"""Errors raised while posting users to Braze."""

from requests.exceptions import RequestException


class APIRetryError(RequestException):
    """Raised on HTTP 429 or 5xx. The request is retried with exponential backoff."""


class FatalAPIError(Exception):
    """Raised on an unexpected client error. Import processing stops."""
