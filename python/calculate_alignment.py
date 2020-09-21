import io
import json
import os
import librosa
import numpy as np
import re
import tempfile
from pathlib import Path
from urllib.parse import urljoin
from scipy.signal import argrelextrema, find_peaks
from surfboard.sound import Waveform

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


import requests

from choirless_lib import create_cos_client, mqtt_status

SAMPLE_RATE = 44100
HOP_LENGTH = 512


@mqtt_status()
def main(args):
    cos = create_cos_client(args)
    bucket = args.get('bucket')
    debug_bucket = args.get('debug_bucket')

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
    s0, sr0 = load_from_cos(reference_key)
    print("Loaded from COS: ", reference_key)

    # load in sarah
    print("Loading from COS: ", rendition_key)
    s1, sr1 = load_from_cos(rendition_key)
    print("Loaded from COS: ", rendition_key)

    min_len = min(len(s0), len(s1))

    s0 = s0[:min_len]
    s1 = s1[:min_len]

    sound0 = Waveform(signal=s0, sample_rate=sr0)
    sound1 = Waveform(signal=s1, sample_rate=sr1)

    try:
        # Calculate the features
        sf0 = sound0.spectral_flux()[0]
        cf0 = sound0.crest_factor()[0]

        sf1 = sound1.spectral_flux()[0]
        cf1 = sound1.crest_factor()[0]

        prom_sf0 = calc_prominence_threshold(sf0)
        prom_sf1 = calc_prominence_threshold(sf1)
        prom_cf0 = calc_prominence_threshold(cf0)
        prom_cf1 = calc_prominence_threshold(cf1)

        peaks_sf0 = calc_get_peaks(sf0, prom_sf0)
        peaks_sf1 = calc_get_peaks(sf1, prom_sf1)
        peaks_cf0 = calc_get_peaks(cf0, prom_cf0)
        peaks_cf1 = calc_get_peaks(cf1, prom_cf1)

        map_sf0 = map_peaks(peaks_sf0, len(sf0))
        map_sf1 = map_peaks(peaks_sf1, len(sf1))
        map_cf0 = map_peaks(peaks_cf0, len(cf0))
        map_cf1 = map_peaks(peaks_cf1, len(cf1))

        # Set up a chart to plot sync process
        plt.figure(figsize=(20, 6))

        # Acutally calc the offset
        offsets = []
        lookahead_ms = 100
        lookbehind_ms = 400

        offsets = []
        potential_offsets = np.arange(int(ms_to_frames(-lookahead_ms, SAMPLE_RATE)),
                                      int(ms_to_frames(lookbehind_ms, SAMPLE_RATE)))

        # Add 1 here as frame offset is 1/4 of the fft window and we want to be in middle on average
        times = frames_to_ms(potential_offsets + 1, SAMPLE_RATE)

        # Measure error of different offsets
        for start in range(0, len(map_sf0)-1000, 200):
            try:
                offset, err, errors = find_offset(map_sf0[start:start+1000], map_sf1[start:start+1000], potential_offsets)
                offsets.append(offset)
                plt.plot(times, errors)
            except ValueError:
                pass

            try:
                offset, err, errors = find_offset(map_cf0[start:start+1000], map_cf1[start:start+1000], potential_offsets)
                offsets.append(offset)
                plt.plot(times, errors)
            except ValueError:
                pass

        offsets = np.array(offsets)
        if len(offsets):

            uniques, counts = np.unique(offsets, return_counts=True)

            best_offset = uniques[np.argmax(counts)]
            offset_ms = int(times[best_offset])
        else:
            offset_ms = 0
        print(f"Offset: {offset_ms}")

        # Plot the output
        plt.axvline(x=offset_ms, color='r', linestyle='--')
        plt.title(f'Alignment: {rendition_key}')
        plt.ylabel('difference')
        plt.xlabel(f'milliseconds behind: {reference_key}')

        x_bounds = plt.xlim()
        plt.annotate(text=f'{offset_ms} ms', 
                     xy =(((offset_ms-x_bounds[0])/(x_bounds[1]-x_bounds[0])),0.99), 
                     xycoords='axes fraction', verticalalignment='top', 
                     horizontalalignment='left' , rotation = 270)

        # Upload the plot
        with tempfile.TemporaryDirectory() as tmpdir:
            key = f'{choir_id}+{song_id}+{part_id}-alignment.png'
            file_path = str(Path(tmpdir, key))
            plt.savefig(file_path)
            cos.upload_file(file_path, debug_bucket, key)

    except Exception as e:
        raise
        print("Could not sync audio", e)
        offset_ms = 0

    # If the offset is too great, assume we failed and fallback to zero
    if offset_ms > 700 or offset_ms < -700:
        print(f"Offset was too great ({offset}) so falling back to zero")
        offset_ms = 0

    # Save the offest to the API so we can trim on it later
    try:
        api_url = args['CHOIRLESS_API_URL']
        api_key = args['CHOIRLESS_API_KEY']

        params = {'apikey': api_key}
        payload = {'choirId': choir_id,
                   'songId': song_id,
                   'partId': part_id,
                   'offset': offset_ms}
        resp = requests.post(urljoin(api_url, 'choir/songpart'),
                             params=params,
                             json=payload)
        resp.raise_for_status()

    except Exception as e:
        print(f"Could not store offset in API: choidId {choir_id} songId {song_id} partId {part_id} offset {offset_ms}")

    ret = {"offset":  offset_ms,
           "key": rendition_key,
           "rendition_key": rendition_key,
           "reference_key": reference_key,
    }
    
    return ret


def ms_to_frames(ms, sr):
    return ((ms / 1000) * sr) / 512


def frames_to_ms(frames, sr):
    return ((frames * 512) / sr) * 1000


def calc_prominence_threshold(signal):
    peaks, properties = find_peaks(signal, prominence=0)
    if len(peaks) == 0:
        return 0
    prominence = np.quantile(properties["prominences"], 0.9)
    return prominence


def calc_get_peaks(signal, prominence):
    peaks, _ = find_peaks(signal, prominence=prominence)
    return peaks


def map_peaks(peaks, length):
    data = np.zeros(length, dtype=np.float32)
    np.put(data, peaks.astype(np.int), 1.0)

    for i in range(1, len(data)):
        data[i] = max(data[i], data[i-1] * 0.8)

    for i in range(len(data) - 2, 0, -1):
        data[i] = max(data[i], data[i+1] * 0.8)

    return data


# Find the best offset
def find_offset(x0, x1, offsets):

    error0 = measure_error(x0, x1, 0)
    errors = np.array([measure_error(x0, x1, int(-offset)) for offset in offsets])

    if all(e == errors[0] for e in errors):
        raise ValueError("Errors flat")

    minidx = np.argmin(errors)
    best_offset = minidx
    best_error = errors[minidx]

    if error0 <= best_error:
        return 0, error0, errors
    else:
        return best_offset, best_error, errors

# function to measure two waveforms with one offset by a certian amount
def measure_error(x0, x1, offset):
    max_len = min(len(x0), len(x1))

    # calculate the mean squared error of the two signals
    diff = x0[:max_len] - np.roll(x1[:max_len], offset)
    err = np.sum(diff**2) / len(diff)
    return err
