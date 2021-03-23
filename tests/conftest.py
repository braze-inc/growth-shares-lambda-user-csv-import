import pytest

from braze_user_csv_import import app


@pytest.fixture
def mock_file_upload_event():
    """ Generates S3 bucket upload Event"""
    return {
        "Records": [
            {
                "eventVersion": "2.0",
                "eventSource": "aws:s3",
                "awsRegion": "us-east-1",
                "eventTime": "1970-01-01T00:00:00.000Z",
                "eventName": "ObjectCreated:Put",
                "userIdentity": {
                    "principalId": "EXAMPLE"
                },
                "requestParameters": {
                    "sourceIPAddress": "127.0.0.1"
                },
                "responseElements": {
                    "x-amz-request-id": "EXAMPLE123456789",
                    "x-amz-id-2": "EXAMPLE123/5678abcdefghijklambdaisawesome/mnopqrstuvwxyzABCDEFGH"
                },
                "s3": {
                    "s3SchemaVersion": "1.0",
                    "configurationId": "testConfigRule",
                    "bucket": {
                        "name": "csv-ingest-lambda",
                        "ownerIdentity": {
                            "principalId": "EXAMPLE"
                        },
                        "arn": "arn:aws:s3:::csv-ingest-lambda"
                    },
                    "object": {
                        "key": "1k_10_attr_no_array.csv",
                        "size": 1024,
                        "eTag": "0123456789abcdef0123456789abcdef",
                        "sequencer": "0A1B2C3D4E5F678901"
                    }
                }
            }
        ]
    }


@pytest.fixture
def users():
    return [{"external_id": 1, "attribute1": "value1"},
            {"external_id": 2, "attribute1": "value2"}]


@pytest.fixture
def csv_processor():
    return app.CsvProcessor(
        bucket_name="test",
        object_key="test",
        offset=0,
        headers=None
    )
