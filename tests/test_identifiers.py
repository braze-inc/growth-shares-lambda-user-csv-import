from pathlib import Path

from braze_user_csv_import.csv_processor import CsvProcessor

FIXTURES = Path(__file__).resolve().parent / "fixtures"
USERS = FIXTURES / "sample_identifier_users.csv"
EVENTS = FIXTURES / "sample_identifier_events.csv"
PURCHASES = FIXTURES / "sample_identifier_purchases.csv"

ALIAS = {"alias_name": "device123", "alias_label": "my_device_identifier"}


def test_attribute_identifiers(capsys):
    rows = CsvProcessor.from_file(str(USERS)).collect_attributes()

    assert rows == [
        {
            "external_id": "abc123",
            "email": "solomon@example.com",
            "loyalty_point": 1982,
        },
        {"external_id": "def456", "loyalty_point": 578},
        {"user_alias": ALIAS, "loyalty_point": 12},
        {"braze_id": "64f1a2b3c4d5e6f7a8b9c0d1", "loyalty_point": 7},
        {"email": "hunter@example.com", "loyalty_point": 578},
        {"phone": "+15043277269", "loyalty_point": 3},
        {
            "email": "both@example.com",
            "phone": "+15045550100",
            "loyalty_point": 4,
        },
    ]
    logged = capsys.readouterr().out
    assert "missing external_id" in logged
    assert "multiple primary identifiers" in logged
    assert "user_alias must be an object" in logged


def test_event_identifiers(capsys):
    rows = CsvProcessor.from_file(str(EVENTS)).collect_attributes()

    assert rows == [
        {
            "external_id": "user1",
            "email": "solomon@example.com",
            "name": "watched_trailer",
            "time": "2013-07-16T19:20:30+01:00",
            "properties": {"movie": "The Sad Egg"},
        },
        {
            "user_alias": ALIAS,
            "name": "rented_movie",
            "time": "2013-07-16T19:20:45+01:00",
            "properties": {"movie": "The Sad Egg"},
        },
        {
            "braze_id": "64f1a2b3c4d5e6f7a8b9c0d1",
            "name": "added_favorite",
            "time": "2022-12-06T19:20:45+01:00",
            "properties": {"movie": "Solomon"},
        },
        {
            "email": "hunter@example.com",
            "name": "watched_trailer",
            "time": "2013-07-16T19:20:30+01:00",
        },
        {
            "phone": "+15043277269",
            "name": "rented_movie",
            "time": "2013-07-16T19:20:50+01:00",
            "properties": {"movie": "Other"},
        },
    ]
    logged = capsys.readouterr().out
    assert "missing external_id" in logged
    assert "multiple primary identifiers" in logged
    assert all("email" not in row.get("properties", {}) for row in rows)


def test_purchase_identifiers(capsys):
    rows = CsvProcessor.from_file(str(PURCHASES)).collect_attributes()

    assert rows == [
        {
            "external_id": "user1",
            "email": "solomon@example.com",
            "event_name": "purchased",
            "time": "2013-07-16T19:20:30+01:00",
            "product_id": "backpack",
            "quantity": 1,
            "price": 40.0,
            "currency": "USD",
            "properties": {"color": "red"},
        },
        {
            "user_alias": ALIAS,
            "event_name": "purchased",
            "time": "2013-07-16T19:20:45+01:00",
            "product_id": "pencil",
            "quantity": 2,
            "price": 2.0,
            "currency": "USD",
            "properties": {"color": "blue"},
        },
        {
            "braze_id": "64f1a2b3c4d5e6f7a8b9c0d1",
            "event_name": "purchased",
            "time": "2022-12-06T19:20:45+01:00",
            "product_id": "notebook",
            "quantity": 1,
            "price": 5.0,
            "currency": "USD",
        },
        {
            "email": "hunter@example.com",
            "event_name": "purchased",
            "time": "2013-07-16T19:20:30+01:00",
            "product_id": "mug",
            "quantity": 1,
            "price": 8.0,
            "currency": "USD",
            "properties": {"color": "green"},
        },
        {
            "phone": "+15043277269",
            "event_name": "purchased",
            "time": "2013-07-16T19:20:50+01:00",
            "product_id": "hat",
            "quantity": 1,
            "price": 15.0,
            "currency": "USD",
        },
    ]
    logged = capsys.readouterr().out
    assert "missing external_id" in logged
    assert "multiple primary identifiers" in logged


def test_identifier_need_not_be_the_first_column(tmp_path):
    users = tmp_path / "users.csv"
    users.write_text("loyalty_point,external_id\n1982,abc123\n")
    assert CsvProcessor.from_file(str(users)).collect_attributes() == [
        {"loyalty_point": 1982, "external_id": "abc123"}
    ]

    events = tmp_path / "batch_events.csv"
    events.write_text(
        "movie,event_name,time,email\n"
        "The Sad Egg,rented_movie,2013-07-16T19:20:45+01:00,hunter@example.com\n"
    )
    assert CsvProcessor.from_file(str(events)).collect_attributes() == [
        {
            "email": "hunter@example.com",
            "name": "rented_movie",
            "time": "2013-07-16T19:20:45+01:00",
            "properties": {"movie": "The Sad Egg"},
        }
    ]

    purchases = tmp_path / "batch_purchases.csv"
    purchases.write_text(
        "color,event_name,time,product_id,price,currency,braze_id\n"
        "red,purchased,2013-07-16T19:20:30+01:00,backpack,40.00,USD,64f1a2b3c4d5e6f7a8b9c0d1\n"
    )
    assert CsvProcessor.from_file(str(purchases)).collect_attributes() == [
        {
            "braze_id": "64f1a2b3c4d5e6f7a8b9c0d1",
            "event_name": "purchased",
            "time": "2013-07-16T19:20:30+01:00",
            "product_id": "backpack",
            "price": 40.0,
            "currency": "USD",
            "properties": {"color": "red"},
        }
    ]


def test_header_without_identifier_fails(tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("city,name\nBoston,Ann\n")
    processor = CsvProcessor.from_file(str(csv_path))

    try:
        processor.collect_attributes()
    except ValueError as exc:
        assert "external_id" in str(exc)
    else:
        raise AssertionError("expected a missing identifier column to fail the file")
