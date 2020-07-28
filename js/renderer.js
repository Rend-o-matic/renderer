const axios = require('axios').default
const boxjam = require('boxjam')
const ibmCOS = require('ibm-cos-sdk')

const main = async (opts) => {
  // get the songid/choirId parameters
  const songId = opts.songId
  const choirId = opts.choirId
  if (!songId || !choirId) {
    return { ok: false, message: 'missing parameters' }
  }

  // get optional parameters
  const width = opts.width || 1920
  const height = opts.height || 1080
  const reverb = opts.reverb || 0.1
  const reverbType = opts.reverbType || 'hall'
  const panning = opts.panning || true
  const watermark = opts.watermark || null
  const margin = opts.margin || 10
  const center = opts.center || true

  // COS
  opts.COS_ENDPOINT = opts.COS_ENDPOINT || opts.endpoint || 'https://s3.us.cloud-object-storage.appdomain.cloud'
  const cosCreds = opts.__bx_creds ? opts.__bx_creds['cloud-object-storage'] : undefined
  if (cosCreds) {
    opts.COS_API_KEY = opts.COS_API_KEY || cosCreds.apikey
    opts.COS_INSTANCE_ID = opts.COS_INSTANCE_ID || cosCreds.resource_instance_id
  }
  const config = {
    endpoint: opts.COS_ENDPOINT,
    apiKeyId: opts.COS_API_KEY,
    serviceInstanceId: opts.COS_INSTANCE_ID
  }
  const cos = new ibmCOS.S3(config)

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

  // turn the song parts in to an array of rectangle objects
  if (response.ok && response.parts.length > 0) {
    const rectangles = []
    for (var i in response.parts) {
      const p = response.parts[i]
      const ar = p.aspectRatio.split(':')
      const w = parseInt(ar[0])
      const h = parseInt(ar[1])
      const obj = {
        id: p.partId,
        width: w,
        height: h
      }
      rectangles.push(obj)
    }
    console.log('rectangles', rectangles)

    // boxjam
    const container = { width: width, height: height }
    const adjustedRectangles = boxjam(rectangles, container, margin, center)
    console.log('boxjam says', adjustedRectangles)

    // construct output JSON
    const output = {
      choir_id: choirId,
      song_id: songId,
      output: {
        size: [width, height],
        reverb: reverb,
        reverb_type: reverbType,
        panning: panning,
        watermark: watermark
      },
      inputs: adjustedRectangles.map((r) => {
        // calculate stereo pan from where the middle of the video overlay
        // pan goes from -1 (left) to 0 (centre) to 1 (right)
        const pan = (2 * ((r.x + r.width / 2) / width) - 1)
        return {
          part_id: r.id,
          position: [r.x, r.y],
          size: [r.width, r.height],
          volume: 1.0,
          panning: pan,
          offset: 0
        }
      })
    }
    console.log('output', JSON.stringify(output))

    // write the definition to a COS bucket
    const key = [opts.choirId, opts.songId, 'auto'].join('+') + '.json'
    await cos.putObject({ Bucket: opts.COS_BUCKET, Key: key, Body: JSON.stringify(output) }).promise()
    console.log('written key', key)
    return { ok: true }
  } else {
    console.log('Nothing to do')
    return { ok: false }
  }
}

module.exports = {
  main
}
