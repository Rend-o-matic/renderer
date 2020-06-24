import io
import json
import os
import librosa
import numpy as np
import tempfile
from pathlib import Path

import ibm_boto3
from ibm_botocore.client import Config

import ffmpeg

SAMPLE_RATE = 44100


def main(args):

    cos = createCOSClient(args)

    if not cos:
        raise ValueError(f"could not create COS instance")

    src_bucket = args.get('src_bucket')
    dst_bucket = args.get('dst_bucket')
    key = args['key']

    # Create a temp dir for our files to use
    with tempfile.TemporaryDirectory() as tmpdir:

        # download file to temp dir
        file_path = Path(tmpdir, key)
        new_path = file_path.with_name(f'{file_path.stem}+converted.mp4')

        cos.download_file(src_bucket, key, str(file_path))

        stream = ffmpeg.input(str(file_path))
        audio = stream.audio.filter('aresample', 44100)
        video = stream.video.filter('fps', fps=25, round='up')
        video = stream.video.filter('scale', 640, -1)
        out = ffmpeg.output(audio, video, str(new_path))
        stdout, stderr = out.run()

        cos.upload_file(str(new_path), dst_bucket, str(new_path.name))

        args["src_bucket"] = src_bucket
        args["dst_bucket"] = dst_bucket
        args["src_key"] = key
        args["dst_key"] = str(new_path.name)

        return args


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
