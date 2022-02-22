#!/bin/sh
VERSION=`grep "SemanticVersion" template.yaml | awk '{print $2}'`

echo "Creating build directory"

if [ -d "./build" ]
then 
    echo "Build directory exists, skipping"
else
    mkdir build
fi

echo "Packaging depencies"
cd braze_user_csv_import
pip install --target ./package requests tenacity
echo "Packaging the app"
cd package
zip -r ../braze-lambda-user-csv-import-v"$VERSION".zip .
cd ..
zip -g braze-lambda-user-csv-import-v"$VERSION".zip app.py
mv braze-lambda-user-csv-import-v"$VERSION".zip ../build
rm -r package
echo "Done"
