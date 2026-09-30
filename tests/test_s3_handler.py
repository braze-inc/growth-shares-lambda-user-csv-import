from braze_user_csv_import.s3_handler import S3Handler


def test_parse_upload_event_decodes_object_key():
    event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "braze-user-csv-import"},
                    "object": {"key": "folder/my+file.csv"},
                }
            }
        ]
    }

    assert S3Handler.parse_upload_event(event) == (
        "braze-user-csv-import",
        "folder/my file.csv",
    )
