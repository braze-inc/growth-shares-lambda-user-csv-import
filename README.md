# User Attribute CSV to Braze Ingestion

This serverless application allows you to easily deploy a Lambda process that will post user attribute data from a CSV file directly to Braze using Braze Rest API endpoint [User Track](https://www.braze.com/docs/api/endpoints/user_data/post_user_track/). The process launches immediately when you upload a CSV file to the AWS S3 bucket.  
It can handle large files and uploads. However, it is important to keep in mind that due to Lambda's time limits, the function will stop execution after 12 minutes. The process will launch another Lambda instance to finish processing the remaining of the file. For more details about function timing, checkout [Execution Times](#execution-times).

### CSV User Attributes

User attributes to be updated are expected in the following `.csv` format:

    external_id,attr_1,...,attr_n
    userID,value_1,...,value_n

where the first column must specify the external ID of the user to be updated and the following columns specify attribute names and values. The amount of attributes you specify can vary. If the `CSV` file to be processed does not follow this format, the function will fail.

### CSV Processing

Any values in an array (ex. `"['Value1', 'Value2']"` will be automatically destructured and sent to the API in an array rather than a string of representation of an array.

## Requirements

To successfully run this Lambda function, you will need:

- **AWS Account** in order to use the S3 and Lambda services
- **Braze API URL** to connect to Braze servers
- **Braze API Key** to be able to send requests to `/users/track` endpoint
- **CSV File** with user external IDs and attributes to update

### Where to find your Braze API URL and key?

#### REST Endpoint

You can find your API URL, or the REST endpoint, in Braze documentation -- https://www.braze.com/docs/user_guide/administrative/access_braze/braze_instances/#braze-instances. Simply match your dashboard URL to the REST endpoint URL.  
For example, if your dashboard shows `dashboard-01.braze.com/` URL, your REST endpoint would be `https://rest.iad-01.braze.com`.

You can also find your REST API URL in the dashboard. Head over to your dashboard and in then the left panel, under _App Settings_, open _Manage App Group_.

[img] _TODO: update after publishing to public repo_

There you can find an `SDK Endpoint`. Replace `sdk` with `rest` to get your REST Endpoint. For example, if you see `sdk.iad-01.braze.com`, your API URL would then be `rest.iad-01.braze.com`

#### API Key

To connect with Braze servers, we also need an API key. This unique identifier allows Braze to verify your identity and upload your data. To get your API key, open the Dashboard and select _Developer Concole_ under _App Settings_.

[img] _TODO: update after publishing to public repo_

You will need an API key that has a permission to post to `user.track` API endpoint. If you know one of your API keys supports that endpoint, you can use that key. To create a new one, click on `Create New API Key` on the right side of your screen.

[img] _TODO: update after publishing to public repo_

Next, name your API Key and select `users.track` under the _User Data_ endpoints group. Scroll down and click on `Save API Key`.
We will need this key shortly.

## Instructions

### Steps Overview

1. Deploy Braze's publicly available CSV processing Lambda from the AWS Serverless Application Repository (SAM)
2. Drop a CSV file with user attributes in the newly created S3 bucket 
3. The users will be automatically imported to Braze

#### Deploy

To start processing your User Attribute CSV files, we just have to deploy the Serverless Application that will handle the processing for you. This application will create the following resources automatically in order to successfully deploy:

- Lambda function
- S3 Bucket for your CSV Files that the Lambda process can read from (_Note: this Lambda function will only receive notifications for `.csv` files_)
- Role allowing for creation of the above
- Policy to allow Lambda to receive S3 upload event in the new bucket

Open the [AWS Serverless Application Repository](https://serverlessrepo.aws.amazon.com/applications). Note that you must check the `Show apps that create custom IAM roles and resource policies` checkbox in order to see this application. The application creates custom policy for the lambda to read from the newly created S3 bucket.

Search for _TODO: Insert title of the application_.

<a name="execution-time"></a>

#### Run

..

#### Monitor

..

## Estimated Execution Times

Describe execution times..

## Logging

Describe logging..

## Creating your own Lambda

The serverless application creates the whole stack of services that work together, S3 bucket, policies and finally the Lambda function. If you want to use an existing bucket, it is not possible with the serverless application. However, you could create and deploy your own Lambda process instead. The steps below will guide you how to accomplish that.

_TODO: Include .zip package in Releases_

1. Download the packaged code from [Releases](INSERT_LINK)
2. Create a new Lambda function
3. ...
