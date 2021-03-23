# User Attribute CSV to Braze Ingestion

This serverless application allows you to easily deploy a Lambda process that will post user attribute data from a CSV file directly to Braze using Braze Rest API endpoint [User Track](https://www.braze.com/docs/api/endpoints/user_data/post_user_track/). The process launches immediately when you upload a CSV file to the AWS S3 bucket.  
It can handle large files and uploads. However, it is important to keep in mind that due to Lambda's time limits, the function will stop execution after 12 minutes. The process will launch another Lambda instance to finish processing the remaining of the file. For more details about function timing, checkout [Execution Times](#execution-times).

### CSV User Attributes

User attributes to be updated are expected in the following `.csv` format:

    external_id,attr_1,...,attr_n
    userID,value_1,...,value_n

where the first column must specify the external ID of the user to be updated and the following columns specify attribute names and values. The amount of attributes you specify can vary. If the CSV file to be processed does not follow this format, the function will fail.

### CSV Processing

Any values in an array (ex. `"['Value1', 'Value2']"` will be automatically destructured and sent to the API in an array rather than a string representation of an array.

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

<img src="./img/manage-app-group.png" width="200">

 <!-- <img src="https://github.com/braze-inc/growth-shares-lambda-user-csv-import/blob/master/img/create-bucket.png"> -->

There you can find your `SDK Endpoint`. Replace `sdk` with `rest` to get your REST Endpoint. For example, if you see `sdk.iad-01.braze.com`, your API URL would be `rest.iad-01.braze.com`

#### API Key

To connect with Braze servers, we also need an API key. This unique identifier allows Braze to verify your identity and upload your data. To get your API key, open the Dashboard and scroll down the left navigation section. Select **Developer Console** under _App Settings_.

<img src="./img/developer-console.png" width="200">

You will need an API key that has a permission to post to `user.track` API endpoint. If you know one of your API keys supports that endpoint, you can use that key. To create a new one, click on `Create New API Key` on the right side of your screen.

<img src="./img/create-key.png" width="200">

Next, name your API Key and select `users.track` under the _User Data_ endpoints group. Scroll down and click on **Save API Key**.
We will need this key shortly.

## Instructions

#### Steps Overview

1. Deploy Braze's publicly available CSV processing Lambda from the AWS Serverless Application Repository (SAM)
2. Drop a CSV file with user attributes in the newly created S3 bucket
3. The users will be automatically imported to Braze

#### Deploy

To start processing your User Attribute CSV files, we need to deploy the Serverless Application that will handle the processing for you. This application will create the following resources automatically in order to successfully deploy:

- Lambda function
- S3 Bucket for your CSV Files that the Lambda process can read from (_Note: this Lambda function will only receive notifications for `.csv` extension files_)
- Role allowing for creation of the above
- Policy to allow Lambda to receive S3 upload event in the new bucket

Follow the direct link to the [Braze User CSV ](_TODO: Insert public link here_) or open the [AWS Serverless Application Repository](https://serverlessrepo.aws.amazon.com/applications) and search for _Braze User CSV Import_ (_TODO: Change to an official name_). Note that you must check the `Show apps that create custom IAM roles and resource policies` checkbox in order to see this application. The application creates a policy for the lambda to read from the newly created S3 bucket.

Click **Deploy** and let AWS create all the necessary resources.

You can watch the deployment and verify that the stack (ie. all the required resources) is being created in the [CloudFormation](https://console.aws.amazon.com/cloudformation/). Find the stack named (_TODO: Update with the application name_). Once the **Status** turns to `CREATE_COMPLETE`, the function is ready to use. You can click on the stack and open **Resources** and watch the different resources being created.

The following resources were created:

- [S3 Bucket](https://s3.console.aws.amazon.com/s3/) - a bucket named `braze-user-csv-import-aaa123` where `aaa123` is a randomly generated string
- [Lambda Function](https://console.aws.amazon.com/lambda/) - a lambda function named `braze-user-csv-import`
- [IAM Role](https://console.aws.amazon.com/iam/) - policy named `braze-user-csv-import-BrazeCSVUserImportRole` to allow lambda to read from S3 and to log function output

#### Run

To run the function, drop a user attribute CSV file in the newly created S3 bucket.

#### Monitoring and Logging

To make sure the function ran successfully, you can read the function's execution logs. Open the Braze User CSV Import function (by selecting it from the list of Lambdas in the console) and navigate to **Monitor**. Here, you can see the execution history of the function. To read the output, click on **View logs in CloudWatch**. Select lambda execution event you want to check.

#### Lambda Configuration

By default, the function is created with 2048MB memory size. Lambda's CPU is proportional to the memory size. Even though, the script uses constant, low amount of memory, the stronger CPU power allows to process the file faster and send more requests simultaneously.  
2GB was chosen as the best cost to performance ratio.  
You can review Lambda pricing here: https://aws.amazon.com/lambda/pricing/.

You can reduce or increase the amount of available memory for the function in the Lambda **Configuration** tab. Under _General configuration_, click **Edit**, specify the amount of desired memory and save.

Keep in mind that any more memory above 2GB has diminishing returns where it might improve processing speed by 10-20% but at the same time doubling or tripling the cost.

<a name="execution-times"></a>

## Estimated Execution Times

_2048MB Lambda Function_

| # of rows | Exec. Time |
| --------- | ---------- |
| 10k       | 3s         |
| 100k      | 30s        |
| 1M        | 5 min      |
| 5M        | 30 min     |

<!-- ## What happens if the function fails?

...

## Creating your own Lambda

The serverless application creates the whole stack of services that work together, S3 bucket, policies and the Lambda function. If you want to use an existing bucket, it is not possible with the serverless application. However, you could create and deploy your own Lambda process instead. The steps below will guide you how to accomplish that.

_TODO: Include .zip package in Releases_

1. Download the packaged code from [Releases](https://github.com/braze-inc/growth-shares-lambda-user-csv-import/releases)
2. Create a new Lambda function
3. ... -->
