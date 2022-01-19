"""This lambda function processes a CSV file to update user attributes within
Braze by using Braze API `users/track <https://www.braze.com/docs/api/endpoints/user_data/post_user_track/>`_
endpoint.

The expected CSV format is:
`external_id,attr_1,...attr_N` -- where the first column specifies external_id
of the user to be updated and every column afterwards specifies an attribute
to update.

The lambda will run up for to 10 minutes. If the file is not processed until
then, it will automatically deploy another lambda to continue processing
the file from where it left off.

The CSV file is streamed by 10MB chunks. User updates are posted to Braze
platform as the processing goes on, in 75 user chunks which is the maximum
amount of users supported by the Braze API.
"""

import csv
import os
import ast
import json
from concurrent.futures.thread import ThreadPoolExecutor
from typing import Dict, Iterator, List, Optional, Sequence, Type, Union

import requests
import boto3
from urllib.parse import unquote_plus
from requests.exceptions import RequestException
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type  # type: ignore


# 10 minute function timeout
FUNCTION_RUN_TIME = 10 * 60 * 1_000

# Remaining time threshold to end execution. 900_000 seconds is equal to
# 15 minutes which is the maximum lambda execution time
FUNCTION_TIME_OUT = 900_000 - FUNCTION_RUN_TIME
MAX_THREADS = 20
MAX_RETRIES = 5

BRAZE_API_URL = os.environ['BRAZE_API_URL']
BRAZE_API_KEY = os.environ['BRAZE_API_KEY']

if BRAZE_API_URL[-1] == '/':
    BRAZE_API_URL = BRAZE_API_URL[:-1]

TypeMap = Dict[str, Type]


def lambda_handler(event, context):
    """Receives S3 file upload event and starts processing the CSV file
    uploaded.

    :param event: Event object containing information about the invoking service
    :param context: Context object, passed to lambda at runtime, providing
                    information about the function and runtime environment
    """
    print("New CSV to Braze import process started")
    bucket_name = event['Records'][0]['s3']['bucket']['name']
    object_key = unquote_plus(event['Records'][0]['s3']['object']['key'])
    type_cast = _process_type_cast(os.environ.get('TYPE_CAST'))

    print(f"Processing {bucket_name}/{object_key}")
    csv_processor = CsvProcessor(
        bucket_name,
        object_key,
        event.get("offset", 0),
        event.get("headers", None),
        type_cast
    )

    try:
        csv_processor.process_file(context)
    except Exception as e:
        event = _create_event(
            event,
            csv_processor.total_offset,
            csv_processor.headers
        )
        _handle_fatal_error(str(e), csv_processor.processed_users, event)
        raise

    print(f"Processed {csv_processor.processed_users:,} users.")
    if not csv_processor.is_finished():
        _start_next_process(
            context.function_name,
            event,
            csv_processor.total_offset,
            csv_processor.headers
        )

    return {
        "users_processed": csv_processor.processed_users,
        "bytes_read": csv_processor.total_offset - event.get("offset", 0),
        "is_finished": csv_processor.is_finished()
    }


