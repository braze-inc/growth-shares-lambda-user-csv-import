import json
import os
import subprocess
import sys
from pathlib import Path

from braze_user_csv_import.braze_attributes import process_type_cast
from braze_user_csv_import.csv_processor import CsvProcessor, main

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample_users.csv"


class _RecordingClient:
    def __init__(self):
        self.chunks = []

    def track_attribute_chunks(self, user_chunks):
        self.chunks.extend(user_chunks)
        return sum(len(chunk) for chunk in user_chunks)


def test_sample_file_attribute_values():
    rows = CsvProcessor.from_file(str(SAMPLE)).collect_attributes()

    assert rows == [
        {
            "external_id": "abc123",
            "loyalty_point": 1982,
            "last_brand_purchased": "Solomon",
            "lifetime_spend": 12.5,
            "is_member": True,
            "zip_code": "02134",
            "favorite_colors": ["red", "blue"],
            "phone": "972-000-0000",
            "custom_attribute": None,
            "active_flag": 1,
        },
        {
            "external_id": "def456",
            "loyalty_point": 578,
            "last_brand_purchased": "Hunter-Hayes",
            "lifetime_spend": 0,
            "is_member": False,
            "zip_code": "01001",
            "favorite_colors": ["green"],
            "custom_attribute": "gold",
            "active_flag": 0,
        },
        {
            "external_id": "0166ecc9-asd9-0305-sjn9-efd44fe61b96",
            "loyalty_point": 0,
            "last_brand_purchased": "Acme",
            "lifetime_spend": -4.23,
            "is_member": True,
            "zip_code": "01234",
            "favorite_colors": [9.12, 1, 4],
            "phone": "555-0100",
            "active_flag": 1,
        },
    ]


def test_sample_file_type_cast_and_batches():
    processor = CsvProcessor.from_file(
        str(SAMPLE),
        type_cast=process_type_cast("active_flag=boolean,zip_code=string"),
    )
    payloads = processor.build_track_payloads(batch_size=2)

    assert len(payloads) == 2
    assert [len(payload["attributes"]) for payload in payloads] == [2, 1]
    assert payloads[0]["attributes"][0]["active_flag"] is True
    assert payloads[0]["attributes"][1]["active_flag"] is False
    assert payloads[0]["attributes"][0]["zip_code"] == "02134"


def test_sample_file_posts_without_calling_braze_network():
    client = _RecordingClient()
    processor = CsvProcessor.from_file(str(SAMPLE), braze_client=client)

    processor.process_file()

    assert processor.processed_users == 3
    assert processor.is_finished()
    assert [row["external_id"] for chunk in client.chunks for row in chunk] == [
        "abc123",
        "def456",
        "0166ecc9-asd9-0305-sjn9-efd44fe61b96",
    ]


def test_cli_prints_track_payload(capsys):
    assert main([str(SAMPLE), "--batch-size", "75"]) == 0
    payloads = json.loads(capsys.readouterr().out)
    assert payloads[0]["attributes"][0]["external_id"] == "abc123"
    assert payloads[0]["attributes"][0]["custom_attribute"] is None


def test_email_identifier_does_not_require_external_id(tmp_path):
    csv_path = tmp_path / "by_email.csv"
    csv_path.write_text("email,city\nann@example.com,Boston\n")
    rows = CsvProcessor.from_file(str(csv_path)).collect_attributes()
    assert rows == [{"email": "ann@example.com", "city": "Boston"}]


def test_lambda_zip_layout_imports_app_flat():
    """The deployed zip is the package directory, with handler app.lambda_handler."""
    package_dir = Path(__file__).resolve().parents[1] / "braze_user_csv_import"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(package_dir)
    completed = subprocess.run(
        [sys.executable, "-c", "import app; assert callable(app.lambda_handler)"],
        cwd=package_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
