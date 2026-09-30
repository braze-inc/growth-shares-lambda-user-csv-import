"""POST user attributes to Braze ``/users/track``.

https://www.braze.com/docs/api/endpoints/user_data/post_user_track

Each request body is ``{"attributes": [...]}`` with at most 75 objects.
Authentication is ``Authorization: Bearer <BRAZE_API_KEY>``.

Example::

    from braze_user_csv_import import BrazeClient

    client = BrazeClient()
    client.track_attributes([
        {"external_id": "abc123", "loyalty_point": 1982}
    ])

Or post a JSON file::

    python -m braze_user_csv_import braze payload.json
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from requests.exceptions import RequestException
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

if __package__:
    from .config import get_braze_api_key, get_braze_api_url
    from .constants import BRAZE_BATCH_SIZE, MAX_RETRIES, MAX_THREADS
    from .errors import APIRetryError, FatalAPIError
else:
    from config import get_braze_api_key, get_braze_api_url
    from constants import BRAZE_BATCH_SIZE, MAX_RETRIES, MAX_THREADS
    from errors import APIRetryError, FatalAPIError


def _on_network_retry_error(state: RetryCallState) -> None:
    print(
        f"INFO: Retry attempt: {state.attempt_number}/{MAX_RETRIES}. "
        f"Wait time: {state.idle_for}"
    )


def _normalize_url(api_url: str) -> str:
    if api_url.endswith("/"):
        return api_url[:-1]
    return api_url


@retry(
    retry=retry_if_exception_type(RequestException),
    wait=wait_exponential(multiplier=5, min=5),
    stop=stop_after_attempt(MAX_RETRIES),
    after=_on_network_retry_error,
    reraise=True,
)
def post_to_braze(
    users: list[dict],
    api_url: str | None = None,
    api_key: str | None = None,
) -> int:
    """POST one attributes batch. Returns how many users were accepted.

    Retries network errors, HTTP 429, and HTTP 5xx up to ``MAX_RETRIES``.
    A fatal client error is not retried.
    """
    api_url = _normalize_url(api_url or get_braze_api_url())
    api_key = api_key if api_key is not None else get_braze_api_key()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "X-Braze-Bulk": "true",
    }
    data = json.dumps({"attributes": users})
    response = requests.post(
        f"{api_url}/users/track",
        headers=headers,
        data=data,
    )
    error_users = handle_braze_response(response)
    return len(users) - error_users


def handle_braze_response(response: requests.Response) -> int:
    """Interpret one ``/users/track`` response.

    :return: Number of users reported in a non-fatal ``errors`` array.
        ``0`` means the whole batch counts as accepted, including HTTP 400,
        which is logged and does not fail the file.
    :raises APIRetryError: on HTTP 429 or 5xx
    :raises FatalAPIError: on any other HTTP status above 400
    """
    res_text = json.loads(response.text)
    if response.status_code == 201 and "errors" in res_text:
        print(f"Encountered errors processing some users: {res_text['errors']}")
        return len(res_text["errors"])

    if response.status_code == 400:
        print(f"Encountered error for user chunk. {response.text}")
        return 0

    server_error = response.status_code == 429 or response.status_code >= 500
    if server_error:
        raise APIRetryError("Server error. Retrying..")

    if response.status_code > 400:
        raise FatalAPIError(res_text.get("message", response.text))

    return 0


def post_user_chunks(
    user_chunks: list[list[dict]],
    api_url: str | None = None,
    api_key: str | None = None,
) -> int:
    """POST batches concurrently. Each batch should hold at most 75 users."""
    updated = 0
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        results = executor.map(
            lambda users: post_to_braze(users, api_url=api_url, api_key=api_key),
            user_chunks,
        )
        for result in results:
            updated += result
    return updated


class BrazeClient:
    """Reusable ``/users/track`` client.

    ``api_url`` and ``api_key`` fall back to ``BRAZE_API_URL`` and
    ``BRAZE_API_KEY`` when omitted.
    """

    def __init__(self, api_url: str | None = None, api_key: str | None = None):
        self.api_url = _normalize_url(api_url or get_braze_api_url())
        self.api_key = api_key if api_key is not None else get_braze_api_key()

    def track_attributes(self, users: list[dict]) -> int:
        """POST one attributes list. Keep it to 75 objects."""
        return post_to_braze(users, api_url=self.api_url, api_key=self.api_key)

    def track_attribute_chunks(self, user_chunks: list[list[dict]]) -> int:
        """POST many batches with up to ``MAX_THREADS`` requests at once."""
        return post_user_chunks(
            user_chunks,
            api_url=self.api_url,
            api_key=self.api_key,
        )


def _load_attribute_users(payload_path: str) -> list[dict]:
    body = json.loads(Path(payload_path).read_text())
    if isinstance(body, dict) and isinstance(body.get("attributes"), list):
        return body["attributes"]
    if isinstance(body, list):
        return body
    raise SystemExit(
        "Payload must be an attributes array or a {\"attributes\": [...]} object."
    )


def main(argv: list[str] | None = None) -> int:
    """POST a JSON payload file to ``/users/track``."""
    parser = argparse.ArgumentParser(
        description="POST user attributes to Braze /users/track."
    )
    parser.add_argument(
        "payload",
        help='JSON file: {"attributes": [...]} or a bare array of attribute objects',
    )
    parser.add_argument("--api-url", help="Overrides BRAZE_API_URL")
    parser.add_argument("--api-key", help="Overrides BRAZE_API_KEY")
    args = parser.parse_args(argv)

    users = _load_attribute_users(args.payload)
    client = BrazeClient(api_url=args.api_url, api_key=args.api_key)
    updated = 0
    for start in range(0, len(users), BRAZE_BATCH_SIZE):
        updated += client.track_attributes(users[start:start + BRAZE_BATCH_SIZE])
    print(json.dumps({"users_processed": updated}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
