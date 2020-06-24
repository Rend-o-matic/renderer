# stitcher

A serverless function that stitches a list of videos, supplied as an array of COS keys, to an output video which is written back to COS. It knows nothing about Choirless, does nothing with the Choirless API, it deals only in lists of input videos and and output video. It reads from COS, uses ffmpeg/Sticheroo to render the output and writes the output from COS.

The `index.js` module is deployed with a custom Docker image which includes the `node_modules`. Instructions are in this README.

## Parameters

The `main` function expects an object with the following attributes:

- `videos` - array of COS keys for the videos to combine
- `width` - int - width of output video in pixels
- `height` - int - height of output video in pixels
- `margin` - int - gap between videos
- `center` - boolean - whether to centre on screen
- `pan` - boolean - whether to pan audio to match position on screen
- `reverbType` - string - one of none, smallroom, largeroom, hall, church
- `reverbMix` - number - 0 = zero reverb in mix, 1 = 100% reverb in mix
- `outputKey` - COS key to write output to
- `COS_ENDPOINT` - COS endpoint
- `COS_API_KEY` - COS API Key
- `COS_INSTANCE_ID` - COS service instance id

## Example usage

```js
const go = async () => {
  const opts = {
    COS_API_KEY: 'apikey',
    COS_ENDPOINT: 'some.domain.name',
    COS_INSTANCE_ID: 'crn:some:id',
    COS_BUCKET: 'choirless',
    width: 720,
    height: 390,
    margin: 0,
    center: true,
    pan: true,
    reverbType: 'hall',
    reverbMix: 0.1,
    outputKey: 'x/y/final.mp4',
    videos: [ 'x/y/1.mp4', 'x/y/2.mp4', 'x/y/3.mp4' ]
  }
  try {
    await main(opts)
  } catch (e) {
    console.log('ERROR', e)
  }
}
```

## Building Docker image

```sh
# create a docker image, based on the standard OpenWhisk image but with our 
# node_modules added
docker build -t glynnbird/choirless_stitcher .
# tag it
docker tag glynnbird/choirless_stitcher:latest glynnbird/choirless_stitcher:1.0.0

# push it to DockerHub
docker push glynnbird/choirless_stitcher:1.0.0

# create an IBM Cloud Function using our index.js but with our custom Docker image
ibmcloud fn action update choirless/stitcher --docker glynnbird/choirless_stitcher:1.0.0 index.js --memory 2048 -t 600000

# invoke
ibmcloud fn action invoke choirless/stitcher --result 
# ^ will fail as no parameters supplied
```

## Deploying

Create a config file `config.json` with the following form:

```js
{
  "COS_API_KEY": "...",
  "COS_ENDPOINT": "...",
  "COS_INSTANCE_ID": "...",
  "COS_BUCKET": "choirless"
}
```

> Note: see the parameters section for which values to put in the config file.

```sh
# create a package with the config rolled into it
ibmcloud fn package update choirless -P config.json

# add stitcher action into this package with non-default memory size and execution limit
ibmcloud fn action update choirless/stitcher --docker glynnbird/choirless_stitcher:1.0.0 index.js --memory 2048 -t 600000
```