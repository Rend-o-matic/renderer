const path = require('path')
const openwhisk = require('openwhisk')

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
    return { ok: false, message: 'missing parameters' }
  }

  // get the song parts from the database
  const response = await choirlessAPI.getChoirSongParts({ songId: songId, choirId: choirId })
  console.log('choirlessAPI response', response)

  // calculate the filenames of the videos
  const videos = response.parts.map((p) => {
      return [p.choirId, p.songId, p.partId].join('+') + '.mp4'
  })
  const outputKey = [choirId, songId, 'final'].join('+') + '.mp4'
  console.log('COS keys', videos)

  // call the sticher service
  const ow = openwhisk()
  const params = {
    videos: videos,
    width: 720,
    height: 390,
    center: true,
    pan: true,
    margin: 20,
    reverbType: 'hall',
    reverbMix: 0.1,
    outputKey: outputKey
  }
  console.log(params)
  try {
    const invocation = await ow.actions.invoke({ name: 'choirless/stitcher', params: params })
    return { ok: true, key: invocation }
  } catch (e) {
    console.error(e)
    return { ok: false }
  }
}

module.exports = {
  main
}
