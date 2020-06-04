const sticheroo = require('stitcheroo')
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

const main = async (opts) => {
  // put incoming opts into environment variables for choirlessapi
  const OPTS = ['COUCH_URL', 'COUCH_USERS_DATABASE', 'COUCH_CHOIRLESS_DATABASE', 'COUCH_KEYS_DATABASE', 'COUCH_QUEUE_DATABASE']
  for (const i in OPTS) {
    process.env[OPTS[i]] = opts[OPTS[i]]
  }
  const choirlessAPI = require('choirlessapi')

  // get the songid/choirId parameters
  const songId = opts.songId
  const choirId = opts.choirId
  if (!songId || !choirId) {
    return { ok: false, message: 'missing parameterss' }
  }

  // configure COS
  const config = {
    endpoint: opts.COS_ENDPOINT,
    apiKeyId: opts.COS_API_KEY,
    serviceInstanceId: opts.COS_INSTANCE_ID
  }
  const cos = new ibmCOS.S3(config)

  // get the song parts from the database
  const response = await choirlessAPI.getChoirSongParts({ songId: songId, choirId: choirId })
  console.log('choirlessAPI response', response)

  // calculate the filenames of the videos
  const videos = response.parts.map((p) => {
    return path.join(p.choirId, p.songId, p.partId) + '.mp4'
  })
  console.log('COS keys', videos)

  // fetch the song parts' mp4 files from COS
  const tmp = os.tmpdir()
  const localVideos = []
  for (var i in videos) {
    const localFilename = path.join(tmp, i + '.mp4')
    await pullFromCOS(cos, { Bucket: opts.COS_BUCKET, Key: videos[i] }, localFilename)
    localVideos.push(localFilename)
  }
  console.log('local video files', localVideos)

  // render the videos to a single video
  const filename = await sticheroo(localVideos, false)
  console.log('finished video', filename)

  // write back to COS
  console.log('writing finished video to cos')
  const outputKey = path.join(choirId, songId, 'final') + '.mp4'
  await cos.putObject({
    Bucket: opts.COS_BUCKET,
    Key: outputKey,
    Body: fs.createReadStream(filename)
  }).promise()
  console.log('done')

  // clean up temp files
  fs.unlinkSync(filename)
  for (i in localVideos) {
    fs.unlinkSync(localVideos[i])
  }

  return { ok: true, key: outputKey }
}

module.exports = {
  main
}
