"""Shape a CSV row into a Braze ``/users/track`` purchase object.

https://www.braze.com/docs/api/objects_filters/purchase_object

Identifier columns, ``event_name``, ``time``, ``product_id``, ``quantity``,
``price``, and ``currency`` stay on the purchase object. Every other column
is nested under ``properties``. Braze rejects those reserved names inside
``properties``.
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

OBJECT_TYPE = "purchases"
REQUIRED = ("event_name", "time", "product_id")
TOP_LEVEL = IDENTIFIER_FIELDS + REQUIRED + ("quantity", "price", "currency")


def matches(file_name: str) -> bool:
    """Return whether ``file_name`` contains ``_purchases`` or ends with ``_purchases``."""
    return name_matches(file_name, "_purchases", "_purchases")


def verify_headers(columns: list[str] | None, type_cast: dict) -> None:
    """Require ``event_name``, ``time``, ``product_id``, and an identifier column."""
    verify_required_columns(columns, REQUIRED, type_cast)
    require_identifier_column(columns)


def shape_row(row: dict) -> dict | None:
    """Return one purchase object, or None when a required value is missing."""
    if not row_has_required(row, REQUIRED, "purchase"):
        return None
    if not row_has_identifier(row, "purchase"):
        return None
    purchase = {key: row[key] for key in TOP_LEVEL if key in row}
    properties = properties_except(row, TOP_LEVEL)
    if properties:
        purchase["properties"] = properties
    return purchase
