import io
import json
import os
import librosa
import numpy as np
import re
import tempfile
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin
from scipy.signal import find_peaks
from surfboard.sound import Waveform

from sklearn.cluster import MeanShift

from pykalman import UnscentedKalmanFilter as KalmanFilter

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


import requests

from choirless_lib import create_cos_client, mqtt_status

SAMPLE_RATE = 44100
HOP_LENGTH_SECONDS = 0.01

PARAMS = {'cf_weight': 0.4, 'chroma_weight': 0.9, 'decay': 0.65, 'q': 0.9, 'sf_weight': 0.7}

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

    # Calculate the features
    sf0 = sound0.spectral_flux()[0]
    cf0 = sound0.crest_factor()[0]

    sf1 = sound1.spectral_flux()[0]
    cf1 = sound1.crest_factor()[0]

    chroma_s0 = np.argmax(sound0.chroma_cqt(), axis=0) / 12
    chroma_s1 = np.argmax(sound1.chroma_cqt(), axis=0) / 12

    features = {'s0': s0,
                's1': s1,
                'sf0': sf0,
                'sf1': sf1,
                'cf0': cf0,
                'cf1': cf1,
                'chroma_s0': chroma_s0,
                'chroma_s1': chroma_s1,
                }

    # Set up a chart to plot sync process
    fig = plt.figure(figsize=(20, 6))
    ax = fig.add_subplot(1, 1, 1)

    offset_ms = calc_offset(features,
                            ax=ax,
                            **PARAMS)

    # Plot the output
    plt.title(f'Alignment: {rendition_key}')
    plt.ylabel('difference')
    plt.xlabel(f'milliseconds behind: {reference_key}')

    x_bounds = plt.xlim()
    plt.annotate(text=f'{offset_ms:.0f} ms',
                 xy =(((offset_ms-x_bounds[0])/(x_bounds[1]-x_bounds[0])),0.99),
                 xycoords='axes fraction', verticalalignment='top',
                 horizontalalignment='left' , rotation = 270)

    # Upload the plot
    with tempfile.TemporaryDirectory() as tmpdir:
        key = f'{choir_id}+{song_id}+{part_id}-alignment.png'
        file_path = str(Path(tmpdir, key))
        plt.savefig(file_path)
        cos.upload_file(file_path, debug_bucket, key)

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


