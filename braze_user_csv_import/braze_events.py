"""Shape a CSV row into a Braze ``/users/track`` event object.

https://www.braze.com/docs/api/objects_filters/event_object

The CSV column ``event_name`` is sent as ``name``. Identifier columns stay on
the event. Every other column except ``time`` is nested under ``properties``.
"""

if __package__:
    from .braze_custom_events import (
        IDENTIFIER_FIELDS,
        name_matches,
        properties_except,
        require_identifier_column,
        row_has_identifier,
        row_has_required,
        verify_required_columns,
    )
else:
    from braze_custom_events import (
        IDENTIFIER_FIELDS,
        name_matches,
        properties_except,
        require_identifier_column,
        row_has_identifier,
        row_has_required,
        verify_required_columns,
    )

OBJECT_TYPE = "events"
REQUIRED = ("event_name", "time")
# Identifier fields stay on the event so Braze can resolve the user.
RESERVED = IDENTIFIER_FIELDS + REQUIRED


def matches(file_name: str) -> bool:
    """Return whether ``file_name`` contains ``_events_`` or ends with ``_events``."""
    return name_matches(file_name, "_events_", "_events")


def verify_headers(columns: list[str] | None, type_cast: dict) -> None:
    """Require ``event_name``, ``time``, and an identifier column."""
    verify_required_columns(columns, REQUIRED, type_cast)
    require_identifier_column(columns)


def shape_row(row: dict) -> dict | None:
    """Return one event object, or None when a required value is missing."""
    if not row_has_required(row, REQUIRED, "event"):
        return None
    if not row_has_identifier(row, "event"):
        return None
    event = {key: row[key] for key in IDENTIFIER_FIELDS if key in row}
    event["name"] = row["event_name"]
    event["time"] = row["time"]
    properties = properties_except(row, RESERVED)
    if properties:
        event["properties"] = properties
    return event
