# User Attribute CSV to Braze Ingestion

### [Deploy Application](https://console.aws.amazon.com/lambda/home?region=us-east-1#/create/app?applicationId=arn:aws:serverlessrepo:us-east-1:585170621372:applications/braze-user-attribute-import)

This serverless application allows you to easily deploy a Lambda process that will post user attribute data from a CSV file directly to Braze using Braze Rest API endpoint [User Track](https://www.braze.com/docs/api/endpoints/user_data/post_user_track/). The process launches immediately when you upload a CSV file to the configured AWS S3 bucket.  
It can handle large files and uploads. However, it is important to keep in mind that due to Lambda's time limits, the function will stop execution after 10 minutes. The process will launch another Lambda instance to finish processing the remaining of the file. For more details about function timing, checkout [Execution Times](#execution-times).

## Features

- Ingest user attribute CSV file to Braze
- Ingest custom events when the file name contains `_events_` or ends with `_events`
- Ingest purchases when the file name contains `_purchases` or ends with `_purchases`
- Unset attributes with special `null` value
- Skip attribute update by omitting a value for the given user
- Force a particular data type for a given attribute (most useful for phone numbers and zip codes)

### CSV User Attributes

User attributes to be updated are expected in the following `.csv` format:

    external_id,attr_1,...,attr_n
    userID,value_1,...,value_n

Each row needs one identifier. `external_id` is used when that cell has a value. Otherwise use `user_alias` or `braze_id`. Otherwise `email` or `phone` must be present. A file with none of those columns fails. More than one of `external_id`, `user_alias`, and `braze_id` on the same row is skipped, because Braze rejects that object. When a primary identifier is present, `email` and `phone` are profile attributes on that user. With no primary identifier, Braze looks the user up by `email` when both `email` and `phone` are set. See [identifier resolution](https://www.braze.com/docs/api/endpoints/user_data/post_user_track#identifier-resolution).

`user_alias` is a dict cell with `alias_name` and `alias_label`:

    "{'alias_name': 'device123', 'alias_label': 'my_device_identifier'}"

Examples that cover each identifier are `tests/fixtures/sample_identifier_users.csv`, `tests/fixtures/sample_identifier_events.csv`, and `tests/fixtures/sample_identifier_purchases.csv`.

CSV file example:

    external_id,loyalty_point,last_brand_purchased
    abc123,1982,Solomon
    def456,578,Hunter-Hayes

### CSV Events

A file is imported as [events](https://www.braze.com/docs/api/objects_filters/event_object) when its name contains `_events_` or ends with `_events`. The `.csv` suffix does not count, so `sample_events.csv` and `batch_events_2026.csv` are both event files. See `tests/fixtures/sample_events.csv`.

Required columns are an identifier (`external_id`, `user_alias`, `braze_id`, `email`, or `phone`), `event_name`, and `time`. `event_name` is sent as the Braze event field `name`. `time` must be an ISO 8601 datetime. Identifier columns stay on the event. Every other column is nested under `properties`. A row missing a required value is skipped.

    external_id,event_name,time,movie,director
    user1,watched_trailer,2013-07-16T19:20:30+01:00,,
    user1,rented_movie,2013-07-16T19:20:45+01:00,The Sad Egg,Alex Smith

That becomes:

```json
{"events": [
  {
    "external_id": "user1",
    "name": "watched_trailer",
    "time": "2013-07-16T19:20:30+01:00"
  },
  {
    "external_id": "user1",
    "name": "rented_movie",
    "time": "2013-07-16T19:20:45+01:00",
    "properties": {"movie": "The Sad Egg", "director": "Alex Smith"}
  }
]}
```

`time` and `event_name` cannot be custom event properties. They stay on the event object.

### CSV Purchases

A file is imported as [purchases](https://www.braze.com/docs/api/objects_filters/purchase_object) when its name contains `_purchases` or ends with `_purchases`. `sample_purchases.csv` and `batch_purchases_2026.csv` both match. See `tests/fixtures/sample_purchases.csv`.

Required columns are an identifier (`external_id`, `user_alias`, `braze_id`, `email`, or `phone`), `event_name`, `time`, and `product_id`. Identifier columns stay on the purchase object, along with `quantity`, `price`, and `currency` when those columns have a value: `time`, `product_id`, `quantity`, `event_name`, `price`, `currency`. Every other column is nested under `properties`. Braze requires `price` and `currency` as well, and it rejects a `properties` object that repeats any of those reserved names.

    external_id,event_name,time,product_id,currency,price,quantity,color
    user1,purchased,2013-07-16T19:20:30+01:00,backpack,USD,40.00,1,red

That becomes:

```json
{"purchases": [
  {
    "external_id": "user1",
    "event_name": "purchased",
    "time": "2013-07-16T19:20:30+01:00",
    "product_id": "backpack",
    "quantity": 1,
    "price": 40.0,
    "currency": "USD",
    "properties": {"color": "red"}
  }
]}
```

A name that matches both events and purchases, such as `report_events_purchases.csv`, is rejected. Any other CSV is imported as user attributes. Each request still holds at most 75 objects.

### CSV File Processing

Value types will be automatically inferred. For example, numerical attributes will be send as either integers or floats. Boolean values such as `True`, `false`, `FALSE` will be send as a boolean `true` or `false`. If you would like to force a certain type at the import time, you can do so by setting the [TYPE_CAST variable](#type-cast).

#### Empty Values

Any empty values will be ignored. That will help you save on data points when updating custom attributes.

#### Array Attributes

Any values in an array will be automatically destructured and sent to the API in an array. For example, value `"['Value1', 'Value2']"` will be sent to Braze as array attribute `['Value1', 'Value2']`.

#### Unsetting Attributes

To unset, or remove, an attribute, you can use a special string value `null`. For example, the following row will remove the `CustomAttribute` from `user123`:

```
external_id,custom_attribute
user123,null
```

<a name="type-cast"></a>

#### Forcing a Data Type

If you want to avoid automatic attribute data type setting, you can force a particular data type onto an attribute. For example, you can force `0` and `1` values to be boolean values. You can force a numerical attribute to be represented as strings. Or you can force a decimal number (float) to be a whole number (integer).

Supported data types include:

- string
- integer
- float
- boolean

Cast variable format:

    column_name=data_type,another_column_name=data_type

For example:

    zip_code=string,one_or_zero=boolean

In order to set the type cast, in the Lambda function, navigate to the **Configuration** tab and select _Environment variables_. Add a new variable by clicking _Edit_:

- Key: `TYPE_CAST`
- Value: Data cast string in the format specified above

## Requirements

To successfully run this Lambda function, you will need:

- **AWS Account** in order to use the S3 and Lambda services
- **Braze API URL** to connect to Braze servers
- **Braze API Key** to be able to send requests to `/users/track` endpoint
- **CSV File** with user external IDs and attributes to update

### Where to find your Braze API URL and Braze API Key?

#### REST Endpoint

You can find your API URL, or the REST endpoint, in Braze documentation -- https://www.braze.com/docs/user_guide/administrative/access_braze/braze_instances/#braze-instances. Simply match your dashboard URL to the REST endpoint URL.  
For example, if your dashboard shows `dashboard-01.braze.com/` URL, your REST endpoint would be `https://rest.iad-01.braze.com`.

You can also find your REST API URL in the dashboard. In then the left navigation panel, scroll down and select **Manage App Group**.

There, you can find your `SDK Endpoint`. Replace `sdk` with `rest` to get your REST Endpoint. For example, if you see `sdk.iad-01.braze.com`, your API URL would be `https://rest.iad-01.braze.com`

#### API Key

To connect with Braze servers, we also need an API key. This unique identifier allows Braze to verify your identity and upload your data. To get your API key, open the Dashboard and scroll down the left navigation section. Select **Developer Console** under _App Settings_.

You will need an API key that has a permission to post to `user.track` API endpoint. If you know one of your API keys supports that endpoint, you can use that key. To create a new one, click on `Create New API Key` on the right side of your screen.

Next, name your API Key and select `users.track` under the _User Data_ endpoints group. Scroll down and click on **Save API Key**.
We will need this key shortly.

## Instructions

#### Steps Overview

1. Deploy Braze's publicly available CSV processing Lambda from the AWS Serverless Application Repository
2. Drop a CSV file with user attributes in the newly created S3 bucket
3. The users will be automatically imported to Braze

### Deploy

To start processing your User Attribute CSV files, we need to deploy the Serverless Application that will handle the processing for you. This application will create the following resources automatically in order to successfully deploy:

- Lambda function
- S3 Bucket for your CSV Files that the Lambda process can read from (_Note: this Lambda function will only receive notifications for `.csv` extension files_)
- Role allowing for creation of the above
- Policy to allow Lambda to receive S3 upload event in the new bucket

Follow the direct link to the [Application](https://console.aws.amazon.com/lambda/home?region=us-east-1#/create/app?applicationId=arn:aws:serverlessrepo:us-east-1:585170621372:applications/braze-user-attribute-import) or open the [AWS Serverless Application Repository](https://serverlessrepo.aws.amazon.com/applications) and search for _braze-user-attribute-import_. Note that you must check the `Show apps that create custom IAM roles and resource policies` checkbox in order to see this application. The application creates a policy for the lambda to read from the newly created S3 bucket.

Click **Deploy** and let AWS create all the necessary resources.

You can watch the deployment and verify that the stack (ie. all the required resources) is being created in the [CloudFormation](https://console.aws.amazon.com/cloudformation/). Find the stack named _serverlessrepo-braze-user-attribute-import_. Once the **Status** turns to `CREATE_COMPLETE`, the function is ready to use. You can click on the stack and open **Resources** and watch the different resources being created.

The following resources were created:

- [S3 Bucket](https://s3.console.aws.amazon.com/s3/) - a bucket named `braze-user-csv-import-aaa123` where `aaa123` is a randomly generated string
- [Lambda Function](https://console.aws.amazon.com/lambda/) - a lambda function named `braze-user-attribute-import`
- [IAM Role](https://console.aws.amazon.com/iam/) - policy named `braze-user-csv-import-BrazeUserCSVImportRole` to allow lambda to read from S3 and to log function output

### Run

To run the function, drop a user attribute CSV file in the newly created S3 bucket.

<a name="monitoring"></a>

### Monitoring and Logging

#### CloudWatch

To make sure the function ran successfully, you can read the function's execution logs. Open the Braze User CSV Import function (by selecting it from the list of Lambdas in the console) and navigate to **Monitor**. Here, you can see the execution history of the function. To read the output, click on **View logs in CloudWatch**. Select lambda execution event you want to check.

#### SNS

Optionally, you can publish a message to AWS SNS when the file is finished processing or it encounters a fatal error.

SNS message format:

    {
        // object key of the processed file
        "fileName": "abc.csv",
        // true if file was processed with no fatal error
        "success": true,
        "usersProcessed": 123
    }

In order to use this feature, you must:

- [Update](#updating) the lambda function to version `0.2.2` or higher
- Allow Lambda to publish messages to the topic
- Set the `TOPIC_ARN` environment variable

To allow lambda to publish to the topic, head over to `Configuration -> Permissions` and under **Execution Role**, click on the Role name. Next, click `Add permissions -> Create inline policy`.

- Service: SNS
- Actions: Publish
- Resources: Under topic, Add ARN and specify the topic ARN

Review policy, add name `BrazeUserImportSNSPublish` and Create Policy.

Finally, set the lambda environment variable with key: **`TOPIC_ARN`** and provide the SNS topic ARN where you would like to publish the message as the value.

#### Lambda Configuration

By default, the function is created with 2048MB memory size. Lambda's CPU is proportional to the memory size. Even though, the script uses constant, low amount of memory, the stronger CPU power allows to process the file faster and send more requests simultaneously.  
2GB was chosen as the best cost to performance ratio.  
You can review Lambda pricing here: https://aws.amazon.com/lambda/pricing/.

You can reduce or increase the amount of available memory for the function in the Lambda **Configuration** tab. Under _General configuration_, click **Edit**, specify the amount of desired memory and save.

Keep in mind that any more memory above 2GB has diminishing returns where it might improve processing speed by 10-20% but at the same time doubling or tripling the cost.

<a name="updating"></a>

#### Updating an Existing Function

If you have already deployed the application and a new version is available in the repository, you can update by re-deploying the function as if you were doing it for the first time. That means you have to pass it the Braze API Key and Braze API URL again. The update will only overwrite the function code. It will not modify or delete other existing resources like the S3 bucket.

You can also upload the packaged `.zip` file that's available under [Releases](https://github.com/braze-inc/growth-shares-lambda-user-csv-import/releases). In the AWS Console, navigate to the `braze-user-csv-import` Lambda function and in the **Code** tab, click on **Upload from** and then **.zip file**. Select the downladed `.zip` file.

<a name="execution-times"></a>

## Estimated Execution Times

_2048MB Lambda Function_

| # of rows | Exec. Time |
| --------- | ---------- |
| 10k       | 3s         |
| 100k      | 30s        |
| 1M        | 5 min      |
| 5M        | 30 min     |

<br>

## Fatal Error

In case of an unexpected error that prevents further processing of the file, an event is logged (accessible through CloudWatch described in [Monitoring and Logging](#monitoring)) that can be used to restart the Lambda from the point where the program stopped processing the file. It is important not to re-import the same data to save Data Points. You can find the instructions how to do that below.

## Manual Triggers

In case you wanted to trigger the Lambda manually, for testing or due to processing error, you can do it from the AWS Lambda Console using a test event.  
Open the Braze User Import Lambda in the the AWS console by opening Lambda service and selecting `braze-user-csv-import` function. Navigate to **Test**.

#### Event

If you have an event from a returned exception, paste it in the **Test event**. Otherwise, copy the contents of [`sample-event.json`](/events/sample-event.json). Replace the following values:

1. `"awsRegion"` under `"Records"`, replace `"your-region" with the proper region of the bucket with the file
2. `"name"` and `"arn"` under `"bucket"`, replace **only** `lambda-bucket-name` with the bucket name that CSV files are read from (the bucket that triggers this Lambda)
3. `"key"` under `"object"` with the CSV file key

_Optional_:

- `"offset"` field specifies the byte offset to start reading the file from
- `"headers"` field specifies CSV headers and it is mandatory if the file is not being read from the beginning

#### Invoke

To invoke the function, press `Invoke` and wait for the execution to finish.

## Manual Function Deploy

<a name="role"></a>

### Role

The Lambda function requires permissions to read objects from S3, log to CloudWatch and call other Lambda functions. You can create a new role or add the policies to an existing roles.
Required policies:

    AmazonS3ReadOnlyAccess
    AWSLambdaBasicExecutionRole
    AWSLambdaRole

To create a new role with these permissions open [Roles](https://console.aws.amazon.com/iam/home?region=us-east-1#/roles) console.

1. Click **Create role**
2. Select **Lambda** as a use case, and click on **Next: Permissions**
3. Search and mark all policies mentioned above
4. Click **Next:Tags** and **Next:Review**, name your role and finally create it by pressing **Create role**

### Create Function

1. Download the packaged code from [Releases](https://github.com/braze-inc/growth-shares-lambda-user-csv-import/releases)
2. Create a new [Lambda](https://console.aws.amazon.com/lambda/home?region=us-east-1#/discover) function.

   1. Select _Author from scratch_
   2. Name your function
   3. Select **Python 3.14** runtime
   4. Under **Change default execution role**, select _Use an existing role_ and select a role with all three policies described [above](#role)
   5. Create the function

3. Upload the packaged code downloaded from the repository by clicking on **Upload from** and selecting `.zip file`
4. Configure Lambda
   1. In the **Code** tab, scroll down to edit _Runtime settings_, changing Handler to `app.lambda_handler`
   2. In the **Configuration** tab, edit _General configuration_, setting timeout to `15` min and `0` sec, and changing Memory size to `2048` MB
   3. Also in **Configuration**, under _Environment variables_ add two key-value pairs: `BRAZE_API_URL` key with your API URL as value, and `BRAZE_API_KEY` with your API Key as value
   4. Under _Asynchronous invocation_, change `Retry attempts` to `0`.
5. Add an S3 trigger where you can drop the user attribute CSV files by clicking on `+ Add trigger` under the Function overview, selecting **S3** as a trigger and the source bucket, optionally using a bucket prefix. Then Add the trigger.

# Contributing and Testing

Use Python 3.14. Run the commands below from the repository root.

### Virtual environment

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install -r braze_user_csv_import/requirements.txt
    python -m pip install pytest pytest-mock pytest-env

If `python3` is not 3.14, create the environment with `python3.14 -m venv .venv` instead. `.venv` is gitignored. Activate it again in any new shell before the commands in this section.

### Run the test suite

`pytest.ini` sets stand-in `BRAZE_API_URL` and `BRAZE_API_KEY` values, so the suite does not call Braze or AWS.

    pytest

To run one area:

    pytest tests/test_csv_processor.py
    pytest tests/test_events_purchases.py
    pytest tests/test_identifiers.py
    pytest tests/test_braze_client.py
    pytest tests/test_s3_handler.py
    pytest tests/test_app.py

### Test each step

The import is split so each step can be run without deploying Lambda. `tests/fixtures/sample_users.csv` is a local stand-in for an uploaded file. It uses the CSV format above, including integers, floats, booleans, a leading-zero zip code, list cells, `null`, an empty cell, and a row that only has `external_id` (that row is skipped).

#### Attribute values

This does not read a file and does not call Braze.

    python - <<'PY'
    from braze_user_csv_import.braze_attributes import process_row, process_type_cast, process_value

    print(process_value("1982"))
    print(process_value("12.50"))
    print(process_value("true"))
    print(process_value("null"))
    print(process_value("02134"))
    print(process_value("['red', 'blue']"))
    print(process_row({"external_id": "abc123", "loyalty_point": "1982", "notes": ""}, {}))
    print(process_value("1", process_type_cast("active_flag=boolean")["active_flag"]))
    PY

#### CSV processor

Print the `/users/track` JSON for the sample file. Nothing is sent to Braze.

    python -m braze_user_csv_import csv tests/fixtures/sample_users.csv
    python -m braze_user_csv_import csv tests/fixtures/sample_users.csv --type-cast active_flag=boolean
    python -m braze_user_csv_import csv tests/fixtures/sample_events.csv
    python -m braze_user_csv_import csv tests/fixtures/sample_purchases.csv
    python -m braze_user_csv_import csv tests/fixtures/sample_identifier_users.csv
    python -m braze_user_csv_import csv tests/fixtures/sample_identifier_events.csv
    python -m braze_user_csv_import csv tests/fixtures/sample_identifier_purchases.csv

Nothing is sent to Braze. The events command prints an `events` array, with `event_name` mapped to `name` and other columns under `properties`. The purchases command prints a `purchases` array. The identifier files print one object for each of `external_id`, `user_alias`, `braze_id`, `email`, and `phone`. Rows with no identifier, or with more than one of `external_id`, `user_alias`, and `braze_id`, are left out of the JSON and logged. The same entry point is `python -m braze_user_csv_import.csv_processor`. `--batch-size` defaults to 75 and cannot be higher.

From Python:

    python - <<'PY'
    from braze_user_csv_import import CsvProcessor

    processor = CsvProcessor.from_file("tests/fixtures/sample_users.csv")
    for row in processor.collect_attributes():
        print(row["external_id"], row.get("loyalty_point"), row.get("custom_attribute"))
    PY

#### Braze `/users/track`

Set the REST endpoint and an API key that has the `users.track` permission. These are the same values the Lambda uses.

    export BRAZE_API_URL=https://rest.iad-01.braze.com
    export BRAZE_API_KEY=your-rest-api-key

Post the sample file through the CSV processor:

    python -m braze_user_csv_import csv tests/fixtures/sample_users.csv --post

Or post one payload on its own. The file must be either `{"attributes": [...]}` or a bare array of attribute objects, with at most 75 objects:

    python -m braze_user_csv_import braze payload.json

From Python:

    python - <<'PY'
    from braze_user_csv_import import BrazeClient

    accepted = BrazeClient().track_attributes([
        {"external_id": "abc123", "loyalty_point": 1982, "last_brand_purchased": "Solomon"}
    ])
    print(accepted)
    PY

`tests/test_braze_client.py` covers this call with a mocked response, so it does not need a real key.

#### S3

Read a CSV that is already in S3 and print the same payloads. This uses your AWS credentials and does not call Braze.

    python -m braze_user_csv_import s3 your-bucket path/to/users.csv

Add `--post` to send those users to Braze. `--offset` starts at a byte offset, which is how a follow-up Lambda resumes a large file.

To check only the event parsing, without AWS:

    python - <<'PY'
    from braze_user_csv_import import S3Handler

    event = {
        "Records": [
            {"s3": {"bucket": {"name": "your-bucket"}, "object": {"key": "path/to/users.csv"}}}
        ]
    }
    print(S3Handler.parse_upload_event(event))
    PY

#### Lambda handler

`tests/test_app.py` calls `lambda_handler` with a fake S3 event and checks success, fatal errors, SNS, and the follow-up invoke. To invoke the deployed function with a real file, use a test event from [Manual Triggers](#manual-triggers). The handler name stays `app.lambda_handler`.

### GitHub release

Publish a release from the repository root. The asset name matches previous releases, for example `braze-lambda-user-csv-import-v0.3.0.zip`.

1. Set `SemanticVersion` in `template.yaml` to the release version and commit that change. `package.sh` reads this value for the zip name. For `0.3.0`, the file is `build/braze-lambda-user-csv-import-v0.3.0.zip`.
2. Build the zip in the Lambda Python image. That image does not include the `zip` command, so install it first. A zip built on macOS can include a macOS `charset-normalizer` wheel that fails in Lambda. The zip includes `requests` and `tenacity`. It does not include `boto3` or `botocore`, because the Lambda Python runtime already provides them.

    docker run --rm -v "$PWD":/var/task -w /var/task --entrypoint bash \
      public.ecr.aws/lambda/python:3.14 \
      -lc 'dnf install -y zip && ./package.sh'

3. Open [Releases](https://github.com/braze-inc/growth-shares-lambda-user-csv-import/releases) and choose **Draft a new release**.
4. Choose a tag of `v` plus the version in `template.yaml`, for example `v0.3.0`. Create the tag on the commit that contains that `SemanticVersion`.
5. Set the release title to the same tag, for example `v0.3.0`, and write the release notes.
6. Under the release notes, attach `build/braze-lambda-user-csv-import-v0.3.0.zip`. Leave the zip name unchanged so it matches earlier release assets.
7. Choose **Publish release**.

Contributions are welcome.
