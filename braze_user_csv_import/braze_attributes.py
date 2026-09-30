"""Convert CSV cells into Braze user-attribute values.

Call ``process_row`` or ``process_value`` directly to test typing without S3
or Braze. ``process_type_cast`` parses the ``TYPE_CAST`` setting.
"""

import ast

TYPE_MAP = {
    "string": str,
    "integer": int,
    "float": float,
    "boolean": bool,
}

TypeMap = dict[str, type]
OBJECT_TYPE = "attributes"


IDENTIFIER_STRINGS = {"external_id", "braze_id", "email", "phone"}


def verify_headers(columns: list[str] | None, type_cast: TypeMap) -> None:
    """Require a Braze identifier column, then warn about unknown casts.

    The identifier is ``external_id``, or else ``user_alias`` or ``braze_id``,
    or else ``email`` or ``phone``. The file fails when none of those columns
    exist.
    """
    if not columns:
        return

    _require_identifier_column(columns)
    warn_missing_casts(columns, type_cast)


def shape_row(row: dict) -> dict | None:
    """Return an attributes object.

    A row with no identifier is skipped. A row that only has an identifier
    and no attribute is skipped. ``email`` and ``phone`` stay on the object
    when a primary identifier is also present; Braze then treats them as
    profile attributes.
    """
    if not _row_has_identifier(row):
        return None
    if len(row) <= 1:
        return None
    return row


def _require_identifier_column(columns: list[str]) -> None:
    if __package__:
        from .braze_custom_events import require_identifier_column
    else:
        from braze_custom_events import require_identifier_column
    require_identifier_column(columns)


def _row_has_identifier(row: dict) -> bool:
    if __package__:
        from .braze_custom_events import row_has_identifier
    else:
        from braze_custom_events import row_has_identifier
    return row_has_identifier(row, "attribute")


def process_row(user_row: dict, type_cast: TypeMap) -> dict:
    """Convert one CSV row into a Braze attributes object.

    Empty cells are omitted. The string ``null`` becomes JSON ``null``, which
    unsets that attribute in Braze.
    """
    processed_row = {}
    for col, value in user_row.items():
        if value is None:
            print(f"WARNING: None value received for column {col} in row {user_row}")
            continue
        if value.strip() == "":
            continue
        if col == "user_alias":
            processed_row[col] = process_user_alias(value)
        elif col in IDENTIFIER_STRINGS:
            processed_row[col] = process_value(value, str)
        else:
            processed_row[col] = process_value(value, type_cast.get(col))
    return processed_row


def process_user_alias(value: str):
    """Parse a ``user_alias`` cell into ``{alias_name, alias_label}``.

    The cell is a Python dict literal, for example
    ``{'alias_name': 'device123', 'alias_label': 'my_device_identifier'}``.
    A cell that is not a dict is returned unchanged so the row can be skipped.
    """
    stripped = value.strip()
    if len(stripped) > 1 and stripped[0] == "{" and stripped[-1] == "}":
        try:
            parsed = ast.literal_eval(stripped)
        except Exception:
            print("ERROR: Could not convert user_alias:", stripped)
            return value
        if isinstance(parsed, dict):
            return parsed
    return value


def process_value(
    value: str,
    cast: type | None = None,
) -> None | str | int | float | list | bool:
    """Convert one cell.

    A forced cast is applied after the value is parsed, except ``string``,
    which keeps the raw cell. Without a cast, numbers, booleans, ``null``,
    and Python-style lists such as ``"['a', 'b']"`` are inferred. Integers
    with a leading zero stay strings so zip codes are not truncated.
    """
    if cast == str:
        return value

    if cast:
        return cast(process_value(value))

    stripped = value.strip()
    leading_zero_int = (
        len(stripped) > 1 and stripped.startswith("0") and not stripped.startswith("0.")
    )

    is_numeric = stripped.replace(".", "").replace("-", "").isdigit()

    if stripped.lower() == "null":
        return None
    elif is_numeric and not leading_zero_int and is_int(stripped):
        return int(stripped)
    elif is_numeric and not leading_zero_int and is_float(stripped):
        return float(stripped)
    elif stripped.lower() == "true":
        return True
    elif stripped.lower() == "false":
        return False
    elif len(stripped) > 1 and stripped[0] == "[" and stripped[-1] == "]":
        try:
            return ast.literal_eval(stripped)
        except Exception:
            print("ERROR: Could not convert value to an array:", stripped)
            return stripped
    else:
        return value


def process_type_cast(type_cast: str | None) -> TypeMap:
    """Parse ``column=type`` pairs separated by commas.

    Supported types are ``string``, ``integer``, ``float``, and ``boolean``.
    Unknown types are ignored. Example: ``zip_code=string,active_flag=boolean``.
    """
    cast_map: TypeMap = {}
    if not type_cast:
        return cast_map

    for cast in type_cast.split(","):
        col, type_name = cast.strip().split("=")
        if type_name not in TYPE_MAP:
            print(
                f"Cast type {type_name} for column {col} not in supported types."
                "Type will not be applied"
            )
            continue
        cast_map[col] = TYPE_MAP[type_name]
    return cast_map


def warn_missing_casts(columns: list[str] | None, type_cast: dict) -> None:
    """Log a warning when a ``TYPE_CAST`` column is not in the header."""
    if not columns:
        return
    for column_name in type_cast:
        if column_name not in columns:
            print(
                f"WARNING: Cast column {column_name} not found."
                "Cast will not be applied"
            )


def is_int(value: str) -> bool:
    try:
        int(value)
        return True
    except Exception:
        return False


def is_float(value: str) -> bool:
    try:
        float(value)
        return True
    except Exception:
        return False
