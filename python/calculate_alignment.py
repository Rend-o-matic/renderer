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

from choirless_lib import create_cos_client, mqtt_status

SAMPLE_RATE = 44100
HOP_LENGTH = 512


@mqtt_status()
def main(args):
    cos = create_cos_client(args)
    bucket = args.get('bucket')

    if not cos:
        raise ValueError("could not create COS instance")

    notification = args.get('notification', {})
    rendition_key = args.get('key', notification.get('object_name', ''))

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
                reference_key = f"{part['choirId']}+{part['songId']}+{part['partId']}.nut"
    except:
        print(f"Could not look up part in API: choidId {choir_id} songId {song_id}")

    # Abort if we are the reference part
    if rendition_key == reference_key:
        ret = {"offset":  0,
               "err": 0,
               "key": rendition_key,
               "rendition_key": rendition_key,
               "reference_key": reference_key,
               }
        
        return ret

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

    # Check we have a tempo, if not say offset is zero
    if tempo0 > 0 and tempo1 > 0:
    
        # Actually calculate the offset
        offset, error = find_offset(data0, data1)
        print(f"Offset: {offset} Error: {error}")

        # Convert offset to milliseconds
        offset = int(((offset * HOP_LENGTH) / SAMPLE_RATE) * 1000)
    else:
        offset, error = 0, 0

    # If the offset is too great, assume we failed and fallback to zero
    if offset > 700:
        print(f"Offset was too great ({offset}) so falling back to zero")
        offset = 0

    ret = {"offset":  offset,
           "err": error,
           "key": rendition_key,
           "rendition_key": rendition_key,
           "reference_key": reference_key,
    }
    
    return ret


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
    error0 = measure_error(x0, x1, 0)
    offsets = np.arange(0,50)
    errors = np.array([measure_error(x0, x1, -offset) for offset in offsets])
    best_offset = argrelextrema(errors, np.less)[0][0]
    best_error = errors[best_offset]

    if error0 <= best_error:
        return 0, error0
    else:
        return best_offset, best_error


# function to measure two waveforms with one offset by a certian amount
def measure_error(x0, x1, offset):
    max_len = min(len(x0), len(x1))

    # calculate the mean squared error of the two signals
    diff = x0[:max_len] - np.roll(x1[:max_len], offset)
    err = np.sum(diff**2) / len(diff)
    return err
