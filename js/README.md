# renderer

> They call me the renderer.....the renderer.....

A serverless function that takes a `choirId` & `songId`:

- gets a list of song parts from the Choirless API.
- calls the "stitcher" serverless action to combine videos

## Parameters

The `main` function expects an object with the following attributes:

- `choirId` - the id choir whose song is to be rendered. (required)
- `songId` - the id of the song to render. (required)
- `CHOIRLESS_API_URL` - the URL Choirless API (required).
- `CHOIRLESS_API_KEY` - the API key for the Choirless API (required).
- `COS_ENDPOINT` - COS endpoint (required)
- `COS_API_KEY` - COS API Key (required)
- `COS_INSTANCE_ID` - COS service instance id (required)
- `COS_BUCKET` - the name of the COS bucket to write the output definition to (required)s

optional parameters:

- `width` - the number of horizontal pixels in the output video (default: `1920`)
- `height` - the number of vertical pixels in the output video (default: `1080`)
- `reverb` - the amount of reverb to add 0 = none, 1 = lots (default: `0.1`)
- `reverbType` - the type of reverb to add: `none`, `smallroom`, `largeroom`, `hall`, `church`  (default `hall`)
- `panning` - whether to pan audio according to video's horizonal position (default:  `true`)
- `watermark` - filename of watermark image (default: `null`)
- `center` - whether to centre the videos (default: `true`)
- `margin` - the number of pixels margin between videos (default: `10`)

> Note: items in capitals are usually embedded in the serverless function "package"

## Example usage

```js
const go = async () => {
  const opts = {
    COUCH_URL: 'https://u:p@myhost.cloudant.com',
    COUCH_CHOIRLESS_DATABASE: 'choirless',
    COS_ENDPOINT: 'https://cos.someendpoint.com',
    COS_API_KEY: 'someapikey,
    COS_INSTANCE_ID: 'someinstanceid',
    COS_BUCKET: 'somebucketname',
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

### Output

```js
{
	"choir_id": "001jtqPK3709Op2285kQ27t8Jc30NULC",
	"song_id": "001jtuMI4bZ1FC3AaBtX2IaLcL4AKbDQ",
	"output": {
		"size": [1920, 1080],
		"reverb": 0.1,
		"reverb_type": "hall",
		"panning": true,
		"watermark": null
	},
	"inputs": [{
		"part_id": "001jtuYx0XUzd80b00Ld33fR0o0TMES6",
		"position": [315, 55],
		"size": [640, 480],
		"volume": 1,
		"panning": -0.33854166666666663,
		"offset": 0
	}, {
		"part_id": "001juWUB17nWwY1WN9mY3aooHu2OLymk",
		"position": [965, 55],
		"size": [640, 480],
		"volume": 1,
		"panning": 0.33854166666666674,
		"offset": 0
	}, {
		"part_id": "001juWlF3nhRa230t8WP2NhoRb2qa1Ka",
		"position": [315, 545],
		"size": [640, 480],
		"volume": 1,
		"panning": -0.33854166666666663,
		"offset": 0
	}, {
		"part_id": "001juWze2dBn3q4Gcbdn2sDLH73GSNdx",
		"position": [965, 545],
		"size": [640, 480],
		"volume": 1,
		"panning": 0.33854166666666674,
		"offset": 0
	}]
}
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