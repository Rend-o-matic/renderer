# Cloud Object Storage instance name 
COS_INSTANCE_NAME ?= cloud-object-storage-cb
COS_REGION ?= eu-gb
COS_ENDPOINT = s3.private.eu-gb.cloud-object-storage.appdomain.cloud

# Regional buckets in above Cloud Object Storage instance
RAW_BUCKET_NAME ?= choirless-videos-raw
CONVERTED_BUCKET_NAME ?= choirless-videos-converted
DEFINITION_BUCKET_NAME ?= choirless-videos-definition
PREPROD_BUCKET_NAME ?= choirless-videos-preprod
PREVIEW_BUCKET_NAME ?= choirless-videos-preview
FINAL_PARTS_BUCKET_NAME ?= choirless-videos-final-parts
FINAL_BUCKET_NAME ?= choirless-videos-final
STATUS_BUCKET_NAME ?= choirless-videos-status
SNAPSHOTS_BUCKET_NAME ?= choirless-videos-snapshots
MISC_BUCKET_NAME ?= choirless-videos-misc

# Namespace functions will be created int
NAMESPACE_NAME ?= choirless

# Choirless API details
CHOIRLESS_API_URL ?= https://choirless-api.eu-gb.mybluemix.net/
CHOIRLESS_API_KEY ?=
RENDERER_KEY ?= 

# Docker images
PYTHON_IMAGE ?= choirless/choirless_py_actions:release-0.21
NODEJS_IMAGE ?= choirless/choirless_js_actions:release-0.21

# MQTT details
MQTT_BROKER ?= mqtt.eclipse.org:1883


normalbuild: clean package build

build: actions sequences triggers rules list

fullclean: clean deletenamespace

fullbuild: namespace cos-auth build

deletenamespace:
	ic fn namespace delete $${namespace}

clean:
	ibmcloud fn property set --namespace $(NAMESPACE_NAME)
	$(eval NAMESPACE_ID := $(shell ibmcloud fn property get --namespace | cut -f 3))
	ic fn trigger list /$(NAMESPACE_ID) | grep "/$(NAMESPACE_ID)" | cut -d ' ' -f 1 | xargs -n1 ic fn trigger delete 
	ic fn action list /$(NAMESPACE_ID) | grep "/$(NAMESPACE_ID)" | cut -d ' ' -f 1 | xargs -n1 ic fn action delete
	ic fn rule list /$(NAMESPACE_ID) | grep "/$(NAMESPACE_ID)" | cut -d ' ' -f 1 | xargs -n1 ic fn rule delete
	ic fn package list /$(NAMESPACE_ID) | grep "/$(NAMESPACE_ID)" | cut -d ' ' -f 1 | xargs -n1 ic fn package delete

# Create buckets in COS
create-buckets:
	ibmcloud cos create-bucket --bucket $(RAW_BUCKET_NAME) --ibm-service-instance-id $(COS_INSTANCE_NAME) --region $(COS_REGION)
	ibmcloud cos create-bucket --bucket $(CONVERTED_BUCKET_NAME) --ibm-service-instance-id $(COS_INSTANCE_NAME) --region $(COS_REGION)
	ibmcloud cos create-bucket --bucket $(DEFINITION_BUCKET_NAME) --ibm-service-instance-id $(COS_INSTANCE_NAME) --region $(COS_REGION)
	ibmcloud cos create-bucket --bucket $(FINAL_PARTS_BUCKET_NAME) --ibm-service-instance-id $(COS_INSTANCE_NAME) --region $(COS_REGION)
	ibmcloud cos create-bucket --bucket $(PREPROD_BUCKET_NAME) --ibm-service-instance-id $(COS_INSTANCE_NAME) --region $(COS_REGION)
	ibmcloud cos create-bucket --bucket $(PREVIEW_BUCKET_NAME) --ibm-service-instance-id $(COS_INSTANCE_NAME) --region $(COS_REGION)
	ibmcloud cos create-bucket --bucket $(FINAL_BUCKET_NAME) --ibm-service-instance-id $(COS_INSTANCE_NAME) --region $(COS_REGION)
	ibmcloud cos create-bucket --bucket $(STATUS_BUCKET_NAME) --ibm-service-instance-id $(COS_INSTANCE_NAME) --region $(COS_REGION)
	ibmcloud cos create-bucket --bucket $(SNAPSHOTS_BUCKET_NAME) --ibm-service-instance-id $(COS_INSTANCE_NAME) --region $(COS_REGION)
	ibmcloud cos create-bucket --bucket $(MISC_BUCKET_NAME) --ibm-service-instance-id $(COS_INSTANCE_NAME) --region $(COS_REGION)