class CsvProcessor:
    """Class responsible for reading and processing the CSV file, and delegating
    the user attribute update to background threads.

    :param bucket_name: S3 bucket name to get the object from
    :param object_key: S3 object key of the CSV file to process
    :param offset: Amount of bytes read already from the file
    :param headers: CSV file headers
    """

    def __init__(
        self,
        bucket_name: str,
        object_key: str,
        offset: int = 0,
        headers: List[str] = None,
        type_cast: TypeMap = None
    ) -> None:
        self.processing_offset = 0
        self.total_offset = offset
        self.csv_file = _get_file_from_s3(bucket_name, object_key)
        self.headers = headers
        self.type_cast = type_cast or {}

        self.processed_users = 0

    def process_file(self, context) -> None:
        """Processes the CSV file.

        It reads the file by 10MB chunks and iterates over each line.
        It collects users into 75-user chunks which is the maximum amount
        of users Braze API accepts. Once there are enough chunks collected,
        it uploads them concurrently from background threads.
        The number of background threads used and the number of user chunks
        collected is equal to `MAX_THREADS`.

        :param context: Context object providing information about the
                        function and runtime environment
        """
        reader = csv.DictReader(self.iter_lines(), fieldnames=self.headers)
        _verify_headers(reader.fieldnames, self.type_cast)

        user_rows, user_row_chunks = [], []
        for row in reader:
            processed_row = _process_row(row, self.type_cast)
            if len(processed_row) <= 1:
                continue

            user_rows.append(processed_row)
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

        Reads chunks of data (10MB) by default, and splits it into lines.
        Yields each line separately.
        """
        chunk_size = 1024*1024*10
        object_stream = _get_object_stream(self.csv_file, self.total_offset)
        leftover = b''
        for chunk in object_stream.iter_chunks(chunk_size=chunk_size):
            data = leftover + chunk

            # Current chunk is not the end of the file
            if len(data) + self.total_offset < self.csv_file.content_length:
                last_newline = data.rfind(b'\n')
                data, leftover = data[:last_newline], data[last_newline:]

            for line in data.splitlines(keepends=True):
                self.processing_offset += len(line)
                yield line.decode("utf-8")

        # Last empty new line in the file
        if leftover == b'\n':
            self.total_offset += len(leftover)

    def post_users(self, user_chunks: List[List]) -> None:
        """Posts updated users to Braze platform using Braze API.

        :param user_chunks: List containing chunked user lists of maximum 75
                            users
        """
        updated = _post_users(user_chunks)
        self.processed_users += updated
        self._move_offset()

    def is_finished(self) -> bool:
        """Returns whether the end of file was reached or there were no rows in the file."""
        return not self.processed_users or not self.total_offset or self.total_offset >= self.csv_file.content_length

    def _move_offset(self) -> None:
        self.total_offset += self.processing_offset
        self.processing_offset = 0


def _get_file_from_s3(bucket_name: str, object_key: str):
    """Returns the S3 Object with `object_key` name, from `bucket_name` S3
    bucket."""
    return boto3.resource("s3").Object(bucket_name, object_key)  # type: ignore


def _get_object_stream(s3_object, offset: int):
    """Returns an object stream from the S3 file, starting at the specified
    offset.

    :param object: Object returned from S3 resource
    :param offset: Byte file offset
    :return: Stream of the S3 object, starting from ``offset``.
    """
    return s3_object.get(Range=f"bytes={offset}-")["Body"]


def _verify_headers(columns: Optional[Sequence[str]], type_cast: TypeMap) -> None:
    """Verifies that column follow the established format of
    `external_id,attr1,...attrN`

    :param columns: CSV file header columns
    :raises ValueError: if the format didn't meet the requirements
    """
    if not columns:
        return

    if columns[0] != 'external_id':
        raise ValueError(
            "File headers don't match the expected format."
            "First column should specify a user's 'external_id'.")

    for column_name in type_cast:
        if column_name not in columns:
            print(f"Warning: Cast column {column_name} not found."
                  "Cast will not be applied.")


def _process_row(user_row: Dict, type_cast: TypeMap) -> Dict:
    """Processes a CSV row, evaluating each value type in the row.

    :param user_row: A single row from the CSV file in a dict form
    """
    processed_row = {}
    for col, value in user_row.items():
        if value.strip() == '':
            continue
        processed_row[col] = _process_value(value, type_cast.get(col))
    return processed_row


def _process_value(
    value: str,
    cast: Type = None
) -> Union[None, str, int, float, list, bool]:
    """Processes a single cell value.

    If there is a forced type cast, returns the type casted value.
    Otherwise, checks the format of the value and returns a correct value type.
    If values in a column are formatted as a list of values, for example
    "['Value1', 'Value2']" -- it converts them to an array.

    :param value: Value in the cell
    :param cast (optional): Forced variable type cast
    :returns: Value of the proper type
    """
    if cast == str:
        return value

    stripped = value.strip().lower()
    leading_zero_int = len(stripped) > 1 and stripped.startswith('0') \
        and not stripped.startswith('0.')
    if cast:
        return cast(_process_value(value))

    if stripped == 'null':
        return None
    elif not leading_zero_int and _is_int(stripped):
        return int(stripped)
    elif not leading_zero_int and _is_float(stripped):
        return float(stripped)
    elif stripped == 'true':
        return True
    elif stripped == 'false':
        return False
    elif len(stripped) > 1 and stripped[0] == '[' and stripped[-1] == ']':
        return ast.literal_eval(stripped)
    else:
        return value


def _post_users(user_chunks: List[List]) -> int:
    """Posts users concurrently to Braze API, using `MAX_THREADS` concurrent
    threads.

    In case of a server error, or in case of Too Many Requests (429)
    client error, the function will employ exponential delay stall and try
    again.

    :return: Number of users successfully updated
    """
    updated = 0
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        results = executor.map(_post_to_braze, user_chunks)
        for result in results:
            updated += result
    return updated


@retry(retry=retry_if_exception_type(RequestException),
       wait=wait_exponential(multiplier=8, min=8, max=120),
       stop=stop_after_attempt(MAX_RETRIES))
def _post_to_braze(users: List[Dict]) -> int:
    """Posts users read from the CSV file to Braze users/track API endpoint.

    Authentication is necessary. Braze Rest API key is expected to be passed
    to the lambda process as an environment variable, under `BRAZE_API_KEY` key.
    In case of a lack of valid API Key, the function will fail.

    Each request is retried 3 times. This retry session takes place in each
    thread individually and it is independent of the global retry strategy.

    :return: The number of users successfully imported
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {BRAZE_API_KEY}",
        "X-Braze-Bulk": "true"
    }
    data = json.dumps({"attributes": users})
    response = requests.post(f"{BRAZE_API_URL}/users/track",
                             headers=headers, data=data)
    error_users = _handle_braze_response(response)
    return len(users) - error_users


