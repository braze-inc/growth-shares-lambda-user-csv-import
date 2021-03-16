"""This lambda function processes a CSV file to update user attributes within
Braze by using Braze API `users/track <https://www.braze.com/docs/api/endpoints/user_data/post_user_track/>`_
endpoint.

The expected CSV format is:
`external_id,attr_1,...attr_N` -- where the first column specifies external_id
of the user to be updated and every column afterwards specifies an attribute
to update.

The lambda will run up for to 12 minutes. If the file is not processed until
then, it will automatically deploy another lambda to continue processing
the file from where it left off.

The CSV file is streamed by 1024 byte chunks. User updates are posted to Braze
platform as the processing goes on, in 75 user chunks which is the maximum
amount of users supported by the Braze API.
"""

import sys
import csv
import os
import ast
import json
import requests
from time import sleep
from threading import Lock
from concurrent.futures.thread import ThreadPoolExecutor
from typing import Dict, Iterator, List

import boto3

# 12 minute function timeout
FUNCTION_RUN_TIME = 12 * 60 * 1_000

# Remaining time threshold to end execution. 900_000 seconds is equal to
# 15 minutes which is the maximum lambda execution time
FUNCTION_TIME_OUT = 900_000 - FUNCTION_RUN_TIME
MAX_THREADS = 20

# In case of an API error
MAX_API_RETRIES = 6
RETRIES = 0

BRAZE_API_URL = os.environ['BRAZE_API_URL']
BRAZE_API_KEY = os.environ['BRAZE_API_KEY']

if BRAZE_API_URL[-1] == '/':
    BRAZE_API_URL = BRAZE_API_URL[:-1]

# re_array_column = re.compile(r"^\[(.+)\]$")
lock = Lock()


def lambda_handler(event, context):
    """Receives S3 file upload event and starts processing the CSV file
    uploaded.

    :param event: Event object containing information about the invoking service
    :param context: Context object, passed to lambda at runtime, providing
                    information about the function and runtime environment
    """
    print("New CSV to Braze import process started")
    bucket_name = event['Records'][0]['s3']['bucket']['name']
    object_key = event['Records'][0]['s3']['object']['key']

    print(f"Processing {bucket_name}/{object_key}")
    reader = CsvProcessor(
        bucket_name,
        object_key,
        event.get("offset", 0),
        event.get("headers", None),
    )
    reader.process_file(context)

    print(f"Processed {reader.processed_users:,} users.")
    if not reader.is_finished():
        _start_next_process(context.function_name, event,
                            reader.offset, reader.headers)

    return {
        "users_processed": reader.processed_users,
        "bytes_read": reader.offset - event.get("offset", 0),
        "is_finished": reader.is_finished()
    }


class CsvProcessor:
    """Class responsible for reading and processing the CSV file, and delegating
    the user attribute update to background threads.

    :param bucket_name: S3 bucket name to get the object from
    :param object_key: S3 object key of the CSV file to process
    :param offset: Amount of bytes read already from the file
    :param headers: CSV file headers
    """

    def __init__(self, bucket_name: str, object_key: str,
                 offset: int = 0, headers: List[str] = None) -> None:
        self.offset = offset
        self.csv_file = _get_file_from_s3(bucket_name, object_key)
        self.headers = headers

        self.processed_users = 0

    def process_file(self, context) -> None:
        """Processes the CSV file.

        It reads the file by 1,024 byte chunks and iterates over each line.
        It collects users into 75-user chunks which is the maximum amount
        of users Braze API accepts. Once there are enough chunks collected,
        it uploads them concurrently from background threads.
        The number of background threads used and the number of user chunks
        collected is equal to `MAX_THREADS`.

        :param context: Context object providing information about the
                        function and runtime environment
        """
        reader = csv.DictReader(self.iter_lines(), fieldnames=self.headers)
        _verify_header_format(reader.fieldnames)

        user_rows, user_row_chunks = [], []
        for row in reader:
            _process_row(row)
            user_rows.append(row)
            if len(user_rows) == 75:
                user_row_chunks.append(user_rows)
                user_rows = []

            if len(user_row_chunks) == MAX_THREADS:
                self.post_users(user_row_chunks)
                if _should_terminate(context):
                    break
                user_row_chunks = []

        else:  # no break
            if user_rows:
                user_row_chunks.append(user_rows)
                self.post_users(user_row_chunks)

        self.headers = reader.fieldnames or self.headers

    def iter_lines(self) -> Iterator:
        """Iterates over lines in the object.

        Reads chunks of data (1,024 bytes) by default, and splits it into lines.
        Yields each line separately.
        """
        object_stream = _get_object_stream(self.csv_file, self.offset)
        leftover = b""
        for chunk in object_stream.iter_chunks():
            data = leftover + chunk
            last_newline = data.rfind(b"\n")
            data, leftover = data[:last_newline], data[last_newline:]
            for line in data.splitlines(keepends=True):
                self.offset += len(line)
                yield line.decode("utf-8")

        if leftover == b'\n':
            self.offset += len(leftover)

    def post_users(self, user_chunks: List[List]) -> None:
        """Posts users from up to `MAX_THREADS` simultaneously.
        Max threads is set at 20, by default.

        :param user_chunks: List of dictionaries where each key is the CSV
                            header with the attribute namesand each values is
                            the corresponding attribute value
        """
        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            try:
                results = executor.map(_post_to_braze, user_chunks)
                for result in results:
                    self.processed_users += result
            except RuntimeError:
                print(f"Processed {self.processed_users} users")
                sys.exit()

    def is_finished(self) -> bool:
        """Returns whether the end of file was reached."""
        return self.offset >= self.csv_file.content_length


