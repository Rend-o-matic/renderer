# renderer

> They call me the renderer.....the renderer.....

A serverless function that takes a `choirId` & `songId`:

- gets a list of song parts from the Choirless API.
- pulls down the video files from COS for each video to local temporary storage
- stitches the videos into a video wall using Stitcheroo, creating a new local file
- uploads the finished video to COS

## Parameters

The `main` function expects an object with the following attributes:

- `choirId` - the id choir whose song is to be rendered.
- `songId` - the id of the song to render.
- `COS_API_KEY` - the 'apikey' from the service credentials.
- `COS_INSTANCE_ID` - the 'resource_instance_id' from the service credentials.
- `COS_ENDPOINT` - the [S3 API endpoint](https://cloud.ibm.com/docs/cloud-object-storage?topic=cloud-object-storage-endpoints) not to be confused with 'endpoints' from the service credentials e.g. 's3.eu-gb.cloud-object-storage.appdomain.cloud'.
- `COS_BUCKET` - the name of the bucket to read and write videos.
- `COUCH_URL` - the URL of the Cloudant service (including credentials).
- `COUCH_USERS_DATABASE` - the name of the users database e.g. 'choirless_users'.
- `COUCH_CHOIRLESS_DATABASE` - the name of the main database e.g. 'choirless'.
- `COUCH_KEYS_DATABASE` - the name of the keys database e.g. 'choirless_keys'.
- `COUCH_QUEUE_DATABASE` - the name of the queue database e.g. 'choirless_queue'.

## Example usage

```js
const go = async () => {
  const opts = {
    COS_API_KEY: 'apikey',
    COS_ENDPOINT: 'some.domain.name',
    COS_INSTANCE_ID: 'crn:some:id',
    COS_BUCKET: 'choirless',
    COUCH_URL: 'https://u:p@myhost.cloudant.com',
    COUCH_USERS_DATABASE: 'choirless_users',
    COUCH_CHOIRLESS_DATABASE: 'choirless',
    COUCH_KEYS_DATABASE: 'choirless_keys',
    COUCH_QUEUE_DATABASE: 'choirless_queue',
    songId: 'songId',
    choirId: 'choirId'
  }
  try {
    await main(opts)
  } catch (e) {
    console.log('ERROR', e)
  }
}
```

## Assumptions

Song part videos are stored in the COS bucket with keys

```
<choirId>/<songId>/<partId>.mp4
```

The final video is stored as

```
<choirId>/<songId>/final.mp4
```

## Building Docker image

```sh
# create a docker image, based on the standard OpenWhisk image but with our 
# node_modules added
docker build -t glynnbird/choirless_renderer .
# tag it
docker tag glynnbird/choirless_renderer:latest glynnbird/choirless_renderer:1.0.1

# push it to DockerHub
docker push glynnbird/choirless_renderer:1.0.1
# create an IBM Cloud Function using our index.js but with our custom Docker image
ibmcloud fn action update choirless_renderer --docker glynnbird/choirless_renderer:1.0.1 index.js

# invoke
ibmcloud fn action invoke choirless_renderer --result 
# ^ will fail as no parameters supplied
```

## Deploying

Create a config file `config.json` with the following form:

```js
{
  "COS_API_KEY": "...",
  "COS_ENDPOINT": "...",
  "COS_INSTANCE_ID": "...",
  "COS_BUCKET": "choirless",
  "COUCH_URL": "...",
  "COUCH_USERS_DATABASE": "choirless_users",
  "COUCH_CHOIRLESS_DATABASE": "choirless",
  "COUCH_KEYS_DATABASE": "choirless_keys",
  "COUCH_QUEUE_DATABASE": "choirless_queue"
}
```

> Note: see the parameters section for which values to put in the config file.

```sh
# create a package with the config rolled into it
ibmcloud fn package update choirless -P config.json

# add renderer action into this package with non-default memory size and execution limit
ibmcloud fn action update choirless/renderer --docker glynnbird/choirless_renderer:1.0.1 index.js --memory 2048 -t 600000

# test invocation for known choirId/songId
ibmcloud fn action invoke choirless_renderer --result --param choirId "001jZ8zh3NPbQ71ZmcEx3BDvTX1n3mgO" --param songId "001jZ9O31N91NT0bEukk49qjL62D9vWT"
```