def _handle_braze_response(response: requests.Response) -> int:
    """Handles server response from Braze API.

    The amount of requests made is well
    below the limits for the given API endpoint therefore Too Many Requests
    API errors are not expected. In case they do, however, occur - the API
    calls will be re-tried, up to `MAX_API_RETRIES`, using exponential delay.
    In case of a server error, the same strategy will be applied. After max
    retries have been reached, the execution will terminate.

    In case users were posted but there were minor mistakes, the errors will be
    logged. In case the API received data in an unexpected format, the data
    that caused the issue will be logged.

    In any unexpected client API error (other than 400), the function execution
    will terminate.

    :param response: Response from the API
    :return: Number of users that resulted in an error
    :raise APIRetryError: On a 429 or 500 server error
    :raise FatalAPIError: After `MAX_API_RETRIES` unsuccessful retries, or on
                          any non-400 client error
    """
    res_text = json.loads(response.text)
    if response.status_code == 201 and 'errors' in res_text:
        print(
            f"Encountered errors processing some users: {res_text['errors']}")
        return len(res_text['errors'])

    if response.status_code == 400:
        print(f"Encountered error for user chunk. {response.text}")
        return 0

    server_error = response.status_code == 429 or response.status_code >= 500
    if server_error:
        raise APIRetryError("Server error. Retrying..")

    if response.status_code > 400:
        raise FatalAPIError(res_text.get('message', response.text))

    return 0


def _start_next_process(function_name: str, event: Dict, offset: int,
                        headers: Optional[Sequence[str]]) -> None:
    """Starts a new lambda process, passing in current offset in the file.

    :param function_name: Python function name for Lambda to invoke
    :param event: Received S3 event object
    :param offset: The amount of bytes read so far
    :param headers: The headers in the CSV file
    """
    print("Starting new user processing lambda..")
    new_event = _create_event(event, offset, headers)
    boto3.client("lambda").invoke(
        FunctionName=function_name,
        InvocationType="Event",
        Payload=json.dumps(new_event),
    )


def _create_event(received_event: Dict, byte_offset: int,
                  headers: Optional[Sequence[str]]) -> Dict:
    return {
        **received_event,
        "offset": byte_offset,
        "headers": headers
    }


def _should_terminate(context) -> bool:
    """Returns whether lambda should terminate execution."""
    return context.get_remaining_time_in_millis() < FUNCTION_TIME_OUT


def _handle_fatal_error(error_message: str, processed_users: int, event: Dict) -> None:
    """Prints logging information when a fatal error occurred."""
    print(f'Encountered error "{error_message}"')
    print(f"Processed {processed_users:,} users")
    print(f"Use the event below to continue processing the file:")
    print(json.dumps(event))


TYPE_MAP = {
    'string': str,
    'integer': int,
    'float': float,
    'boolean': bool
}


def _process_type_cast(type_cast: Optional[str]) -> Dict:
    """Builds a type casting dictionary where the key represents a column name
    and the value is the type to cast to.
    Valid cast types include: string, integer, float and boolean.
    If the cast type is invalid, the cast will be ignored.

    :param type_cast: Type cast string where each mapping is separate by 
                      a comma and each cast is specified with column_name=type.
                      Example:
                        attribute_name=float,another_name=boolean
    :returns: Type cast dictionary
    """
    cast_map = {}
    if not type_cast:
        return cast_map

    for cast in type_cast.split(','):
        col, t = cast.strip().split('=')
        try:
            assert t in TYPE_MAP
        except AssertionError:
            print(f"Cast type {t} for column {col} not in supported types."
                  "Type will not be applied.")
            continue
        cast_map[col] = TYPE_MAP[t]
    return cast_map


def _is_int(value: str) -> bool:
    try:
        int(value)
        return True
    except Exception:
        return False


def _is_float(value: str) -> bool:
    try:
        float(value)
        return True
    except Exception:
        return False


class APIRetryError(RequestException):
    """Raised on 429 or 5xx server exception. If there are retries left, the
    API call will be made again after a delay."""
    pass


class FatalAPIError(Exception):
    """Raised when received an unexpected error from the server. Causes the
    execution to fail."""
    pass