# Create and set namespace
namespace:
	ibmcloud fn namespace create $(NAMESPACE_NAME) --description "Choirless DEV video processing service"
	ibmcloud fn property set --namespace $(NAMESPACE_NAME)

# Prepare namespace for Cloud Object Storage triggers
cos-auth:
	ibmcloud iam authorization-policy-create functions cloud-object-storage "Notifications Manager" --source-service-instance-name $(NAMESPACE_NAME) --target-service-instance-name $(COS_INSTANCE_NAME)

# Create the package
package:
	ibmcloud fn property set --namespace $(NAMESPACE_NAME)
	ibmcloud fn package update choirless \
	 --param CHOIRLESS_API_URL $(CHOIRLESS_API_URL) \
	 --param CHOIRLESS_API_KEY $(CHOIRLESS_API_KEY) \
	 --param ENDPOINT $(COS_ENDPOINT) \
	 --param geo $(COS_REGION) \
	 --param auth $(RENDERER_KEY) \
	 --param mqtt_broker $(MQTT_BROKER) \
	 --param definition_bucket $(DEFINITION_BUCKET_NAME) \
	 --param raw_bucket $(RAW_BUCKET_NAME) \
	 --param converted_bucket $(CONVERTED_BUCKET_NAME) \
	 --param final_parts_bucket $(FINAL_PARTS_BUCKET_NAME) \
	 --param preprod_bucket $(PREPROD_BUCKET_NAME) \
	 --param preview_bucket $(PREVIEW_BUCKET_NAME) \
	 --param final_bucket $(FINAL_BUCKET_NAME) \
	 --param status_bucket $(STATUS_BUCKET_NAME) \
	 --param snapshots_bucket $(SNAPSHOTS_BUCKET_NAME) \
	 --param misc_bucket $(MISC_BUCKET_NAME)

	# Bind COS instance to the package
	ibmcloud fn service bind cloud-object-storage choirless --instance $(COS_INSTANCE_NAME)

# Actions
actions: convert_format calculate_alignment trim_clip \
	 renderer renderer_compositor_main renderer_compositor_child renderer_final \
	 snapshot delete_handler post_production

# Convert format
convert_format:
	ibmcloud fn action update choirless/convert_format python/convert_format.py \
	 --docker $(PYTHON_IMAGE) --timeout 600000 --memory 2048

# Calculate alignment
calculate_alignment:
	ibmcloud fn action update choirless/calculate_alignment python/calculate_alignment.py \
	 --docker $(PYTHON_IMAGE) --timeout 600000 --memory 2048

# Trim clip
trim_clip:
	ibmcloud fn action update choirless/trim_clip python/trim_clip.py \
	 --docker $(PYTHON_IMAGE) --timeout 600000 --memory 512

# Renderer front end
renderer:
	ibmcloud fn action update choirless/renderer js/renderer.js \
	 --docker $(NODEJS_IMAGE) --memory 2048 -t 600000 \
	 --web true --web-secure $(RENDERER_KEY)

# Renderer main process
renderer_compositor_main:
	ibmcloud fn action update choirless/renderer_compositor_main js/renderer_compositor_main.js \
	 --docker $(NODEJS_IMAGE)

# Renderer child process
renderer_compositor_child:
	ibmcloud fn action update choirless/renderer_compositor_child python/renderer_compositor_child.py \
	 --docker $(PYTHON_IMAGE) --timeout 600000 --memory 2048 

# Renderer final process
renderer_final:
	ibmcloud fn action update choirless/renderer_final python/renderer_final.py \
	 --docker $(PYTHON_IMAGE) --timeout 600000 --memory 2048

# Snapshot
snapshot:
	ibmcloud fn action update choirless/snapshot python/snapshot.py \
	 --docker $(PYTHON_IMAGE) --memory 2048

# Status report
status:
	ibmcloud fn action update choirless/status python/status.py

# Delete handler
delete_handler:
	ibmcloud fn action update choirless/delete_handler js/delete_handler.js \
	 --docker $(NODEJS_IMAGE)

