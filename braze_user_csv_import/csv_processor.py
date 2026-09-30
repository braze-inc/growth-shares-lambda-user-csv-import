"""Read a user-attribute CSV and turn it into Braze ``/users/track`` batches.

Use a local file when testing the parser. Nothing is sent to Braze unless
you call ``process_file`` or pass ``--post``.

Example::

    from braze_user_csv_import import CsvProcessor

    processor = CsvProcessor.from_file("tests/fixtures/sample_users.csv")
    payloads = processor.build_track_payloads()

Command line::

    python -m braze_user_csv_import csv tests/fixtures/sample_users.csv
    python -m braze_user_csv_import.csv_processor tests/fixtures/sample_users.csv
"""

import argparse
import csv
import json
from collections.abc import Iterator

if __package__:
    from .braze_attributes import process_row, process_type_cast
    from .braze_client import post_user_chunks
    from .braze_custom_events import payload_kind, shape_track_row, verify_track_headers
    from .constants import BRAZE_BATCH_SIZE, CHUNK_SIZE, FUNCTION_TIME_OUT, MAX_THREADS
    from .s3_handler import S3Handler, S3ObjectSource
else:
    from braze_attributes import process_row, process_type_cast
    from braze_client import post_user_chunks
    from braze_custom_events import payload_kind, shape_track_row, verify_track_headers
    from constants import BRAZE_BATCH_SIZE, CHUNK_SIZE, FUNCTION_TIME_OUT, MAX_THREADS
    from s3_handler import S3Handler, S3ObjectSource


class LocalFileSource:
    """Byte source for a CSV on disk. Used to exercise the parser without S3."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.content_length = _file_size(file_path)

    def open_stream(self, offset: int):
        handle = open(self.file_path, "rb")
        handle.seek(offset)
        return _ChunkedFile(handle)


class _ChunkedFile:
    """File handle with the ``iter_chunks`` method the CSV reader expects."""

    def __init__(self, handle):
        self._handle = handle

    def iter_chunks(self, chunk_size: int = CHUNK_SIZE):
        while True:
            chunk = self._handle.read(chunk_size)
            if not chunk:
                break
            yield chunk

    def close(self) -> None:
        self._handle.close()


def _file_size(file_path: str) -> int:
    with open(file_path, "rb") as handle:
        handle.seek(0, 2)
        return handle.tell()


def should_terminate(context) -> bool:
    """Return whether this Lambda invocation should hand off to the next one."""
    if context is None:
        return False
    return context.get_remaining_time_in_millis() < FUNCTION_TIME_OUT


class CsvProcessor:
    """Stream a CSV and post attribute updates in Braze-sized batches.

    Construct it with an S3 bucket and key (the Lambda path), or use
    ``from_file`` / ``from_s3``. ``collect_attributes`` and
    ``build_track_payloads`` do not call Braze.
    """

    def __init__(
        self,
        bucket_name: str | None = None,
        object_key: str | None = None,
        offset: int = 0,
        headers: list[str] | None = None,
        type_cast: dict[str, type] | None = None,
        *,
        file_path: str | None = None,
        source=None,
        braze_client=None,
        chunk_size: int = CHUNK_SIZE,
    ) -> None:
        self.processing_offset = 0
        self.total_offset = offset
        self.csv_file = _resolve_source(
            bucket_name=bucket_name,
            object_key=object_key,
            file_path=file_path,
            source=source,
        )
        self.headers = headers
        self.type_cast = type_cast or {}
        self.processed_users = 0
        self.braze_client = braze_client
        self.chunk_size = chunk_size
        self.source_name = _source_name(bucket_name, object_key, file_path, source)
        self.object_type = payload_kind(self.source_name)

    @classmethod
    def from_file(
        cls,
        file_path: str,
        offset: int = 0,
        headers: list[str] | None = None,
        type_cast: dict[str, type] | None = None,
        braze_client=None,
        chunk_size: int = CHUNK_SIZE,
    ) -> "CsvProcessor":
        """Parse ``file_path`` from disk. No AWS credentials are required."""
        return cls(
            offset=offset,
            headers=headers,
            type_cast=type_cast,
            file_path=file_path,
            braze_client=braze_client,
            chunk_size=chunk_size,
        )

    @classmethod
    def from_s3(
        cls,
        bucket_name: str,
        object_key: str,
        offset: int = 0,
        headers: list[str] | None = None,
        type_cast: dict[str, type] | None = None,
        braze_client=None,
        s3_handler: S3Handler | None = None,
        chunk_size: int = CHUNK_SIZE,
    ) -> "CsvProcessor":
        """Read ``s3://bucket_name/object_key``."""
        handler = s3_handler or S3Handler()
        return cls(
            offset=offset,
            headers=headers,
            type_cast=type_cast,
            source=handler.get_source(bucket_name, object_key),
            braze_client=braze_client,
            chunk_size=chunk_size,
        )

    def collect_attributes(self) -> list[dict]:
        """Return track objects for rows that update at least one field.

        Does not call Braze. Rows with only an identifier are skipped.
        """
        return list(self._iter_processed_rows())

    def build_track_payloads(self, batch_size: int = BRAZE_BATCH_SIZE) -> list[dict]:
        """Return ``/users/track`` bodies, one per batch.

        The array name is ``attributes``, ``events``, or ``purchases``, chosen
        from the file name. Each array has at most ``batch_size`` objects.
        ``batch_size`` cannot exceed 75.
        """
        if batch_size < 1 or batch_size > BRAZE_BATCH_SIZE:
            raise ValueError(f"batch_size must be from 1 to {BRAZE_BATCH_SIZE}")
        rows = self.collect_attributes()
        payloads = []
        for start in range(0, len(rows), batch_size):
            payloads.append({self.object_type: rows[start:start + batch_size]})
        return payloads

    def process_file(self, context=None, batch_size: int = BRAZE_BATCH_SIZE) -> None:
        """Read the CSV and post users to Braze.

        Rows are grouped into ``batch_size`` (max 75) and flushed
        ``MAX_THREADS`` batches at a time. Pass a Lambda context to stop
        near the 10 minute mark. Pass ``context=None`` for a local run that
        reads the whole file.
        """
        if batch_size < 1 or batch_size > BRAZE_BATCH_SIZE:
            raise ValueError(f"batch_size must be from 1 to {BRAZE_BATCH_SIZE}")

        user_rows: list[dict] = []
        user_row_chunks: list[list[dict]] = []
        for processed_row in self._iter_processed_rows():
            user_rows.append(processed_row)
            if len(user_rows) == batch_size:
                user_row_chunks.append(user_rows)
                user_rows = []

            if len(user_row_chunks) == MAX_THREADS:
                self.post_users(user_row_chunks)
                if should_terminate(context):
                    break
                user_row_chunks = []
        else:
            if user_rows:
                user_row_chunks.append(user_rows)
            self.post_users(user_row_chunks)

    def iter_lines(self) -> Iterator[str]:
        """Yield decoded CSV lines, reading ``chunk_size`` bytes at a time."""
        object_stream = self.csv_file.open_stream(self.total_offset)
        leftover = b""
        try:
            for chunk in object_stream.iter_chunks(chunk_size=self.chunk_size):
                data = leftover + chunk

                # Current chunk is not the end of the file.
                if len(data) + self.total_offset < self.csv_file.content_length:
                    last_newline = data.rfind(b"\n")
                    data, leftover = data[:last_newline], data[last_newline:]

                for line in data.splitlines(keepends=True):
                    self.processing_offset += len(line)
                    yield line.decode("utf-8")

            # Last empty new line in the file.
            if leftover == b"\n":
                self.total_offset += len(leftover)
        finally:
            close = getattr(object_stream, "close", None)
            if close:
                close()

    def post_users(self, user_chunks: list[list]) -> None:
        """POST batched users and advance the committed byte offset."""
        if self.braze_client is not None and hasattr(self.braze_client, "track_object_chunks"):
            updated = self.braze_client.track_object_chunks(
                user_chunks,
                object_type=self.object_type,
            )
        elif self.braze_client is not None:
            updated = self.braze_client.track_attribute_chunks(user_chunks)
        else:
            updated = post_user_chunks(user_chunks, object_type=self.object_type)
        self.processed_users += updated
        self._move_offset()

    def is_finished(self) -> bool:
        """Return whether the file has no further rows to import."""
        return (
            not self.processed_users
            or not self.total_offset
            or self.total_offset >= self.csv_file.content_length
        )

    def _iter_processed_rows(self) -> Iterator[dict]:
        self.processing_offset = 0
        reader = csv.DictReader(self.iter_lines(), fieldnames=self.headers)
        verify_track_headers(reader.fieldnames, self.type_cast, self.object_type)
        self.headers = reader.fieldnames or self.headers

        for row in reader:
            try:
                processed_row = process_row(row, self.type_cast)
                shaped = shape_track_row(processed_row, self.object_type)
            except Exception as exc:
                print(
                    f"ERROR: Could not process row - {str(exc)}. Failing row: {dict(row)}"
                )
                continue

            if shaped is None:
                continue
            yield shaped

    def _move_offset(self) -> None:
        self.total_offset += self.processing_offset
        self.processing_offset = 0


