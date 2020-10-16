const openwhisk = require('openwhisk')
const ibmCOS = require('ibm-cos-sdk')
const crypto = require('crypto')
const { v4: uuidv4 } = require('uuid')

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

    // Get the definition from the bucket
    let definition_object = await cos.getObject({ Bucket: opts.definition_bucket, Key: key }).promise()
    let definition = JSON.parse(definition_object['Body'])

    // if we have scenes then loop per scene, if not add artificial scene in
    let scenes = []
    if (definition.scenes == undefined) {
	scenes.push({"scene_id": 1,
		     "inputs": definition.inputs
		    })
    } else {
	scenes = definition.scenes
    }

    let actions = [] 
    const ow = openwhisk()
    let run_id = uuidv4().slice(0,8)
    
    scenes.forEach(scene => {
	// Get the inputs for this scene
	input_specs = scene.inputs
	// Calculate number of rows
	let rows = new Set()
	input_specs.forEach(spec => {
	    let [x, y] = spec.position || [-1, -1]
	    rows.add(y)
	})
	rows = Array.from(rows)
	rows.sort((a,b) => parseInt(a) - parseInt(b))

	let num_rows = rows.length

	// Calculate the hash of our rows
	let rows_str = rows.join("-")
	let rows_hash = crypto.createHash('sha1').update(rows_str).digest('hex').slice(0,8)

	// Invoke all the child actions
	rows.forEach(row => {
	    let params = {"row_num": row,
			  "run_id": run_id,
			  "rows_hash": rows_hash,
			  "compositor": "combined",
			  "key": key,
			  "definition_key": key}
	    let action =  ow.actions.invoke({name: "choirless/renderer_compositor_child",
					     params: params,
					     blocking: false})
	    actions.push(action)
	})
    })
    
    // Await for the child calls to all return with their activation ID
    let res = await Promise.all(actions)
    let activation_ids = res.map(r => {	return r.activationId  })
    
    return {"status": "spawned children",
            "run_id": run_id,
            "definition_key": key,
	    "activation_ids": activation_ids}
}

module.exports = {
  main
}

