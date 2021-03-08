# Apache OpenWhisk IBM Cloud Functions for converting and aligning audio tracks

## Deploy the package

Make sure you are logged in to the IBM Cloud account (`ibmcloud login`). [Create an account](https://developer.ibm.com/dwwi/jsp/register.jsp?eventid=cfc-2020-projects) if you don't have one.

Check the contents of `Makefile` and ensure the namespace and buckets are correct.
Make sure the Cloud Object Storage (COS) buckets you want to use exist. By default:

- `RAW_BUCKET_NAME ?= choirless-videos-raw`
- `CONVERTED_BUCKET_NAME ?= choirless-videos-converted`
- `TRIMMED_BUCKET_NAME ?= choirless-videos-trimmed`

Then run:

```
make
```

This will create the serverless IBM Cloud Functions actions and triggers for the COS buckets.




