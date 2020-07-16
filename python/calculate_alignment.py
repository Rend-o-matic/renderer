import io
import json
import os
import librosa
import numpy as np
import re
import tempfile
from pathlib import Path
from urllib.parse import urljoin
from scipy.signal import argrelextrema

import requests

import ibm_boto3
from ibm_botocore.client import Config


SAMPLE_RATE = 44100
HOP_LENGTH = 512

# function to process the signals and get something that
# we can compare against each other.
def process_signal(x, sr):

    onset_env = librosa.onset.onset_strength(x, sr=sr,
                                             aggregate=np.median)
    print("Calculated onset_env")

    tempo, beats = librosa.beat.beat_track(onset_envelope=onset_env,
                                           sr=sr)
    print("Calculated tempo and beats")

    times = librosa.times_like(onset_env, sr=sr, hop_length=HOP_LENGTH)

    print("Calculated times")

    data = np.zeros(len(onset_env))
    np.put(data, beats, 1)
    for i in range(1, len(data)):
        data[i] = max(data[i], data[i-1] * 0.9)

    for i in range(len(data) - 2, 0, -1):
        data[i] = max(data[i], data[i+1] * 0.9)

    return times, data, tempo, beats


# Find the offest with the lowest error
def find_offset(x0, x1):
    offsets = np.arange(0,50)
    errors = np.array([measure_error(x0, x1, -offset) for offset in offsets])
    best_offset = argrelextrema(errors, np.less)[0][0]
    best_error = errors[best_offset]

    return best_offset, best_error


# function to measure two waveforms with one offset by a certian amount
def measure_error(x0, x1, offset):
    max_len = min(len(x0), len(x1))

    # calculate the mean squared error of the two signals
    diff = x0[:max_len] - np.roll(x1[:max_len], offset)
    err = np.sum(diff**2) / len(diff)
    return err


def main(args):
    cos = createCOSClient(args)
    bucket = args.get('bucket')

    if not cos:
        raise ValueError("could not create COS instance")

    rendition_key = args['key']
    mo = re.match(r'^(.*?)\+(.*?)\+(.*?)\.(.*?)$', rendition_key)
    if not mo:
        raise ValueError(f"Could not parse key: {rendition_key}")

    choir_id, song_id, part_id, ext = mo.groups()

    # Try and detemine the reference key, first by looking in the bucket
    # for a specially named partid, or then via the Choirless API
    reference_key = f"{choir_id}+{song_id}+reference.{ext}"

    # Ask the API if we have parts for this Song
    try:
        api_url = args['CHOIRLESS_API_URL']
        api_key = args['CHOIRLESS_API_KEY']

        params = {'apikey': api_key,
                  'choirId': choir_id,
                  'songId': song_id,}
        req = requests.get(urljoin(api_url, 'choir/songparts'),
                           params=params)
        parts = req.json()['parts']

        # Check each part and look for the reference one
        for part in parts:
            if part['partType'] == 'backing':
                reference_key = f"{part['choirId']}+{part['songId']}+{part['partId']}.mkv"
    except:
        print(f"Could not look up part in API: choidId {choir_id} songId {song_id}")

    # Abort if we are the reference part
    if rendition_key == reference_key:
        args["offset"] = 0
        args["err"] = 0
        args['rendition_key'] = rendition_key
        args['reference_key'] = reference_key
        return args

    args['rendition_key'] = rendition_key
    args['reference_key'] = reference_key

    def load_from_cos(key):
        # Create a temp dir for our files to use
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir, key)
            cos.download_file(bucket, key, str(file_path))

            # load the audio from out temp file
            return librosa.load(file_path,
                                sr=SAMPLE_RATE,
                                mono=True,
                                offset=0,
                                duration=180)

    # load in the leader
    x0, fs0 = load_from_cos(reference_key)
    print("Loaded from COS: ", reference_key)

    # load in sarah
    print("Loading from COS: ", rendition_key)
    x1, fs1 = load_from_cos(rendition_key)
    print("Loaded from COS: ", rendition_key)

    times0, data0, tempo0, beats0 = process_signal(x0, fs0)
    print("Tempo0:", tempo0)
    times1, data1, tempo1, beats1 = process_signal(x1, fs1)
    print("Tempo1:", tempo1)

    # Actually calculate the offset
    offset, error = find_offset(data0, data1)
    print(f"Offset: {offset} Error: {error}")

    # Convert offset to milliseconds
    offset = int(((offset * HOP_LENGTH) / SAMPLE_RATE) * 1000)

    # If the offset is too great, assume we failed and fallback to zero
    if offset > 700:
        print(f"Offset was too great ({offset}) so falling back to zero")
        offset = 0

    args["offset"] = offset
    args["err"] = error

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
