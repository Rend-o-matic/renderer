import asyncio
import aiohttp
import io
import json
import os
import numpy as np
import random
import tempfile
from pathlib import Path
import uuid

import requests

import ibm_boto3
from ibm_botocore.client import Config

def main(args):
    futures = main_async(args)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(futures)
    return args

async def main_async(args):

    cos = createCOSClient(args)

    if not cos:
        raise ValueError(f"could not create COS instance")

    notification = args.get('notification', {})
    definition_key = args.get('key', notification.get('object_name', ''))

    definition_bucket = args['definition_bucket']
    video_src_bucket = args.get('video_src_bucket')
    audio_src_bucket = args.get('audio_src_bucket')
    auth = args['auth']

    dst_bucket = args.get('dst_bucket')
    
    # Create a temp dir for our files to use
    with tempfile.TemporaryDirectory() as tmpdir:

        # Download the definition file for this job
        definition_object = cos.get_object(
            Bucket=definition_bucket,
            Key=definition_key,
            )
        definition = json.load(definition_object['Body'])

        choir_id = definition['choir_id']
        song_id = definition['song_id']

        inputs = definition['inputs']
        num_inputs = len(inputs)

        scaled_keys = []

        # Go through our inputs and see if we have scaled versions of each
        contents = cos.list_objects(
            Bucket=video_src_bucket,
            Prefix=f"{choir_id}+{song_id}"
        )
        already_scaled = set([ x['Key'] for x in contents.get('Contents', []) ])
        headers = {'X-Require-Whisk-Auth': auth}

        async with aiohttp.ClientSession(headers=headers) as session:
            awaitables = []
            for input in inputs:
                part_id = input['part_id']
                width, height = input['size']
                key = f"{choir_id}+{song_id}+{part_id}.mkv"
                awaitables.append(call_scaler(session,
                                              already_scaled, key,
                                              width, height))

            scaled_keys = await asyncio.gather(*awaitables)
            args['scaled_keys'] = scaled_keys

        return args

async def call_scaler(client, already_scaled, key, width, height):
    scaled_key = f"{Path(key).stem}-{width}-{height}.mkv"
    # Check if we have this already, if not fire off task to scale
    if scaled_key in already_scaled:
        print(f"Found already scaled: {scaled_key}")
        return scaled_key
    else:
        data = {'key': key,
                'width': int(width),
                'height': int(height)
        }

        # Construct the url of the scaler process
        __OW_API_HOST = os.environ['__OW_API_HOST']
        __OW_NAMESPACE = os.environ['__OW_NAMESPACE']
        url = f"{__OW_API_HOST}/api/v1/web/{__OW_NAMESPACE}/choirless/renderer-engine-video-scaler.json"
        
        print(f"Calling scaler: {key} -> {scaled_key}")
        resp = await client.request('POST',
                                    url=url,
                                    json=data)
        if resp.status == 200:
            return scaled_key
        else:
            print("Scaler call returned error", resp.status)

    
def createCOSClient(args):
    """
    Create a ibm_boto3.client using the connectivity information
    contained in args.

    :param args: action parameters
    :type args: dict
    :return: An ibm_boto3.client
    :rtype: ibm_boto3.client
    """

    # if a Cloud Object Storage endpoint parameter was specified
    # make sure the URL contains the https:// scheme or the COS
    # client cannot connect
    if args.get('endpoint') and not args['endpoint'].startswith('https://'):
        args['endpoint'] = 'https://{}'.format(args['endpoint'])

    # set the Cloud Object Storage endpoint
    endpoint = args.get('endpoint',
                        'https://s3.us.cloud-object-storage.appdomain.cloud')

    # extract Cloud Object Storage service credentials
    cos_creds = args.get('__bx_creds', {}).get('cloud-object-storage', {})

    # set Cloud Object Storage API key
    api_key_id = \
        args.get('apikey',
                 args.get('apiKeyId',
                          cos_creds.get('apikey',
                                        os.environ
                                        .get('__OW_IAM_NAMESPACE_API_KEY')
                                        or '')))

    if not api_key_id:
        # fatal error; it appears that no Cloud Object Storage instance
        # was bound to the action's package
        return None

    # set Cloud Object Storage instance id
    svc_instance_id = args.get('resource_instance_id',
                               args.get('serviceInstanceId',
                                        cos_creds.get('resource_instance_id',
                                                      '')))
    if not svc_instance_id:
        # fatal error; it appears that no Cloud Object Storage instance
        # was bound to the action's package
        return None

    ibm_auth_endpoint = args.get('ibmAuthEndpoint',
                                 'https://iam.cloud.ibm.com/identity/token')

    # Create a Cloud Object Storage client using the provided
    # connectivity information
    cos = ibm_boto3.client('s3',
                           ibm_api_key_id=api_key_id,
                           ibm_service_instance_id=svc_instance_id,
                           ibm_auth_endpoint=ibm_auth_endpoint,
                           config=Config(signature_version='oauth'),
                           endpoint_url=endpoint)

    # Return Cloud Object Storage client
    return cos

def batch(iterable, n=1):
    l = len(iterable)
    for ndx in range(0, l, n):
        yield iterable[ndx:min(ndx + n, l)]
