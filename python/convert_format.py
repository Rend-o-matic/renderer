import time
from functools import partial
from pathlib import Path
import json
import math

import ffmpeg

from choirless_lib import mqtt_status, create_signed_url

SAMPLE_RATE = 44100


@mqtt_status()
def main(args):

    notification = args.get('notification', {})
    key = args.get('key', notification.get('object_name', ''))

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
        audio = audio.filter('silenceremove',
                             stop_periods=-1,
                             stop_duration=1,
                             stop_threshold='-60dB')
        audio = audio.filter('loudnorm',
                             i=-14,
                             dual_mono=True,
                             print_format='json')
        pipeline = ffmpeg.output(audio,
                                 "-",
                                 format='null')

        cmd = pipeline.compile()
        print("ffmpeg command to run: ", cmd)

        stdout, stderr = pipeline.run(capture_stdout=True,
                                      capture_stderr=True)
        output = stdout + stderr
        output_lines = [line.strip() for line in output.decode().split('\n')]
        loudnorm_start = False
        loudnorm_end = False

        for index, line in enumerate(output_lines):
            if line.startswith('[Parsed_loudnorm'):
                loudnorm_start = index + 1
                continue
            if loudnorm_start and line.startswith('}'):
                loudnorm_end = index + 1
                break

        if not (loudnorm_start and loudnorm_end):
            raise Exception("Could not parse loudnorm stats; no loudnorm-related output found")

        try:
            loudnorm_stats = json.loads('\n'.join(output_lines[loudnorm_start:loudnorm_end]))
        except Exception as e:
            raise Exception("Could not parse loudnorm stats; wrong JSON format in string: {e}")

        print("json stats", loudnorm_stats)

        target_offset = float(loudnorm_stats['target_offset'])
        input_i=float(loudnorm_stats['input_i'])
        input_lra=float(loudnorm_stats['input_lra'])
        input_tp=float(loudnorm_stats['input_tp'])
        input_thresh=float(loudnorm_stats['input_thresh'])

        # if the input volume level is so low, we might as well mute it
        if input_i < -50:
            print("Input loudness is so low, we are muting it", input_i)
            audio_present = False

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
        if input_i == -math.inf or input_lra == 0 or target_offset == math.inf:
            audio = audio.filter('volume', 0)
        else:
            audio = audio.filter('loudnorm',
                                 i=-14,
                                 offset=target_offset,
                                 measured_i=input_i,
                                 measured_lra=input_lra,
                                 measured_tp=input_tp,
                                 measured_thresh=input_thresh,
                                 linear=True,
                                 dual_mono=True,
                                 print_format='summary')
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
           'dst_key': output_key
           }

    return ret

