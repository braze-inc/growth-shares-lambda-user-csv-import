# AGENTS.md

This Lambda reads a user-attribute CSV from S3 and posts it to Braze
[`POST /users/track`](https://www.braze.com/docs/api/endpoints/user_data/post_user_track).
The deployed handler stays `app.lambda_handler`. The steps underneath are separate
modules so they can be imported or run without Lambda.

Operator setup, deploy, and CSV rules are in `README.md`. This file is the map
for changing the code.

## Layout

| Module | Call it for |
| --- | --- |
| `app.py` | Lambda entry. Re-exports `lambda_handler`. Do not move that name. |
| `handler.py` | S3 event, continuation invoke, SNS, fatal-error event |
| `csv_processor.py` | `CsvProcessor`. Local file or S3. Parsing does not call Braze. |
| `s3_handler.py` | `S3Handler`. Bucket/key from the S3 event, ranged object read |
| `braze_client.py` | `BrazeClient` and `post_to_braze`. One `/users/track` request |
| `braze_attributes.py` | Cell typing: `process_row`, `process_value`, `process_type_cast` |
| `braze_events.py` | Event rows: `event_name` becomes `name`, other columns go in `properties` |
| `braze_purchase.py` | Purchase rows: reserved fields stay on the object, other columns go in `properties` |
| `braze_custom_events.py` | Shared event/purchase helpers and file-name routing |
| `config.py` | `BRAZE_API_URL`, `BRAZE_API_KEY`, `TYPE_CAST`, `TOPIC_ARN` |
| `errors.py` | `APIRetryError` (retry), `FatalAPIError` (stop the file) |
| `constants.py` | Batch size, thread count, retry count, runtime hand-off |

```python
from braze_user_csv_import import CsvProcessor, BrazeClient, S3Handler, lambda_handler
from braze_user_csv_import.braze_attributes import process_row, process_value, process_type_cast
```

Inside the Lambda zip the same files sit at the root of the deployment package
(`CodeUri: braze_user_csv_import/`). Imports work both as
`braze_user_csv_import.csv_processor` and, in that zip, as flat modules.

## Run a step on its own

Install dependencies (Python 3.14):

```bash
python3 -m pip install -r braze_user_csv_import/requirements.txt
```

Sample file: `tests/fixtures/sample_users.csv`. It follows the README format.
The first two users are the README example (`abc123` / Solomon, `def456` /
Hunter-Hayes), plus types the importer infers:

- integers and floats (`1982`, `12.50`, `0`, `-4.23`)
- booleans (`true`, `false`, `TRUE`)
- leading-zero strings left as strings (`02134`) so zip codes are not truncated
- list cells (`"['red', 'blue']"`, `"[9.12, 1, 4]"`)
- `null`, which becomes JSON `null` and unsets `custom_attribute`
- an empty `phone` cell, which is omitted
- `0` / `1` in `active_flag` (integers unless `--type-cast active_flag=boolean`)
- `ghost_user`, which has only `external_id` and is skipped

Print `/users/track` bodies without calling Braze:

```bash
python -m braze_user_csv_import csv tests/fixtures/sample_users.csv
python -m braze_user_csv_import csv tests/fixtures/sample_users.csv --type-cast active_flag=boolean
python -m braze_user_csv_import.csv_processor tests/fixtures/sample_users.csv
```

Post that file (needs `BRAZE_API_URL` and `BRAZE_API_KEY`):

```bash
python -m braze_user_csv_import csv tests/fixtures/sample_users.csv --post
```

Post a payload you already built, or read a CSV from S3:

```bash
python -m braze_user_csv_import braze payload.json
python -m braze_user_csv_import s3 my-bucket uploads/users.csv
python -m braze_user_csv_import s3 my-bucket uploads/users.csv --post
```

`payload.json` is either `{"attributes": [...]}` or a bare array. `--batch-size`
cannot be higher than 75. `--post` on the S3 and CSV commands sends the file;
without it they only print payloads.

```python
processor = CsvProcessor.from_file("tests/fixtures/sample_users.csv")
payloads = processor.build_track_payloads()          # no network
rows = processor.collect_attributes()                # one dict per user

processor.process_file()                             # POST every batch
CsvProcessor.from_s3("bucket", "file.csv").collect_attributes()

BrazeClient().track_attributes(payloads[0]["attributes"])
S3Handler.parse_upload_event(event)                  # -> (bucket, key)
```

`braze_attributes.py` does not need AWS or Braze:

```python
process_value("02134")          # "02134"
process_value("null")           # None
process_value("['red', 'blue']")
process_type_cast("zip_code=string,active_flag=boolean")
```

## What the Lambda does

1. S3 `ObjectCreated` on a `.csv` key calls `lambda_handler`.
2. `CsvProcessor` streams the object in 10 MB chunks from `event["offset"]`
   (default 0). A continuation event also carries `headers`, because the
   header row is not read again.
3. Rows become attribute, event, or purchase objects (from the file name) and
   are posted in batches of 75, with up to 20 requests in flight (`MAX_THREADS`).
4. The function stops once less than 5 minutes remain of the 15 minute Lambda
   timeout (about 10 minutes of work). It then invokes itself asynchronously
   with the current byte `offset` and `headers`.
5. Each invocation publishes to SNS when `TOPIC_ARN` is set, including a
   hand-off that has not reached the end of the file. `usersProcessed` is the
   count for that invocation. A fatal error publishes `success: false`.

```json
{"fileName": "abc.csv", "success": true, "usersProcessed": 123}
```

A fatal error logs a full event you can paste into a Lambda test invocation to
resume. The manual event shape is `events/sample-event.json`.

Environment variables: `BRAZE_API_URL`, `BRAZE_API_KEY`, `TYPE_CAST`, `TOPIC_ARN`.
They are read when a call needs them, so importing `CsvProcessor` does not
require Braze credentials.

## CSV contract

Header and rows:

```text
external_id,attr_1,...,attr_n
userID,value_1,...,value_n
```

Each row needs one identifier. `external_id` is used when present. Otherwise
`user_alias` or `braze_id`. Otherwise `email` or `phone`. A header with none
of those columns fails the file. More than one of `external_id`, `user_alias`,
and `braze_id` skips that row. `user_alias` is a dict cell with `alias_name`
and `alias_label`. With a primary identifier, `email` and `phone` are profile
attributes. Sample files: `tests/fixtures/sample_identifier_users.csv`,
`tests/fixtures/sample_identifier_events.csv`,
`tests/fixtures/sample_identifier_purchases.csv`.
Empty cells are skipped so unchanged attributes are not sent. The cell
`null` is sent as JSON `null` and unsets that attribute.

Inferred types: integers, floats, `true`/`false`, `null`, and bracketed lists
parsed with `ast.literal_eval`. A leading zero (`02134`, `0123`) stays a
string. Phone numbers with dashes stay strings. Force a column with
`TYPE_CAST` or `--type-cast`:

```text
zip_code=string,active_flag=boolean
```

Supported cast names: `string`, `integer`, `float`, `boolean`. A cast other
than `string` is applied after inference (`"1"` with `boolean` becomes
`true`). A numeric zip code with no leading zero, such as `10001`, is inferred
as an integer unless you cast that column to `string`.

Rows that only contain `external_id` are not posted.

## Braze `POST /users/track`

Docs: https://www.braze.com/docs/api/endpoints/user_data/post_user_track

Use this endpoint to set attributes and record custom events and purchases.
The CSV file name selects the array:

- contains `_events_` or ends with `_events` (ignoring `.csv`): `events`. CSV column `event_name` is sent as `name`. Identifier columns stay on the event. Other columns go in `properties`. Required columns: an identifier, `event_name`, `time`.
- contains `_purchases` or ends with `_purchases`: `purchases`. Top-level fields are the identifier, `event_name`, `time`, `product_id`, and, when present, `quantity`, `price`, and `currency`. Other columns go in `properties`. Required columns: an identifier, `event_name`, `time`, `product_id`.
- any other name: `attributes`.

A name that matches both events and purchases is rejected. This importer does not send `group_id`. Sample files: `tests/fixtures/sample_users.csv`, `tests/fixtures/sample_events.csv`, `tests/fixtures/sample_purchases.csv`.

- **URL:** `{BRAZE_API_URL}/users/track`. Match the dashboard instance, for
  example dashboard `dashboard-01.braze.com` -> `https://rest.iad-01.braze.com`.
  One trailing slash on the env var is stripped.
- **Auth:** API key with the `users.track` permission.
  `Authorization: Bearer <key>`.
- **Headers this client sends:** `Content-Type: application/json`,
  `Authorization`, and `X-Braze-Bulk: true`.
- **Body:**

```json
{"attributes": [{"external_id": "abc123", "loyalty_point": 1982}]}
```

- **Batch size:** each request may contain at most **75 objects combined**
  across `attributes`, `events`, and `purchases`. Keep
  `constants.BRAZE_BATCH_SIZE` at 75. Do not raise it.
- **Identifier:** every object must include one of `external_id`,
  `user_alias`, `braze_id`, `email`, or `phone`. This CSV path uses
  `external_id` when that cell is set, otherwise `user_alias` or `braze_id`,
  otherwise `email` or `phone`. When a primary identifier is present, `email`
  and `phone` are profile attributes, not lookup keys. A new `external_id`
  plus an email that already exists can create a duplicate profile; Braze's
  `/users/identify` endpoint is the migration path, and this importer does
  not call it.
- **Only one primary identifier** per object. `external_id`, `user_alias`,
  and `braze_id` together get that object rejected.
- **Deltas:** Braze bills a data point per custom attribute in the request.
  Empty cells are omitted on purpose. Send changes, not a full profile copy.
- **Async:** HTTP success means the update was queued, not that the profile
  is updated yet. Processing order across separate requests is not guaranteed.
  Status polling via `group_id` and `/users/track/status` is not implemented.
- **Rate limit:** for data-point contracts, a burst limit of 3,000 requests
  per 3 seconds. Other contracts vary. HTTP 429 is retried.
- **Retries:** 429, 5xx, and `requests` errors retry up to 5 attempts with
  exponential backoff (`multiplier=5`, `min=5` seconds) in
  `braze_client.post_to_braze`. `FatalAPIError` is not retried.
- **Responses this client understands:**
  - 2xx: batch counts as accepted.
  - 201 with an `errors` array: those entries are subtracted from the
    accepted count and logged. Braze still applies the other objects.
  - 400: logged, and the batch still counts as accepted (0 errors returned).
    Do not change that without an explicit decision; it is existing behavior.
  - 429 or 5xx: `APIRetryError`, then the tenacity retry.
  - any other status above 400: `FatalAPIError`, the file stops, SNS gets
    `success: false`, and the continuation event is logged.
- **Endpoint errors** worth recognizing in logs include `EMAIL_BAD_FORMAT`,
  `EXTERNAL_USER_ID_TOO_LARGE` (external id max 987 bytes),
  `BLACKLISTED_EXTERNAL_USER_ID`, and the `BAD_SUBSCRIPTION_GROUP_*` /
  subscription-state errors. Invalid nested custom attributes can cause Braze
  to drop the whole nested update.

Server-to-server callers behind a firewall may need to allow the REST host
(`rest.iad-01.braze.com` for the US-01 instance).

## Tests

```bash
python3 -m pip install pytest pytest-mock pytest-env
pytest
```

`pytest.ini` sets a fake `BRAZE_API_URL` and `BRAZE_API_KEY` through
`pytest-env`. The sample-file tests do not call Braze.

## Runtime and packaging

- Lambda runtime in `template.yaml` is `python3.14`. Handler:
  `app.lambda_handler`. Timeout 15 minutes, 2048 MB, retry attempts 0.
- `braze_user_csv_import/requirements.txt` pins the Python 3.14 tree
  (`boto3`, `requests`, `tenacity`, and their dependencies).
- `package.sh` installs that file and zips every module next to the
  dependencies. Build the zip on Linux, or for the Lambda architecture, so
  binary wheels match Amazon Linux. `charset-normalizer` is the package most
  likely to break if the zip is built on macOS and deployed as-is.
- Lambda's Python 3.14 runtime already includes boto3. The packaged copy
  replaces it so the pin in `requirements.txt` is what runs.

## Change safely

- Keep identifier resolution: `external_id`, else `user_alias` or `braze_id`, else `email` or `phone`. Only one primary identifier per object.
- Leave the 75-object batch and the 20-thread wave unless Braze's limit changes.
- A continuation must keep both `offset` and `headers`. Resuming without
  headers re-reads the header row as a user.
- Do not import Braze at module import time. Local CSV parsing has to work
  with no API key.
- Do not log `BRAZE_API_KEY`.
