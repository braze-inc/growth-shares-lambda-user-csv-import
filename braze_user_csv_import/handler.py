"""Lambda orchestration: S3 event, CSV processing, continuation, and SNS.

The callable entrypoint is ``lambda_handler``. ``app.py`` re-exports it so the
deployed handler stays ``app.lambda_handler``.
"""

import json

import boto3

if __package__:
    from .braze_attributes import process_type_cast
    from .config import get_topic_arn, get_type_cast_setting
    from .csv_processor import CsvProcessor
    from .s3_handler import S3Handler
else:
    from braze_attributes import process_type_cast
    from config import get_topic_arn, get_type_cast_setting
    from csv_processor import CsvProcessor
    from s3_handler import S3Handler


def lambda_handler(event, context):
    """Receive an S3 upload event and import the CSV into Braze.

    :param event: S3 event, plus optional ``offset`` and ``headers`` when this
        invocation continues a file that did not finish
    :param context: Lambda context. ``None`` skips the runtime hand-off check
        inside the CSV processor only if you call ``CsvProcessor`` yourself;
        this handler still publishes SNS and may invoke a follow-up function.
    """
    print("New CSV to Braze import process started")
    bucket_name, object_key = S3Handler.parse_upload_event(event)
    type_cast = process_type_cast(get_type_cast_setting())

    print(f"Processing {bucket_name}/{object_key}")
    csv_processor = CsvProcessor(
        bucket_name,
        object_key,
        event.get("offset", 0),
        event.get("headers", None),
        type_cast,
    )

    try:
        csv_processor.process_file(context)
    except Exception as exc:
        fatal_event = create_event(
            event,
            csv_processor.total_offset,
            csv_processor.headers,
        )
        handle_fatal_error(
            exc,
            csv_processor.processed_users,
            fatal_event,
            object_key,
        )
        raise

    print(f"Processed {csv_processor.processed_users:,} users")
    if not csv_processor.is_finished():
        start_next_process(
            context.function_name,
            event,
            csv_processor.total_offset,
            csv_processor.headers,
        )
    else:
        print(f"File {object_key} import is complete")

    publish_message(object_key, True, csv_processor.processed_users)
    return {
        "users_processed": csv_processor.processed_users,
        "bytes_read": csv_processor.total_offset - event.get("offset", 0),
        "is_finished": csv_processor.is_finished(),
    }


def start_next_process(function_name: str, event: dict, offset: int, headers) -> None:
    """Invoke this function again, asynchronously, at ``offset``."""
    print("Starting new user processing lambda..")
    new_event = create_event(event, offset, headers)
    boto3.client("lambda").invoke(
        FunctionName=function_name,
        InvocationType="Event",
        Payload=json.dumps(new_event),
    )


def create_event(received_event: dict, byte_offset: int, headers) -> dict:
    """Copy the invocation event and record how far the file was read."""
    return {
        **received_event,
        "offset": byte_offset,
        "headers": headers,
    }


def publish_message(file_name: str, success: bool, users_processed: int) -> None:
    """Publish an import result to SNS when ``TOPIC_ARN`` is set."""
    topic_arn = get_topic_arn()
    if not topic_arn:
        print("No topic ARN provided. Skipping publishing a message")
        return

    print("Publishing a message to SNS")
    message = json.dumps({
        "fileName": file_name,
        "success": success,
        "usersProcessed": users_processed,
    })
    boto3.client("sns").publish(
        TargetArn=topic_arn,
        Message=message,
    )


def handle_fatal_error(error: Exception, processed_users: int, event: dict, file_name: str) -> None:
    """Log the continuation event and publish a failure notification."""
    print(f'Encountered error: "{error}"')
    print(f"Processed {processed_users:,} users")
    print("Use the event below to continue processing the file:")
    print(json.dumps(event))
    publish_message(file_name, False, processed_users)
