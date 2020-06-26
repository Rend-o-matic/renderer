const openwhisk = require('openwhisk')
const axios = require('axios').default

const main = async (opts) => {
  // get the songid/choirId parameters
  const songId = opts.songId
  const choirId = opts.choirId
  if (!songId || !choirId) {
    return { ok: false, message: 'missing parameters' }
  }

  // get the song parts from the API
  const req = {
    method: 'get',
    baseURL: opts.CHOIRLESS_API_URL,
    url: '/choir/songparts',
    params: {
      apikey: opts.CHOIRLESS_API_KEY,
      songId: songId,
      choirId: choirId
    },
    responseType: 'json'
  }
  const httpResponse = await axios(req)
  const response = httpResponse.data
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
