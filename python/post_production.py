import asyncio
import aiohttp
import json
import os
import numpy as np
from pathlib import Path
import tempfile
from functools import partial
import time
import hashlib

import ffmpeg

from choirless_lib import mqtt_status, create_signed_url, create_cos_client

@mqtt_status()
def main(args):
    cos = create_cos_client(args)

    if not cos:
        raise ValueError(f"could not create COS instance")

    notification = args.get('notification', {})
    key = args.get('key', notification.get('object_name', ''))

    # parse the key
    choir_id, song_id, def_id = Path(key).stem.split('-')[0].split('+')

    src_bucket = args['preprod_bucket']
    dst_bucket = args['preview_bucket']
    misc_bucket = args['misc_bucket']
    definition_bucket = args['definition_bucket']

    # Download the definition file for this job
    definition_key = f'{choir_id}+{song_id}+{def_id}.json'
    definition_object = cos.get_object(
        Bucket=definition_bucket,
        Key=definition_key,
    )
    definition = json.load(definition_object['Body'])
    output_spec = definition['output']

    geo = args['geo']
    host = args.get('endpoint', args['ENDPOINT'])
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
    
    get_misc_url = partial(create_signed_url,
                            host,
                            'GET',
                            cos_api_key,
                            cos_api_secret,
                            geo,
                            misc_bucket)

    ###
    ### Combine video and audio
    ###
    
    # Create a temp dir for our files to use
    with tempfile.TemporaryDirectory() as tmpdir:

        stream = ffmpeg.input(get_input_url(key),
                              seekable=0,
                              thread_queue_size=64)

        audio = stream.audio
        video = stream.video

        # Pad the video to final size, place video in center
        output_width, output_height = output_spec['size']
        video = video.filter('pad',
                             x=-1,
                             y=-1,
                             width=output_width,
                             height=output_height)
        
        # Overlay the watermark if present
        watermark_file = output_spec.get('watermark')
        if watermark_file:
            watermark_url = get_misc_url(watermark_file)
            watermark = ffmpeg.input(watermark_url,
                                     seekable=0)
            video = video.overlay(watermark,
                                  x='W-w-20',
                                  y='H-h-20')
             
        print("Doing first pass loudnorm")
        stream = ffmpeg.input(get_input_url(key),
                              seekable=0)
        audio = stream.audio
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

        # Second pass, apply normalisation
        print("Doing second pass loudnorm")
        stream = ffmpeg.input(get_input_url(key),
                              seekable=0)

        audio = audio.filter('loudnorm',
                             i=-14,
                             offset=target_offset,
                             measured_i=input_i,
                             measured_lra=input_lra,
                             measured_tp=input_tp,
                             measured_thresh=input_thresh,
                             linear=True,
                             print_format='summary')

        # Add in audio compression
        audio = audio.filter('acompressor')
        
        # Add reverb in if present
        reverb_type = output_spec.get('reverb_type')
        if reverb_type:
            reverb_url = get_misc_url(f'{reverb_type}.wav')
            reverb_pct = float(output_spec.get('reverb', 0.1))
            if reverb_pct > 0:
                reverb_part = ffmpeg.input(reverb_url,
                                           seekable=0)
                split_audio = audio.filter_multi_output('asplit')
                reverb = ffmpeg.filter([split_audio[1], reverb_part],
                                       'afir',
                                       dry=10, wet=10)
                audio = ffmpeg.filter([split_audio[0], reverb],
                                      'amix',
                                      dropout_transition=180,
                                      inputs=2,
                                      weights=f'{1-reverb_pct} {reverb_pct}')

        # Output
        output_key = f'{choir_id}+{song_id}+{def_id}-final.mp4'
        output_path = str(Path(tmpdir, output_key))

        kwargs = {}
        if 'duration' in args:
            kwargs['t'] = int(args['duration'])

        if 'loglevel' in args:
            kwargs['v'] = args['loglevel']

        pipeline = ffmpeg.output(audio,
                                 video,
                                 output_path,
                                 pix_fmt='yuv420p',
                                 vcodec='libx264',
                                 preset='veryfast',
                                 movflags='+faststart',
                                 **kwargs
        ) 
        cmd = pipeline.compile()
        print("ffmpeg command to run: ", cmd)
        t1 = time.time()
        pipeline.run()
        t2 = time.time()

        # Upload the final file
        cos.upload_file(output_path, dst_bucket, output_key)
        
        ret = {'dst_key': output_key,
               'def_id': def_id,
               'render_time': int(t2-t1),
               'status': 'ok'}

        return ret



