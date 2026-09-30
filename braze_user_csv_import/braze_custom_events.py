"""Shared /users/track shaping for custom events and purchases.

``braze_events`` and ``braze_purchase`` use these helpers. This module also
picks the payload from the file name and dispatches a row to the right shaper.
"""

import os

if __package__:
    from .braze_attributes import OBJECT_TYPE as ATTRIBUTES
    from .braze_attributes import shape_row as shape_attribute_row
    from .braze_attributes import verify_headers as verify_attribute_headers
    from .braze_attributes import warn_missing_casts
else:
    from braze_attributes import OBJECT_TYPE as ATTRIBUTES
    from braze_attributes import shape_row as shape_attribute_row
    from braze_attributes import verify_headers as verify_attribute_headers
    from braze_attributes import warn_missing_casts


def file_match_names(file_name: str) -> list[str]:
    """Return the lowercased file name, and the name without its extension."""
    base = os.path.basename(file_name.replace("\\", "/")).lower()
    stem, extension = os.path.splitext(base)
    if extension:
        return [base, stem]
    return [base]


def name_matches(file_name: str, infix: str, suffix: str) -> bool:
    """Return whether the file name contains ``infix`` or ends with ``suffix``."""
    return any(
        infix in name or name.endswith(suffix) for name in file_match_names(file_name)
    )


# https://www.braze.com/docs/api/endpoints/user_data/post_user_track#identifier-resolution
PRIMARY_IDENTIFIERS = ("external_id", "user_alias", "braze_id")
SECONDARY_IDENTIFIERS = ("email", "phone")
IDENTIFIER_FIELDS = PRIMARY_IDENTIFIERS + SECONDARY_IDENTIFIERS


def headers_include_identifier(columns: list[str] | None) -> bool:
    """Return whether the header has a column Braze can use to find a user."""
    if not columns:
        return False
    return any(name in columns for name in IDENTIFIER_FIELDS)


def require_identifier_column(columns: list[str] | None) -> None:
    """Fail the file when no identifier column is present.

    A file may mix ``external_id``, ``user_alias``, ``braze_id``, ``email``,
    and ``phone``. Each row is checked on its own.
    """
    if not columns or headers_include_identifier(columns):
        return
    raise ValueError(
        "ERROR: File headers don't match the expected format. "
        "Include one of external_id, user_alias, braze_id, email, or phone"
    )


def row_has_identifier(row: dict, label: str) -> bool:
    """Return whether ``row`` has one identifier Braze will accept.

    ``external_id`` is used when it is present. Otherwise ``user_alias`` or
    ``braze_id`` is used. Otherwise ``email`` or ``phone`` must be present.
    More than one of ``external_id``, ``user_alias``, and ``braze_id`` is
    rejected, matching Braze primary-identifier rules.
    """
    message = _identifier_error(row)
    if message is None:
        return True
    print(f"ERROR: {label} row {message}. Failing row: {row}")
    return False


def _identifier_error(row: dict) -> str | None:
    primaries = [name for name in PRIMARY_IDENTIFIERS if name in row]
    if len(primaries) > 1:
        return (
            "has multiple primary identifiers "
            f"({', '.join(primaries)}). Only one of external_id, user_alias, "
            "or braze_id is allowed"
        )
    if "user_alias" in row and not _valid_user_alias(row["user_alias"]):
        return "user_alias must be an object with alias_name and alias_label"
    if primaries or any(name in row for name in SECONDARY_IDENTIFIERS):
        return None
    return "missing external_id, user_alias, braze_id, email, or phone"


def _valid_user_alias(value) -> bool:
    if not isinstance(value, dict):
        return False
    return bool(value.get("alias_name")) and bool(value.get("alias_label"))


def row_has_required(row: dict, required: tuple[str, ...], label: str) -> bool:
    """Return False and log when a required column was empty or absent."""
    missing = [key for key in required if key not in row]
    if not missing:
        return True
    print(f"ERROR: {label} row missing {', '.join(missing)}. Failing row: {row}")
    return False


def properties_except(row: dict, top_level: tuple[str, ...]) -> dict:
    """Return columns that are not part of the track object itself."""
    return {key: value for key, value in row.items() if key not in top_level}


def verify_required_columns(
    columns: list[str] | None,
    required: tuple[str, ...],
    type_cast: dict,
) -> None:
    """Require ``required`` headers, then warn about unknown type casts."""
    if not columns:
        return
    missing = [name for name in required if name not in columns]
    if missing:
        raise ValueError(
            "ERROR: File headers don't match the expected format. "
            f"Missing required columns: {', '.join(missing)}"
        )
    warn_missing_casts(columns, type_cast)


def payload_kind(file_name: str) -> str:
    """Return ``attributes``, ``events``, or ``purchases`` for ``file_name``."""
    events = _events_module()
    purchases = _purchase_module()
    is_events = events.matches(file_name)
    is_purchases = purchases.matches(file_name)
    if is_events and is_purchases:
        raise ValueError(
            "File name matches both events and purchases. "
            "Use either _events or _purchases, not both."
        )
    if is_events:
        return events.OBJECT_TYPE
    if is_purchases:
        return purchases.OBJECT_TYPE
    return ATTRIBUTES


def verify_track_headers(columns: list[str] | None, type_cast: dict, kind: str) -> None:
    """Check the header row for the payload selected by the file name."""
    if kind == ATTRIBUTES:
        verify_attribute_headers(columns, type_cast)
        return
    if kind == _events_module().OBJECT_TYPE:
        _events_module().verify_headers(columns, type_cast)
        return
    _purchase_module().verify_headers(columns, type_cast)


def shape_track_row(row: dict, kind: str) -> dict | None:
    """Turn one parsed CSV row into a /users/track object.

    Returns None when the row should be skipped.
    """
    if kind == _events_module().OBJECT_TYPE:
        return _events_module().shape_row(row)
    if kind == _purchase_module().OBJECT_TYPE:
        return _purchase_module().shape_row(row)
    return shape_attribute_row(row)


def _events_module():
    if __package__:
        from . import braze_events
    else:
        import braze_events
    return braze_events


def _purchase_module():
    if __package__:
        from . import braze_purchase
    else:
        import braze_purchase
    return braze_purchase
