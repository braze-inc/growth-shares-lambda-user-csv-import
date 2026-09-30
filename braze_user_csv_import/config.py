"""Environment configuration. Values are read when a call needs them."""

import os


def get_braze_api_url() -> str:
    """Return the Braze REST endpoint, without a trailing slash.

    Example: ``https://rest.iad-01.braze.com``.
    """
    try:
        url = os.environ["BRAZE_API_URL"]
    except KeyError as exc:
        raise RuntimeError(
            "BRAZE_API_URL is not set. Use the REST endpoint for your Braze "
            "instance, for example https://rest.iad-01.braze.com."
        ) from exc
    if url.endswith("/"):
        url = url[:-1]
    return url


def get_braze_api_key() -> str:
    """Return the REST API key. It needs the ``users.track`` permission."""
    try:
        return os.environ["BRAZE_API_KEY"]
    except KeyError as exc:
        raise RuntimeError(
            "BRAZE_API_KEY is not set. Create a key with the users.track permission."
        ) from exc


def get_topic_arn() -> str | None:
    """Return the SNS topic ARN, or None when publishing is disabled."""
    topic_arn = os.environ.get("TOPIC_ARN")
    if not topic_arn:
        return None
    return topic_arn


def get_type_cast_setting() -> str | None:
    """Return the raw ``TYPE_CAST`` environment value."""
    return os.environ.get("TYPE_CAST")
