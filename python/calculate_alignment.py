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

from pykalman import UnscentedKalmanFilter as KalmanFilter

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


import requests

from choirless_lib import create_cos_client, mqtt_status

SAMPLE_RATE = 44100
HOP_LENGTH_SECONDS = 0.01

PARAMS = {'cf_weight': 0.5, 'chroma_weight': 0.8, 'sf_weight': 0.6}

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


    # Set up a chart to plot sync process
    fig = plt.figure(figsize=(20, 6))
    ax = fig.add_subplot(1, 1, 1)

    offset_ms = calc_offset(s0, sr0, s1, sr1,
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
        print(f"Could not store offset in API: choidId {choir_id} songId {song_id} partId {part_id} offset {offset_ms}", e)

    ret = {"offset":  offset_ms,
           "key": rendition_key,
           "rendition_key": rendition_key,
           "reference_key": reference_key,
    }

    return ret


def ms_to_frames(ms, sr, hop_length):
    return ((ms / 1000) * sr) / hop_length


def frames_to_ms(frames, sr, hop_length):
    return ((frames * hop_length) / sr) * 1000


def calc_prominences(signal):
    _, properties = find_peaks(signal, prominence=0)
    return properties.get("prominences", [])


def calc_prominence_threshold(signal, q=0.9):
    prominences = calc_prominences(signal)
    if len(prominences) == 0:
        return 0
    prominence = np.quantile(prominences, q)
    return prominence


def calc_peaks(signal, prominence=0, height=0):
    peaks, properties = find_peaks(signal, prominence=prominence, height=height)
    return peaks, properties.get('peak_heights', np.array([]))


def map_peaks(peaks, length, decay=0.8):
    data = np.zeros(length, dtype=np.float32)
    np.put(data, peaks.astype(np.int), 1.0)

    for i in range(1, len(data)):
        data[i] = max(data[i], data[i-1] * decay)

    for i in range(len(data) - 2, 0, -1):
        data[i] = max(data[i], data[i+1] * decay)

    return data

def calc_errors(x0, x1, times, hop_length, exact=False):
    if exact:
        errors = np.array([measure_error_chroma(x0, x1, -int(ms_to_frames(t, SAMPLE_RATE, hop_length))) for t in times])
    else:
        errors = np.array([measure_error(x0, x1, -int(ms_to_frames(t, SAMPLE_RATE, hop_length))) for t in times])
    return errors


# function to measure two waveforms with one offset by a certian amount
def measure_error(x0, x1, offset):
    max_len = min(len(x0), len(x1))

    # calculate the mean squared error of the two signals
    diff = x0[:max_len] - np.roll(x1[:max_len], offset)
    if len(diff) > 0:
        return np.sum(diff**2) / len(diff)
    return 0

# function to measure two waveforms with one offset by a certian amount
def measure_error_chroma(x0, x1, offset):
    x0t = x0.transpose()
    x1t = x1.transpose()
    max_len = min(len(x0t), len(x1t))

    x0a = np.argmax(x0t, axis=1) / 12
    x1a = np.argmax(x1t, axis=1) / 12

    # calculate the mean squared error of the two signals
    diff = np.where(x0a[:max_len] == np.roll(x1a[:max_len], offset, 0), 0, 1)
    if len(diff) > 0:
        return np.nanmean(diff)
    return 0


def gen_features(s, sr, n_fft_seconds=0.04, hop_length_seconds=0.01):
    if not hasattr(gen_features, '__cache'):
        gen_features.__cache = {}
    cache = gen_features.__cache

    key = (hash(s.tobytes()), n_fft_seconds, hop_length_seconds)
    if key in cache:
        return cache[key]

    sound = Waveform(signal=s, sample_rate=sr)
    sf = sound.spectral_flux(n_fft_seconds, hop_length_seconds)[0]
    cf = sound.crest_factor(n_fft_seconds, hop_length_seconds)[0]
    #chroma = np.argmax(sound.chroma_cqt(hop_length_seconds), axis=0) / 12
    chroma = sound.chroma_cens(hop_length_seconds)

    cache[key] = (sf, cf, chroma)

    return sf, cf, chroma

def gen_peak_map(signal):
    if not hasattr(gen_peak_map, '__cache'):
        gen_peak_map.__cache = {}
    cache = gen_peak_map.__cache

    key = hash(signal.tobytes())
    if key in cache:
        return cache[key]

    peaks, peak_heights = calc_peaks(signal)
    std = np.std(peak_heights)
    peaks = peaks[peak_heights > std]
    peak_map = map_peaks(peaks, len(signal))

    cache[key] = peak_map

    return peak_map


def calc_offset(s0, sr0, s1, sr1,
                ax=None,
                start_seconds=None,
                length_seconds=None,
                chroma_weight=1.0, sf_weight=1.0, cf_weight=1.0):

    try:

        # Acutally calc the offset
        lookahead_ms = 100
        lookbehind_ms = 600

        hop_lengths = [256, 512, 1024, 2048]

        times = np.arange(-lookahead_ms, lookbehind_ms, 10)

        all_chroma_errors = []
        all_sf_errors = []
        all_cf_errors = []

        for hop_length in hop_lengths:

            hop_length_seconds = hop_length / SAMPLE_RATE 

            sf0, cf0, chroma_s0 = gen_features(s0, sr0, hop_length_seconds=hop_length_seconds)
            sf1, cf1, chroma_s1 = gen_features(s1, sr1, hop_length_seconds=hop_length_seconds)

            if start_seconds is not None:
                start_frames = int(start_seconds // hop_length_seconds)
                sf0 = sf0.copy()[start_frames:]
                sf1 = sf1.copy()[start_frames:]
                cf0 = cf0.copy()[start_frames:]
                cf1 = cf1.copy()[start_frames:]
                chroma_s0 = chroma_s0.copy()[start_frames:]
                chroma_s1 = chroma_s1.copy()[start_frames:]

            if length_seconds is not None:
                length_frames = int(length_seconds // hop_length_seconds)
                sf0 = sf0.copy()[:length_frames]
                sf1 = sf1.copy()[:length_frames]
                cf0 = cf0.copy()[:length_frames]
                cf1 = cf1.copy()[:length_frames]
                chroma_s0 = chroma_s0.copy()[:length_frames]
                chroma_s1 = chroma_s1.copy()[:length_frames]

            map_sf0 = gen_peak_map(sf0)
            map_sf1 = gen_peak_map(sf1)
            map_cf0 = gen_peak_map(cf0)
            map_cf1 = gen_peak_map(cf1)

            chroma_errors = calc_errors(chroma_s0,
                                        chroma_s1,
                                        times,
                                        hop_length,
                                        exact=True)
            std = np.std(chroma_errors)
            std = 1 if std == 0 else std
            chroma_errors = (chroma_errors - np.mean(chroma_errors)) / std
            chroma_errors *= chroma_weight
            if np.isfinite(chroma_errors).all():
                all_chroma_errors.append(chroma_errors)

            sf_errors = calc_errors(sf0,
                                    sf1,
                                    times,
                                    hop_length)
            std = np.std(sf_errors)
            std = 1 if std == 0 else std
            sf_errors = (sf_errors - np.mean(sf_errors)) / std
            sf_errors *= sf_weight
            if np.isfinite(sf_errors).all():
                all_sf_errors.append(sf_errors)

            cf_errors = calc_errors(cf0,
                                    cf1,
                                    times,
                                    hop_length)
            std = np.std(cf_errors)
            std = 1 if std == 0 else std
            cf_errors = (cf_errors - np.mean(cf_errors)) / std
            cf_errors *= cf_weight
            if np.isfinite(cf_errors).all():
                all_cf_errors.append(cf_errors)

        # Normalise
        all_chroma_errors = np.stack(all_chroma_errors)
        kf = KalmanFilter(initial_state_mean=0, n_dim_obs=all_chroma_errors.shape[0])
        median_chroma_errors = kf.smooth(all_chroma_errors.transpose())[0].flatten()

        all_sf_errors = np.stack(all_sf_errors)
        kf = KalmanFilter(initial_state_mean=0, n_dim_obs=all_sf_errors.shape[0])
        median_sf_errors = kf.smooth(all_sf_errors.transpose())[0].flatten()

        all_cf_errors = np.stack(all_cf_errors)
        kf = KalmanFilter(initial_state_mean=0, n_dim_obs=all_cf_errors.shape[0])
        median_cf_errors = kf.smooth(all_cf_errors.transpose())[0].flatten()
        
        total = np.sum(np.stack([median_sf_errors, median_cf_errors, median_chroma_errors]), axis=0)

        peaks, _ = calc_peaks(-total, height=1.0, prominence=1.0)

        if len(peaks) > 0:
            offsets = times[peaks]
            offset_ms = offsets[0]
        else:
            offsets = []
            offset_ms = 0
            
        if ax:
            for chroma_errors in all_chroma_errors:
                ax.plot(times, chroma_errors, color='r', alpha=0.3)
            ax.plot(times, median_chroma_errors, label='Chroma', color='r')

            for sf_errors in all_sf_errors:
                ax.plot(times, sf_errors, color='g', alpha=0.3)
            ax.plot(times, median_sf_errors, label='Spectral Flux', color='g')

            for cf_errors in all_cf_errors:
                ax.plot(times, cf_errors, color='b', alpha=0.3)
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

    return int(offset_ms)


