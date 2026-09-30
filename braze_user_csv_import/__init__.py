"""Import Braze user attributes from a CSV file."""

__version__ = "0.1.4"

if __package__:
    from .app import lambda_handler
    from .braze_client import BrazeClient
    from .csv_processor import CsvProcessor
    from .errors import APIRetryError, FatalAPIError
    from .s3_handler import S3Handler
else:
    from app import lambda_handler
    from braze_client import BrazeClient
    from csv_processor import CsvProcessor
    from errors import APIRetryError, FatalAPIError
    from s3_handler import S3Handler

__all__ = [
    "APIRetryError",
    "BrazeClient",
    "CsvProcessor",
    "FatalAPIError",
    "S3Handler",
    "lambda_handler",
]