def _get_file_from_s3(bucket_name: str, object_key: str):
    """Return the S3 Object with `object_key` name, from `bucket_name` S3
    bucket."""
    return boto3.resource("s3").Object(bucket_name, object_key)


def _get_object_stream(object, offset: int):
    """Returns an object stream from the S3 file, starting at the specified
    offset.

    :param object: Object returned from S3 resource
    :param offset: Byte file offset
    :return: Stream of the S3 object, starting from ``offset``.
    """
    return object.get(Range=f"bytes={offset}-")["Body"]


def _verify_header_format(columns: List[str]) -> None:
    """Verifies that column follow the established format of
    `external_id,attr1,...attrN`

    :param columns: CSV file header columns
    :raises ValueError: if the format didn't meet the requirements
    """
    if columns and columns[0] != 'external_id':
        raise ValueError("File headers don't match the expected format.")


def _process_row(user_row: Dict) -> None:
    """Processes a CSV row.

    If values in a column are formatted as a list of values, for example
    "['Value1', 'Value2']" -- it converts them to a Python list in order
    for Braze API to receive the data as an array rather than a string.

    :param user_row: A single row from the CSV file in a dict form
    """
    for col, value in user_row.items():
        if value[0] == '[' and value[-1] == ']':
            list_values = ast.literal_eval(value)
            list_values = [item.strip() for item in list_values]
            user_row[col] = list_values


def _post_to_braze(users: List[Dict]) -> int:
    """Posts users read from the CSV file to Braze users/track API endpoint.

    Authentication is necessary. Braze Rest API key is expected to be passed
    to the lambda process as an environment variable, under `BRAZE_API_KEY` key.

   :return: The number of users successfully imported
   """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {BRAZE_API_KEY}",
    }
    data = json.dumps({"attributes": users})

    res = requests.post(
        f"{BRAZE_API_URL}/users/track", headers=headers, data=data
    )

    updated = _handle_braze_response(res, users)
    return updated


def _handle_braze_response(response: requests.Response, users: List[Dict]) -> int:
    """Handles response from Braze API. The amount of requests made is well 
    below the limits for the given API endpoint therefore Too Many Requests
    API errors are not expected.

    In case users were posted but there were minor mistakes, the errors will be
    logged. In case the API received data in an unexpected format, the data 
    that caused the issue will be logged.
    In case of an server error, there will be `MAX_API_RETRIES` exponential
    delay requests after which the script will end execution.

    :param response: Response from the API
    :param users: List of users to be updated sent to the API endpoint
    :return: Actual number of users updated
    :raise RuntimeError: After `MAX_API_RETRIES` unsuccessful attempts
    """
    res_text = json.loads(response.text)
    if response.status_code == 201 and 'errors' in res_text:
        print(
            f"Encountered errors processing some users: {res_text['errors']}")
        return len(users) - len(res_text['errors'])

    if response.status_code != 201:
        if response.status_code == 400:
            print(f"Invalid API request format: {res_text}")

        server_error = response.status_code == 429 or response.status_code >= 500
        should_retry = server_error and RETRIES < MAX_API_RETRIES
        if server_error and not should_retry:
            print(f"Max retries reached.")
            raise RuntimeError

        if server_error:
            _wait()
            _post_to_braze(users)

        return 0

    return len(users)


def _start_next_process(function_name: str, event: Dict, offset: int,
                        headers: List[str]) -> None:
    """Starts a new lambda process, passing in current offset in the file.

    :param function_name: Python function name for Lambda to invoke
    :param event: Received S3 event object
    :param offset: The amount of bytes read so far
    :param headers: The headers in the CSV file
    """
    print("Starting new user processing lambda..")
    new_event = {**event, "offset": offset, "headers": headers}
    boto3.client("lambda").invoke(
        FunctionName=function_name,
        InvocationType="Event",
        Payload=json.dumps(new_event),
    )


def _should_terminate(context) -> bool:
    """Return whether lambda should terminate execution."""
    # print(f"Remaining time: {(context.get_remaining_time_in_millis() / 1000 / 60):.2f} min")
    return context.get_remaining_time_in_millis() < FUNCTION_TIME_OUT


def _wait():
    lock.acquire()
    global RETRIES
    RETRIES += 1
    lock.release()

    sleep(2**RETRIES)