def _source_name(bucket_name, object_key, file_path, source) -> str:
    if file_path:
        return file_path
    if object_key:
        return object_key
    if source is not None:
        return getattr(source, "file_path", None) or getattr(source, "object_key", None) or ""
    return bucket_name or ""


def _resolve_source(bucket_name, object_key, file_path, source):
    if source is not None:
        return source
    if file_path is not None:
        return LocalFileSource(file_path)
    if bucket_name and object_key:
        return S3ObjectSource(bucket_name, object_key)
    raise ValueError("Provide bucket_name and object_key, file_path, or source")


def main(argv: list[str] | None = None) -> int:
    """Print ``/users/track`` payloads for a local CSV, or post them."""
    parser = argparse.ArgumentParser(
        description="Convert a user-attribute CSV into Braze /users/track payloads."
    )
    parser.add_argument("csv_file", help="Path to a local CSV file")
    parser.add_argument("--offset", type=int, default=0, help="Byte offset to start at")
    parser.add_argument(
        "--type-cast",
        default="",
        help="column=type pairs, for example zip_code=string,active_flag=boolean",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BRAZE_BATCH_SIZE,
        help=f"Attribute objects per payload (1-{BRAZE_BATCH_SIZE})",
    )
    parser.add_argument(
        "--post",
        action="store_true",
        help="POST the users to Braze. Requires BRAZE_API_URL and BRAZE_API_KEY.",
    )
    args = parser.parse_args(argv)
    if args.batch_size < 1 or args.batch_size > BRAZE_BATCH_SIZE:
        parser.error(f"--batch-size must be from 1 to {BRAZE_BATCH_SIZE}")

    processor = CsvProcessor.from_file(
        args.csv_file,
        offset=args.offset,
        type_cast=process_type_cast(args.type_cast),
    )
    if args.post:
        processor.process_file(batch_size=args.batch_size)
        print(json.dumps({
            "users_processed": processor.processed_users,
            "bytes_read": processor.total_offset - args.offset,
            "is_finished": processor.is_finished(),
        }))
        return 0

    print(json.dumps(processor.build_track_payloads(batch_size=args.batch_size), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
