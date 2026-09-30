import json
from pathlib import Path

import pytest

from braze_user_csv_import.csv_processor import CsvProcessor, main
from braze_user_csv_import.braze_custom_events import payload_kind

EVENTS = Path(__file__).resolve().parent / "fixtures" / "sample_events.csv"
PURCHASES = Path(__file__).resolve().parent / "fixtures" / "sample_purchases.csv"


def test_file_name_selects_track_array():
    assert payload_kind("uploads/sample_events.csv") == "events"
    assert payload_kind("uploads/batch_events_2026.csv") == "events"
    assert payload_kind("uploads/SAMPLE_EVENTS.CSV") == "events"
    assert payload_kind("uploads/sample_purchases.csv") == "purchases"
    assert payload_kind("uploads/batch_purchases_2026.csv") == "purchases"
    assert payload_kind("uploads/users.csv") == "attributes"
    assert payload_kind("uploads/events.csv") == "attributes"
    with pytest.raises(ValueError, match="both"):
        payload_kind("uploads/report_events_purchases.csv")


def test_sample_events_payload():
    rows = CsvProcessor.from_file(str(EVENTS)).collect_attributes()

    assert rows == [
        {
            "external_id": "user1",
            "name": "watched_trailer",
            "time": "2013-07-16T19:20:30+01:00",
        },
        {
            "external_id": "user1",
            "name": "rented_movie",
            "time": "2013-07-16T19:20:45+01:00",
            "properties": {
                "movie": "The Sad Egg",
                "director": "Alex Smith",
                "genres": ["drama", "comedy"],
            },
        },
        {
            "external_id": "abc123",
            "name": "added_favorite",
            "time": "2022-12-06T19:20:45+01:00",
            "properties": {"movie": "Solomon"},
        },
    ]
    payloads = CsvProcessor.from_file(str(EVENTS)).build_track_payloads()
    assert list(payloads[0]) == ["events"]


def test_sample_purchases_payload():
    rows = CsvProcessor.from_file(str(PURCHASES)).collect_attributes()

    assert rows == [
        {
            "external_id": "user1",
            "event_name": "purchased",
            "time": "2013-07-16T19:20:30+01:00",
            "product_id": "backpack",
            "quantity": 1,
            "price": 40.0,
            "currency": "USD",
            "properties": {"color": "red", "size": "Large"},
        },
        {
            "external_id": "user1",
            "event_name": "purchased",
            "time": "2013-07-17T19:20:20+01:00",
            "product_id": "pencil",
            "quantity": 2,
            "price": 2.0,
            "currency": "USD",
            "properties": {"color": "blue"},
        },
    ]
    payloads = CsvProcessor.from_file(str(PURCHASES)).build_track_payloads()
    assert list(payloads[0]) == ["purchases"]


def test_event_row_missing_required_value_is_skipped(tmp_path, capsys):
    csv_path = tmp_path / "batch_events.csv"
    csv_path.write_text(
        "external_id,event_name,time,movie\n"
        "user1,rented_movie,2013-07-16T19:20:45+01:00,Film\n"
        "user2,,2013-07-16T19:20:45+01:00,Film\n"
    )
    rows = CsvProcessor.from_file(str(csv_path)).collect_attributes()
    assert [row["external_id"] for row in rows] == ["user1"]
    assert "missing event_name" in capsys.readouterr().out


def test_event_file_missing_required_column(tmp_path):
    csv_path = tmp_path / "batch_events_2026.csv"
    csv_path.write_text("external_id,event_name,movie\nuser1,rented_movie,Film\n")
    processor = CsvProcessor.from_file(str(csv_path))
    with pytest.raises(ValueError, match="time"):
        processor.collect_attributes()


def test_cli_prints_events_payload(capsys):
    assert main([str(EVENTS)]) == 0
    payloads = json.loads(capsys.readouterr().out)
    assert payloads[0]["events"][1]["name"] == "rented_movie"
    assert "event_name" not in payloads[0]["events"][1]
