# User Attribute CSV to Braze Ingestion

This serverless application allows you to easily deploy a Lambda process that will post user attribute data from a CSV file directly to Braze using Braze Rest API endpoint [User Track](https://www.braze.com/docs/api/endpoints/user_data/post_user_track/). The process launches immediately when you upload a CSV file to the configured AWS S3 bucket.  
It can handle large files and uploads. However, it is important to keep in mind that due to Lambda's time limits, the function will stop execution after 10 minutes. The process will launch another Lambda instance to finish processing the remaining of the file. For more details about function timing, checkout [Execution Times](#execution-times).

### CSV User Attributes

User attributes to be updated are expected in the following `.csv` format:

    external_id,attr_1,...,attr_n
    userID,value_1,...,value_n

where the first column must specify the external ID of the user to be updated and the following columns specify attribute names and values. The amount of attributes you specify can vary. If the CSV file to be processed does not follow this format, the function will fail.


#### REST Endpoint

You can find your API URL, or the REST endpoint, in Braze documentation -- https://www.braze.com/docs/user_guide/administrative/access_braze/braze_instances/#braze-instances. Simply match your dashboard URL to the REST endpoint URL.  
For example, if your dashboard shows `dashboard-01.braze.com/` URL, your REST endpoint would be `https://rest.iad-01.braze.com`.

#### API Key

To connect with Braze servers, we also need an API key. This unique identifier allows Braze to verify your identity and upload your data. To get your API key, open the Dashboard and scroll down the left navigation section. Select **Developer Console** under _App Settings_.
You will need an API key that has a permission to post to `user.track` API endpoint. If you know one of your API keys supports that endpoint, you can use that key. To create a new one, click on `Create New API Key` on the right side of your screen.
Next, name your API Key and select `users.track` under the _User Data_ endpoints group. Scroll down and click on **Save API Key**.
We will need this key shortly.