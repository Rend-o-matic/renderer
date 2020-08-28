const openwhisk = require('openwhisk')
const ibmCOS = require('ibm-cos-sdk')

const main = async (opts) => {
    // look for a key in opts and pull songId and choidId from there
    const key = opts.notification ? opts.notification.object_name : opts.key

    // COS
    opts.COS_ENDPOINT = opts.COS_ENDPOINT || opts.endpoint || 'https://s3.eu-gb.cloud-object-storage.appdomain.cloud'
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

    const stem = key.split(".")[0]
    let choid_id, song_id, part_id
    [choid_id, song_id, part_id] = stem.split("+")

    // delete in converted bucket
    await cos.deleteObject({
        Bucket:opts.converted_bucket,
        Key: `${choid_id}+${song_id}+${part_id}.nut`
    }).promise()
    
    // delete in snapshot bucket
    await cos.deleteObject({
        Bucket: opts.snapshots_bucket,
        Key: `${choid_id}+${song_id}+${part_id}.jpg`
    }).promise()

    // kick off renderer
    const params = {"key": `${choid_id}+${song_id}+auto.json`}
    const ow = openwhisk()    
    return await ow.actions.invoke({name: "choirless/renderer",
			      params: params,
			      blocking: false})
}

module.exports = {
  main
}

