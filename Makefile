# Cloud Object Storage instance name 
COS_INSTANCE_NAME ?= cloud-object-storage-cb
COS_REGION ?= eu-gb

# Regional buckets in above Cloud Object Storage instance
RAW_BUCKET_NAME ?= choirless-videos-raw
CONVERTED_BUCKET_NAME ?= choirless-videos-converted
TRIMMED_BUCKET_NAME ?= choirless-videos-trimmed
PREVIEW_BUCKET_NAME ?= choirless-videos-preview
FINAL_BUCKET_NAME ?= choirless-videos-final

# Namespace functions will be created int
NAMESPACE_NAME ?= choirless

# Choirless API details
CHOIRLESS_API_URL ?= https://choirless-api.eu-gb.mybluemix.net/
CHOIRLESS_API_KEY ?=
RENDERER_KEY ?= 

normalbuild: clean package build

build: actions sequences triggers rules list

fullclean: clean deletenamespace

fullbuild: namespace cos-auth build

deletenamespace:
	ic fn namespace delete $${namespace}

clean:
	for namespace in `ibmcloud fn namespace list | egrep  "^choirless " | awk '{print $$3}'`; do \
		ic fn trigger list /$${namespace} | grep "/" | awk '{print $$1}' | xargs -n1 ic fn trigger delete ; \
		ic fn action list /$${namespace} | grep "/" | awk '{print $$1}' | xargs -n1 ic fn action delete ; \
		ic fn rule list /$${namespace} | grep "/" | awk '{print $$1}' | xargs -n1 ic fn rule delete ; \
		ic fn package list /$${namespace} | grep "/" | awk '{print $$1}' | xargs -n1 ic fn package delete ; \
	done

# Create buckets in COS
create-buckets:
	ibmcloud cos create-bucket --bucket $(RAW_BUCKET_NAME) --ibm-service-instance-id $(COS_INSTANCE_NAME) --region $(COS_REGION)
	ibmcloud cos create-bucket --bucket $(CONVERTED_BUCKET_NAME) --ibm-service-instance-id $(COS_INSTANCE_NAME) --region $(COS_REGION)
	ibmcloud cos create-bucket --bucket $(TRIMMED_BUCKET_NAME) --ibm-service-instance-id $(COS_INSTANCE_NAME) --region $(COS_REGION)
	ibmcloud cos create-bucket --bucket $(PREVIEW_BUCKET_NAME) --ibm-service-instance-id $(COS_INSTANCE_NAME) --region $(COS_REGION)
	ibmcloud cos create-bucket --bucket $(FINAL_BUCKET_NAME) --ibm-service-instance-id $(COS_INSTANCE_NAME) --region $(COS_REGION)

# Create and set namespace
namespace:
	ibmcloud fn namespace create $(NAMESPACE_NAME) --description "Choirless video processing service"
	ibmcloud fn property set --namespace $(NAMESPACE_NAME)

# Prepare namespace for Cloud Object Storage triggers
cos-auth:
	ibmcloud iam authorization-policy-create functions cloud-object-storage "Notifications Manager" --source-service-instance-name $(NAMESPACE_NAME) --target-service-instance-name $(COS_INSTANCE_NAME)

# Create the package
package:
	ibmcloud fn package create choirless \
	 --param CHOIRLESS_API_URL $(CHOIRLESS_API_URL) \
	 --param CHOIRLESS_API_KEY $(CHOIRLESS_API_KEY)
	# Bind COS instance to the package
	ibmcloud fn service bind cloud-object-storage choirless --instance $(COS_INSTANCE_NAME)

# Actions
actions:
	# Convert format
	ibmcloud fn action update choirless/convert_format python/convert_format.py \
	 --param src_bucket $(RAW_BUCKET_NAME) \
         --param dst_bucket $(CONVERTED_BUCKET_NAME) \
	 --docker hammertoe/librosa_ml:latest --timeout 600000 --memory 512

	# Calculate alignment
	ibmcloud fn action update choirless/calculate_alignment python/calculate_alignment.py \
	 --param bucket $(CONVERTED_BUCKET_NAME) \
	 --docker hammertoe/librosa_ml:latest --timeout 600000 --memory 512

	# Trim clip
	ibmcloud fn action update choirless/trim_clip python/trim_clip.py \
	 --param src_bucket $(CONVERTED_BUCKET_NAME) \
	 --param dst_bucket $(TRIMMED_BUCKET_NAME)  \
	 --docker hammertoe/librosa_ml:latest --timeout 600000 --memory 512

	# Pass to sticher
	ibmcloud fn action update choirless/pass_to_sticher python/pass_to_sticher.py \
	 --param src_bucket $(TRIMMED_BUCKET_NAME) \
	 --param dst_bucket $(PREVIEW_BUCKET_NAME) \
	 --docker hammertoe/librosa_ml:latest --timeout 600000 --memory 512

	# Sticher
	ibmcloud fn action update choirless/stitcher js/stitcher.js \
         --docker choirless/choirless_js_actions:latest --memory 2048 -t 600000

	# Renderer
	ibmcloud fn action update choirless/renderer js/renderer.js \
	 --web true --web-secure $(RENDERER_KEY) \
	 --docker choirless/choirless_js_actions:latest --memory 2048 -t 600000

	# Snapshot
	ibmcloud fn action update choirless/snapshot python/snapshot.py \
	 --param bucket $(PREVIEW_BUCKET_NAME) \
	 --docker hammertoe/librosa_ml:latest --timeout 600000 --memory 512


sequences:
	# Calc alignment and Trim amd stitch
	ibmcloud fn action update choirless/calc_and_trim --sequence choirless/calculate_alignment,choirless/trim_clip
	ibmcloud fn action update choirless/stitch --sequence choirless/pass_to_sticher,choirless/stitcher

triggers:
	# Upload to raw bucket
	ibmcloud fn trigger create bucket_raw_upload_trigger --feed /whisk.system/cos/changes \
	 --param bucket $(RAW_BUCKET_NAME) --param event_types write

	# Upload to converted bucket
	ibmcloud fn trigger create bucket_converted_upload_trigger --feed /whisk.system/cos/changes \
	 --param bucket $(CONVERTED_BUCKET_NAME) --param event_types write

	# Upload to trimmed bucket
	ibmcloud fn trigger create bucket_trimmed_upload_trigger --feed /whisk.system/cos/changes \
	 --param bucket $(TRIMMED_BUCKET_NAME) --param event_types write

	# Upload to preview bucket	
	ibmcloud fn trigger create bucket_preview_upload_trigger --feed /whisk.system/cos/changes \
	 --param bucket $(PREVIEW_BUCKET_NAME) --param event_types write

rules:
	# Upload to raw bucket
	ibmcloud fn rule create bucket_raw_upload_rule bucket_raw_upload_trigger choirless/convert_format

	# Upload to converted bucket
	ibmcloud fn rule create bucket_converted_upload_rule bucket_converted_upload_trigger choirless/calc_and_trim

	# Upload to trimmed bucket
	ibmcloud fn rule create bucket_trimmed_upload_rule bucket_trimmed_upload_trigger choirless/stitch

	# Upload to preview bucket
	ibmcloud fn rule create bucket_preview_upload_rule bucket_preview_upload_trigger choirless/snapshot

list:
	# Display entities in the current namespace
	ibmcloud fn list