# Post-production
post_production:
	ibmcloud fn action update choirless/post_production python/post_production.py \
	 --docker $(PYTHON_IMAGE) --timeout 600000 --memory 2048


sequences: calc_and_render

# Calc alignment and kick of render of json definition
calc_and_render:
	ibmcloud fn action update choirless/calc_and_render --sequence choirless/calculate_alignment,choirless/renderer

triggers: bucket_raw_upload_trigger bucket_converted_upload_trigger \
	  bucket_definition_upload_trigger \
	  bucket_final_parts_upload_trigger bucket_preview_upload_trigger \
	  bucket_raw_delete_trigger bucket_preprod_upload_trigger 

# Upload to raw bucket
bucket_raw_upload_trigger:
	ibmcloud fn trigger create bucket_raw_upload_trigger --feed /whisk.system/cos/changes \
	 --param bucket $(RAW_BUCKET_NAME) --param event_types write

# Upload to converted bucket
bucket_converted_upload_trigger:
	ibmcloud fn trigger create bucket_converted_upload_trigger --feed /whisk.system/cos/changes \
	 --param bucket $(CONVERTED_BUCKET_NAME) --param event_types write --param suffix ".nut"

# Upload to definition bucket
bucket_definition_upload_trigger:
	ibmcloud fn trigger create bucket_definition_upload_trigger --feed /whisk.system/cos/changes \
	 --param bucket $(DEFINITION_BUCKET_NAME) --param event_types write

# Upload to final parts
bucket_final_parts_upload_trigger:
	ibmcloud fn trigger create bucket_final_parts_upload_trigger --feed /whisk.system/cos/changes \
	 --param bucket $(FINAL_PARTS_BUCKET_NAME) --param event_types write

# Upload to pre-prod
bucket_preprod_upload_trigger:
	ibmcloud fn trigger create bucket_preprod_upload_trigger --feed /whisk.system/cos/changes \
	 --param bucket $(PREPROD_BUCKET_NAME) --param event_types write

# Upload to preview bucket
bucket_preview_upload_trigger:
	ibmcloud fn trigger create bucket_preview_upload_trigger --feed /whisk.system/cos/changes \
	 --param bucket $(PREVIEW_BUCKET_NAME) --param event_types write --param suffix ".mp4"

# Delete from raw bucket
bucket_raw_delete_trigger:
	ibmcloud fn trigger create bucket_raw_delete_trigger --feed /whisk.system/cos/changes \
	 --param bucket $(RAW_BUCKET_NAME) --param event_types delete

rules: bucket_raw_upload_rule bucket_converted_upload_rule \
       bucket_definition_upload_rule \
       bucket_final_parts_upload_rule bucket_preview_upload_rule bucket_raw_snapshot_rule \
       bucket_raw_delete_rule bucket_preprod_upload_rule


# Upload to raw bucket
bucket_raw_upload_rule:
	ibmcloud fn rule update bucket_raw_upload_rule bucket_raw_upload_trigger choirless/convert_format

# Upload to converted bucket
bucket_converted_upload_rule:
	ibmcloud fn rule update bucket_converted_upload_rule bucket_converted_upload_trigger choirless/calc_and_render

# Upload to definition bucket
bucket_definition_upload_rule:
	ibmcloud fn rule update bucket_definition_upload_rule bucket_definition_upload_trigger choirless/renderer_compositor_main

# Upload to final parts bucket
bucket_final_parts_upload_rule:
	ibmcloud fn rule update bucket_final_parts_upload_rule bucket_final_parts_upload_trigger choirless/renderer_final

# Upload to pre-prod bucket
bucket_preprod_upload_rule:
	ibmcloud fn rule update bucket_preprod_upload_rule bucket_preprod_upload_trigger choirless/post_production

# Upload to preview bucket
bucket_preview_upload_rule:
	ibmcloud fn rule update bucket_preview_upload_rule bucket_preview_upload_trigger choirless/snapshot

# Upload to raw snapshot rule
bucket_raw_snapshot_rule:
	ibmcloud fn rule update bucket_raw_snapshot_rule bucket_raw_upload_trigger choirless/snapshot

# Delete from raw bucket
bucket_raw_delete_rule:
	ibmcloud fn rule update bucket_raw_delete_rule bucket_raw_delete_trigger choirless/delete_handler

list:
	# Display entities in the current namespace
	ibmcloud fn list