def calc_offset(features, ax=None, q=0.8, decay=0.8, chroma_weight=1.0, sf_weight=1.0, cf_weight=1.0):

    sf0 = features['sf0']
    cf0 = features['cf0']
    sf1 = features['sf1']
    cf1 = features['cf1']
    chroma_s0 = features['chroma_s0']
    chroma_s1 = features['chroma_s1']

    try:
        prom_sf0 = calc_prominence_threshold(sf0, q)
        prom_sf1 = calc_prominence_threshold(sf1, q)
        prom_cf0 = calc_prominence_threshold(cf0, q)
        prom_cf1 = calc_prominence_threshold(cf1, q)

        peaks_sf0, _, _ = calc_peaks(sf0, prom_sf0)
        peaks_sf1, _, _ = calc_peaks(sf1, prom_sf1)
        peaks_cf0, _, _ = calc_peaks(cf0, prom_cf0)
        peaks_cf1, _, _ = calc_peaks(cf1, prom_cf1)

        map_sf0 = map_peaks(peaks_sf0, len(sf0), decay)
        map_sf1 = map_peaks(peaks_sf1, len(sf1), decay)
        map_cf0 = map_peaks(peaks_cf0, len(cf0), decay)
        map_cf1 = map_peaks(peaks_cf1, len(cf1), decay)

        # Acutally calc the offset
        offsets = []
        lookahead_ms = 100
        lookbehind_ms = 600

        window_length = int(10 / HOP_LENGTH_SECONDS)
        window_step = int(window_length / 5)

        potential_offsets = np.arange(int(ms_to_frames(-lookahead_ms, SAMPLE_RATE)),
                                      int(ms_to_frames(lookbehind_ms, SAMPLE_RATE)))

        # Add 1 here as frame offset is 1/4 of the fft window and we want to be in middle on average
        times = frames_to_ms(potential_offsets + 1, SAMPLE_RATE)

        num_segments = 5
        # Calculate errors
        seg_len = len(chroma_s0) // num_segments
        all_chroma_errors = []
        all_sf_errors = []
        all_cf_errors = []

        for i in range(num_segments):
            start = i*seg_len
            end = (i+1)*seg_len

            chroma_errors = calc_errors(chroma_s0[start:end],
                                        chroma_s1[start:end],
                                        potential_offsets,
                                        exact=True)
            std = np.std(chroma_errors)
            std = 1 if std == 0 else std
            chroma_errors = (chroma_errors - np.mean(chroma_errors)) / std
            chroma_errors *= chroma_weight
            all_chroma_errors.append(chroma_errors)

            sf_errors = calc_errors(sf0[start:end],
                                    sf1[start:end],
                                    potential_offsets)
            std = np.std(sf_errors)
            std = 1 if std == 0 else std
            sf_errors = (sf_errors - np.mean(sf_errors)) / std
            sf_errors *= sf_weight
            all_sf_errors.append(sf_errors)

            cf_errors = calc_errors(cf0[start:end],
                                    cf1[start:end],
                                    potential_offsets)
            std = np.std(cf_errors)
            std = 1 if std == 0 else std
            cf_errors = (cf_errors - np.mean(cf_errors)) / std
            cf_errors *= cf_weight
            all_cf_errors.append(cf_errors)

        # Normalise
        all_chroma_errors = np.stack(all_chroma_errors)
        kf = KalmanFilter(initial_state_mean=0, n_dim_obs=5)
        median_chroma_errors = kf.smooth(all_chroma_errors.transpose())[0].flatten()

        all_sf_errors = np.stack(all_sf_errors)
        kf = KalmanFilter(initial_state_mean=0, n_dim_obs=5)
        median_sf_errors = kf.smooth(all_sf_errors.transpose())[0].flatten()

        all_cf_errors = np.stack(all_cf_errors)
        kf = KalmanFilter(initial_state_mean=0, n_dim_obs=5)
        median_cf_errors = kf.smooth(all_cf_errors.transpose())[0].flatten()
        
        total = np.sum(np.stack([median_sf_errors, median_cf_errors, median_chroma_errors]), axis=0)

        peaks, _ = find_peaks(-total, height=1.0)

        if len(peaks) > 0:
            offsets = times[peaks]
            offset_ms = offsets[0]
        else:
            offsets = []
            offset_ms = 0
            
        if ax:
            for chroma_errors in all_chroma_errors:
                ax.plot(times, chroma_errors, color='r', alpha=0.1)
            ax.plot(times, median_chroma_errors, label='Chroma', color='r')

            for sf_errors in all_sf_errors:
                ax.plot(times, sf_errors, color='g', alpha=0.1)
            ax.plot(times, median_sf_errors, label='Spectral Flux', color='g')

            for cf_errors in all_cf_errors:
                ax.plot(times, cf_errors, color='b', alpha=0.1)
            ax.plot(times, median_cf_errors, label='Crest Factor', color='b')

            plt.plot(times, total, label='Overall', color='k', linewidth=5)

            for offset in offsets:
                alpha = 1 if offset == offset_ms else 0.2
                ax.axvline(x=offset, color='r', alpha=alpha, linestyle='--')
            ax.legend()
                
    except Exception as e:
        raise
        print("Could not sync audio", e)
        offset_ms = 0

    return offset_ms
    

def ms_to_frames(ms, sr):
    return ((ms / 1000) * sr) / 512


def frames_to_ms(frames, sr):
    return ((frames * 512) / sr) * 1000


def calc_prominences(signal):
    _, properties = find_peaks(signal, prominence=0)
    return properties.get("prominences", [])


def calc_prominence_threshold(signal, q=0.9):
    prominences = calc_prominences(signal)
    if len(prominences) == 0:
        return 0
    prominence = np.quantile(prominences, q)
    return prominence


def calc_peaks(signal, prominence=0, height=-np.inf):
    peaks, properties = find_peaks(signal, prominence=prominence, height=height)
    return peaks, \
        properties.get('prominences', np.array([])), \
        properties.get('peak_heights', np.array([]))


def map_peaks(peaks, length, decay=0.8):
    data = np.zeros(length, dtype=np.float32)
    np.put(data, peaks.astype(np.int), 1.0)

    for i in range(1, len(data)):
        data[i] = max(data[i], data[i-1] * decay)

    for i in range(len(data) - 2, 0, -1):
        data[i] = max(data[i], data[i+1] * decay)

    return data


def calc_errors(x0, x1, offsets, exact=False):
    if exact:
        errors = np.array([measure_error_exact(x0, x1, int(-offset)) for offset in offsets])
    else:
        errors = np.array([measure_error(x0, x1, int(-offset)) for offset in offsets])
    return errors


# function to measure two waveforms with one offset by a certian amount
def measure_error(x0, x1, offset):
    max_len = min(len(x0), len(x1))

    # calculate the mean squared error of the two signals
    diff = x0[:max_len] - np.roll(x1[:max_len], offset)
    err = np.sum(diff**2) / len(diff)
    return err

# function to measure two waveforms with one offset by a certian amount
def measure_error_exact(x0, x1, offset):
    max_len = min(len(x0), len(x1))

    # calculate the mean squared error of the two signals
    diff = np.where(x0[:max_len] == np.roll(x1[:max_len], offset), 0, 1)
    err = np.sum(diff) / len(diff)
    return err
