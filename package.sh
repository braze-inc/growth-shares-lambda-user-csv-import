#!/bin/sh
set -eu

VERSION=`grep "SemanticVersion" template.yaml | awk '{print $2}'`

echo "Creating build directory"

if [ -d "./build" ]
then
    echo "Build directory exists, skipping"
else
    mkdir build
fi

echo "Packaging dependencies"
cd braze_user_csv_import
# The Lambda Python runtime already provides boto3, botocore, s3transfer,
# and the libraries only those packages need. Leave them out of the zip.
lambda_reqs=$(mktemp)
grep -Ev '^(boto3|botocore|s3transfer|jmespath|python-dateutil|six)==' requirements.txt > "$lambda_reqs"
python3 -m pip install --target ./package -r "$lambda_reqs"
rm -f "$lambda_reqs"
echo "Packaging the app"
cd package
zip -r ../braze-lambda-user-csv-import-v"$VERSION".zip .
cd ..
zip -g braze-lambda-user-csv-import-v"$VERSION".zip *.py
mv braze-lambda-user-csv-import-v"$VERSION".zip ../build
rm -r package
echo "Done"
