# renderer

> They call me the renderer.....the renderer.....

A serverless function that takes a `choirId` & `songId`:

- gets a list of song parts from the Choirless API.
- calls the "stitcher" serverless action to combine videos

## Parameters

The `main` function expects an object with the following attributes:

- `choirId` - the id choir whose song is to be rendered.
- `songId` - the id of the song to render.
- `COUCH_URL` - the URL of the Cloudant service (including credentials).
- `COUCH_USERS_DATABASE` - the name of the users database e.g. 'choirless_users'.
- `COUCH_CHOIRLESS_DATABASE` - the name of the main database e.g. 'choirless'.
- `COUCH_KEYS_DATABASE` - the name of the keys database e.g. 'choirless_keys'.
- `COUCH_QUEUE_DATABASE` - the name of the queue database e.g. 'choirless_queue'.

## Example usage

```js
const go = async () => {
  const opts = {
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
docker tag glynnbird/choirless_renderer:latest glynnbird/choirless_renderer:1.0.3

# push it to DockerHub
docker push glynnbird/choirless_renderer:1.0.3

# create an IBM Cloud Function using our index.js but with our custom Docker image
ibmcloud fn action update choirless/renderer --docker glynnbird/choirless_renderer:1.0.3 index.js

# invoke
ibmcloud fn action invoke choirless/renderer --result 
# ^ will fail as no parameters supplied
```

## Deploying

Create a config file `config.json` with the following form:

```js
{
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
ibmcloud fn action update choirless/renderer --docker glynnbird/choirless_renderer:1.0.3 index.js

# test invocation for known choirId/songId
ibmcloud fn action invoke choirless/renderer --result --param choirId "001jZ8zh3NPbQ71ZmcEx3BDvTX1n3mgO" --param songId "001jZ9O31N91NT0bEukk49qjL62D9vWT"
```