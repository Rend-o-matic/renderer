import io
import json
import os
import librosa
import numpy as np
import re
import tempfile
from pathlib import Path

import ibm_boto3
from ibm_botocore.client import Config


SAMPLE_RATE = 44100

# function to process the signals and get something that
# we can compare against each other.
def process_signal(o):
    # normalise the values (zscore)
    o = (o - np.mean(o)) / np.std(o)
    # take any values > 2 standard deviations
    o = np.where(o > 2, 1.0, 0.0)

    # add an 'decay' to the values such that we can do a more 'fuzzy' match
    # forward pass
    for i in range(1, len(o)):
        o[i] = max(o[i], o[i-1] * 0.9)

    # backwards pass
    for i in range(len(o)-2, 0, -1):
        o[i] = max(o[i], o[i+1] * 0.9)

    return o


# Find the offest with the lowest error
def find_offset(x0, x1):
    offsets = tuple(range(-100, 100))
    errors = [(measure_error(x0, x1, offset), offset) for offset in offsets]

    error, offset = sorted(errors)[0]

    return -offset, error


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

    key = args['key']
    mo = re.match(r'^(.*?)\+(.*?)\+(converted)\.(.*?)$', key)
    if not mo:
        raise ValueError(f"Could not parse key: {key}")

    choir_id, part_key, stage, ext = mo.groups()

    args['part_key'] = f"{choir_id}+{part_key}+{stage}.{ext}"
    args['reference_key'] = f"{choir_id}+reference+{stage}.{ext}"

    if part_key == 'reference':
        args["offset"] = 0
        args["err"] = 0
        return args

    return manual_main(args)

def manual_main(args):

    cos = createCOSClient(args)
    bucket = args.get('bucket')

    if not cos:
        raise ValueError(f"could not create COS instance")

    reference_key = args['reference_key']
    part_key = args['part_key']

    def load_from_cos(key):
        # Create a temp dir for our files to use
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir, key)
            cos.download_file(bucket, key, str(file_path))

            # load the audio from out temp file
            return librosa.load(file_path,
                                sr=SAMPLE_RATE,
                                mono=True,
                                offset=5,
                                duration=20)

    # load in the leader
    x0, fs0 = load_from_cos(reference_key)

    # load in sarah
    x1, fs1 = load_from_cos(part_key)

    # Normalise the two signals so that they are the same average
    # amplitude (volume)
    x0 = (x0 - np.mean(x0)) / np.std(x0)
    x1 = (x1 - np.mean(x1)) / np.std(x1)

    # Calculate the 'onset strength' of the files, ie where parts start
    o0 = librosa.onset.onset_strength(x0, sr=fs0)
    o1 = librosa.onset.onset_strength(x1, sr=fs1)

    # process the signal of the leader and sarah
    s0 = process_signal(o0)
    s1 = process_signal(o1)

    # Actually calculate the offset
    offset, error = find_offset(s0, s1)

    args["offset"] = ((offset * 512) / SAMPLE_RATE) * 1000
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
