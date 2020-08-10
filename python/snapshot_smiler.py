import io
import json
import os
import librosa
import numpy as np
import tempfile
from pathlib import Path

try:
    import importlib.resources as pkg_resources
except ImportError:
    # Try backported to PY<37 `importlib_resources`.
    import importlib_resources as pkg_resources

import cv2

import ibm_boto3
from ibm_botocore.client import Config

from choirless_smiler.smiler import Smiler, load_landmarks

LANDMARKS_URL = "http://dlib.net/files/shape_predictor_68_face_landmarks.dat.bz2"
CACHE_DIR = "~/.smiler"


def main(args):

    cos = createCOSClient(args)

    if not cos:
        raise ValueError(f"could not create COS instance")

    bucket = args.get('preview_bucket')

    notification = args.get('notification', {})
    key = args.get('key', notification.get('object_name', ''))
    if key.endswith(".jpg"):
        return {"success": "true"}

    # Create a temp dir for our files to use
    with tempfile.TemporaryDirectory() as tmpdir:

        # download file to temp dir
        file_path = Path(tmpdir, key)
        new_path = file_path.with_name(f'{file_path.stem}.jpg')

        cos.download_file(bucket, key, str(file_path))
        
        with pkg_resources.path('choirless_smiler', 'smile_detector.tflite') as model_path:

            print("Loading landmarks")
            landmarks_path = load_landmarks(LANDMARKS_URL, CACHE_DIR)
            print("Landmarks loaded")
            
            smiler = Smiler(landmarks_path, model_path)

            print("Calculating threshold")
            fg = smiler.frame_generator(str(file_path))
            threshold = smiler.calc_threshold(fg, 0.95)
            print("Threshold calculated", threshold)

            def callback(frame, smile_score):
                cv2.imwrite(str(new_path), frame)
                cos.upload_file(str(new_path), bucket, str(new_path.name))
                args["snapshot_key"] = str(new_path.name)
                print("New best frame, score:", smile_score)
            
            print("Finding smiliest frame")
            fg = smiler.frame_generator(str(file_path))
            ffg = smiler.filter_frames(fg, threshold)
            smile_score, image = smiler.find_smiliest_frame(ffg, callback=callback)
            print("Smilest frame, score:", smile_score)

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
