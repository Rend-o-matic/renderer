# Openwhisk cloud function for converting and aligning audio tracks

## Deploy the package

Make sure you are logged in to the IBM Cloud account (`ibmcloud login`)

Check the contents of `Makefile` and ensure the namespace and buckets are correct.
Make sure the COS buckets you want to use exist. By default:

- RAW_BUCKET_NAME ?= choirless-videos-raw
- CONVERTED_BUCKET_NAME ?= choirless-videos-converted
- TRIMMED_BUCKET_NAME ?= choirless-videos-trimmed

run:

```
make
```

This will create actions and triggers of the COS buckets.




