const stitcheroo = require('stitcheroo')
const fs = require('fs')
const os = require('os')
const path = require('path')
const ibmCOS = require('ibm-cos-sdk')

// read a COS object to a local file using streams
const pullFromCOS = async (cos, params, localFilename) => {
  console.log('pullFromCOS', params, '--->', localFilename)
  return new Promise((resolve, reject) => {
    const ws = fs.createWriteStream(localFilename)
    cos.getObject(params).createReadStream().pipe(ws)
      .on('close', resolve)
      .on('error', reject)
  })
}

// Parameters
// videos - array of COS keys for the videos to combine
// width - int - width of output video in pixels
// height - int - height of output video in pixels
// margin - int - gap between videos
// center - boolean - whether to centre on screen
// pan - boolean - whether to pan audio to match position on screen
// reverbType - string - one of none, smallroom, largeroom, hall, church
// reverbMix - number - 0 = zero reverb in mix, 1 = 100% reverb in mix
// outputKey - COS key to write output to
// COS_ENDPOINT - COS endpoint
// COS_API_KEY - COS API Key
// COS_INSTANCE_ID - COS service instance id
// COS_BUCKET - name of COS bucket where files are stored
const main = async (opts) => {
  opts.COS_ENDPOINT = opts.COS_ENDPOINT || opts.endpoint || 'https://s3.us.cloud-object-storage.appdomain.cloud'
  const cosCreds = opts.__bx_creds ? opts.__bx_creds['cloud-object-storage'] : undefined
  if (cosCreds) {
    opts.COS_API_KEY = opts.COS_API_KEY || cosCreds.apikey
    opts.COS_INSTANCE_ID = opts.COS_INSTANCE_ID || cosCreds.resource_instance_id
  }

  // check for mandatory parameters
  const mandatoryParams = ['videos', 'width', 'height', 'margin', 'pan', 'center', 'reverbType', 'reverbMix', 'outputKey', 'COS_ENDPOINT', 'COS_API_KEY', 'COS_INSTANCE_ID']
  for (var i in mandatoryParams) {
    if (typeof opts[mandatoryParams[i]] === 'undefined') {
      return { ok: false, error: 'missing param ' + mandatoryParams[i] }
    }
  }
  // configure COS
  const config = {
    endpoint: opts.COS_ENDPOINT,
    apiKeyId: opts.COS_API_KEY,
    serviceInstanceId: opts.COS_INSTANCE_ID
  }
  const cos = new ibmCOS.S3(config)

  // fetch the song parts' mp4 files from COS
  const tmp = os.tmpdir()
  const localVideos = []
  for (i in opts.videos) {
    const localFilename = path.join(tmp, i + '.mp4')
    await pullFromCOS(cos, { Bucket: opts.COS_BUCKET, Key: opts.videos[i] }, localFilename)
    localVideos.push(localFilename)
  }
  console.log('local video files', localVideos)

  // render the videos to a single video
  const params = {
    dimensions: {
      width: opts.width,
      height: opts.height
    },
    margin: opts.margin,
    center: opts.center,
    returnAsFile: true,
    pan: opts.pan,
    reverb: {
      type: opts.reverbType,
      mix: opts.reverbMix
    }
  }
  const filename = await stitcheroo(localVideos, params)
  console.log('finished video', filename)

  // write back to COS
  console.log('writing finished video to cos')
  await cos.putObject({
    Bucket: opts.COS_BUCKET,
    Key: opts.outputKey,
    Body: fs.createReadStream(filename)
  }).promise()
  console.log('done')

  // clean up temp files
  fs.unlinkSync(filename)
  for (i in localVideos) {
    fs.unlinkSync(localVideos[i])
  }

  return { ok: true, key: opts.outputKey }
}

module.exports = {
  main
}
