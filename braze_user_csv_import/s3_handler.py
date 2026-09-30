"""Read the CSV object that triggered the Lambda, or inspect an S3 object directly.

Lambda deployment imports this module as ``s3_handler``. Locally it is
``braze_user_csv_import.s3_handler``.

Example::

    python -m braze_user_csv_import s3 my-bucket uploads/users.csv
"""

import argparse
import json
from urllib.parse import unquote_plus

import boto3


class S3ObjectSource:
    """Byte source for one S3 object. ``content_length`` is the full object size."""

    def __init__(self, bucket_name: str, object_key: str, resource=None):
        self.bucket_name = bucket_name
        self.object_key = object_key
        resource = resource or boto3.resource("s3")
        self._object = resource.Object(bucket_name, object_key)

    @property
    def content_length(self) -> int:
        return self._object.content_length

    def open_stream(self, offset: int):
        """Return a streaming body starting at ``offset`` bytes."""
        return self._object.get(Range=f"bytes={offset}-")["Body"]


class S3Handler:
    """Small wrapper around the S3 resource used by the importer."""

    def __init__(self, s3_resource=None):
        self._resource = s3_resource

    def _resource_or_default(self):
        if self._resource is None:
            self._resource = boto3.resource("s3")
        return self._resource

    def get_source(self, bucket_name: str, object_key: str) -> S3ObjectSource:
        return S3ObjectSource(bucket_name, object_key, self._resource_or_default())

    @staticmethod
    def parse_upload_event(event: dict) -> tuple[str, str]:
        """Return ``(bucket, key)`` from an S3 ``ObjectCreated`` event.

        The object key is URL-decoded the same way S3 notification keys are
        encoded (spaces may arrive as ``+``).
        """
        record = event["Records"][0]
        bucket_name = record["s3"]["bucket"]["name"]
        object_key = unquote_plus(record["s3"]["object"]["key"])
        return bucket_name, object_key


def main(argv: list[str] | None = None) -> int:
    """Read a CSV from S3 and print ``/users/track`` payloads, or post them."""
    parser = argparse.ArgumentParser(
        description="Read a user-attribute CSV from S3 and build Braze /users/track payloads."
    )
    parser.add_argument("bucket", help="S3 bucket name")
    parser.add_argument("key", help="S3 object key of the CSV file")
    parser.add_argument("--offset", type=int, default=0, help="Byte offset to start at")
    parser.add_argument(
        "--type-cast",
        default="",
        help="column=type pairs, for example zip_code=string,active_flag=boolean",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Attribute objects per payload. Cannot exceed the Braze limit of 75.",
    )
    parser.add_argument(
        "--post",
        action="store_true",
        help="POST the users to Braze. Requires BRAZE_API_URL and BRAZE_API_KEY.",
    )
    args = parser.parse_args(argv)

    if __package__:
        from .attributes import process_type_cast
        from .constants import BRAZE_BATCH_SIZE
        from .csv_processor import CsvProcessor
    else:
        from attributes import process_type_cast
        from constants import BRAZE_BATCH_SIZE
        from csv_processor import CsvProcessor

    batch_size = BRAZE_BATCH_SIZE if args.batch_size is None else args.batch_size
    if batch_size < 1 or batch_size > BRAZE_BATCH_SIZE:
        parser.error(f"--batch-size must be from 1 to {BRAZE_BATCH_SIZE}")

    processor = CsvProcessor.from_s3(
        args.bucket,
        args.key,
        offset=args.offset,
        type_cast=process_type_cast(args.type_cast),
    )
    if args.post:
        processor.process_file(batch_size=batch_size)
        print(json.dumps({
            "users_processed": processor.processed_users,
            "bytes_read": processor.total_offset - args.offset,
            "is_finished": processor.is_finished(),
        }))
        return 0

    print(json.dumps(processor.build_track_payloads(batch_size=batch_size), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
