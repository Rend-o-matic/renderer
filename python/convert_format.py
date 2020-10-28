import time
from functools import partial
from pathlib import Path
import json
import math
import re

import ffmpeg

from choirless_lib import mqtt_status, create_signed_url

SAMPLE_RATE = 44100


@mqtt_status()
def main(args):

    notification = args.get('notification', {})
    key = args.get('key', notification.get('object_name', ''))
    choir_id, song_id, part_id = Path(key).stem.split('.')[0].split('+')

    src_bucket = args['raw_bucket']
    dst_bucket = args['converted_bucket']
    
    geo = args['geo']
    host = args.get('endpoint', args.get('ENDPOINT'))
    cos_hmac_keys = args['__bx_creds']['cloud-object-storage']['cos_hmac_keys']
    cos_api_key = cos_hmac_keys['access_key_id']
    cos_api_secret = cos_hmac_keys['secret_access_key']
    
    get_input_url = partial(create_signed_url,
                            host,
                            'GET',
                            cos_api_key,
                            cos_api_secret,
                            geo,
                            src_bucket)
    
    get_output_url = partial(create_signed_url,
                             host,
                             'PUT',
                             cos_api_key,
                             cos_api_secret,
                             geo,
                             dst_bucket)

    output_key = str(Path(key).with_suffix('.nut'))

    kwargs = {}

    ## Probe pass
    # First probe the file to see if we have audio and/or video streams
    try:
        output = ffmpeg.probe(get_input_url(key))
    except Exception as e:
        print("ffprobe error", e.stderr)
        return({'error': str(e)})

    stream_types = set([ s['codec_type'] for s in output['streams'] ])
    audio_present = 'audio' in stream_types
    video_present = 'video' in stream_types

    print("Audio present:" , audio_present)
    print("Video present:", video_present)

    if not (audio_present or video_present):
        return {"error": "no streams!"}

    ## Two pass loudness normalisation
    # First pass, get details
    if audio_present:
        print("Doing first pass")
        stream = ffmpeg.input(get_input_url(key),
                              seekable=0)
        audio = stream.audio
        audio = audio.filter('volumedetect')
        pipeline = ffmpeg.output(audio,
                                 "-",
                                 format='null')

        cmd = pipeline.compile()
        print("ffmpeg command to run: ", cmd)

        stdout, stderr = pipeline.run(capture_stdout=True,
                                      capture_stderr=True)
        output = stdout + stderr
        output_lines = [line.strip() for line in output.decode().split('\n')]

        mute = False

        # Volume detect
        vol_threshold = int(args.get('vol_threshold', 22))
        vol_pct = float(args.get('vol_pct', 0.05))

        total_samples = 0
        high_samples = 0
        max_volume = 0
        hist_re = re.compile(r'histogram_(\d+)db: (\d+)')
        maxvol_re = re.compile(r'max_volume: (-?\d+\.?\d*) dB')
        for line in output_lines:
            # Search for histogram
            mo = hist_re.search(line)
            if mo:
                level, samples = mo.groups()
                total_samples += int(samples)
                if int(level) < vol_threshold:
                    high_samples += int(samples)

            # Search for max volume
            mo = maxvol_re.search(line)
            if mo:
                max_volume = float(mo.groups()[0])

        if high_samples/total_samples < vol_pct:
            print(f"Input volume is so low, we are muting it {high_samples/total_samples:.2f} above {vol_threshold}")
            mute = True

        target_peak = -2
        volume_gain = target_peak - max_volume
        volume_gain = f"{volume_gain:.2f} dB"
            
    # Second pass, apply normalisation
    print("Doing second pass")
    stream = ffmpeg.input(get_input_url(key),
                          seekable=0)

    if video_present:
        video = stream.filter('fps', fps=25, round='up')
        video = video.filter('scale', 640, 480,
                             force_original_aspect_ratio='decrease',
                             force_divisible_by=2)
    else:
        video = ffmpeg.input('color=color=black:size=vga',
                             format='lavfi').video

    if audio_present:
        audio = stream.audio

        # If the normalisation appears to detect no sound then just mute audio
        if mute:
            volume_gain = 0
            
        print("Volume gain to apply:", volume_gain)
        audio = audio.filter('volume',
                             volume_gain)
        audio = audio.filter('aresample', 44100)
    else:
        audio = ffmpeg.input('anullsrc',
                             format='lavfi').audio


    pipeline = ffmpeg.output(audio,
                             video,
                             get_output_url(output_key),
                             format='nut',
                             acodec='pcm_f32le',
                             vcodec='libx264',
                             method='PUT',
                             preset='slow',
                             shortest=None,
                             seekable=0,
                             r=25,
                             ac=1,
                             **kwargs)

    cmd = pipeline.compile()
    print("ffmpeg command to run: ", cmd)
    t1 = time.time()
    pipeline.run()
    t2 = time.time()
    
    ret = {'status': 'ok',
           'render_time': int(t2-t1),
           'src_key': key,
           'dst_key': output_key,
           'choir_id': choir_id,
           'song_id': song_id,
           'part_id': part_id,
           'status': 'converted'
           }

    return ret

