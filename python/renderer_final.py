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

# first step to ensure we have all parts
# then call process()
def main(args):
    cos = create_cos_client(args)

    if not cos:
        raise ValueError(f"could not create COS instance")

    notification = args.get('notification', {})
    key = args.get('key', notification.get('object_name', ''))

    # parse the key
    choir_id, song_id, def_id, run_id, row_num, rows_hash = parse_key(key)

    src_bucket = args['final_parts_bucket']
    dst_bucket = args['preview_bucket']

    ## Check all parts present if, not abort
    key_prefix =  f'{choir_id}+{song_id}+{def_id}+{run_id}'
    contents = cos.list_objects(
        Bucket=src_bucket,
        Prefix=key_prefix
    )
    existing_part_keys = [ x['Key'] for x in contents.get('Contents', []) \
                           if x['Size'] > 0 ]

    video_part_keys = [ x for x in existing_part_keys if '+video-' in x ]
    audio_part_keys = [ x for x in existing_part_keys if '+audio-' in x ]

    # Sort to make sure we are in correct order
    video_part_keys.sort(key=lambda x: int(parse_key(x)[4]))
    audio_part_keys.sort(key=lambda x: int(parse_key(x)[4]))

    # Calc hash of found parts to make sure we have all, if not abort
    if calc_hash_of_keys(video_part_keys) != rows_hash:
        ret = {'status': 'missing video parts'}
        return ret

    if calc_hash_of_keys(audio_part_keys) != rows_hash:
        ret = {'status': 'missing audio parts'}
        return ret

    args['video_part_keys'] = video_part_keys
    args['audio_part_keys'] = audio_part_keys
    return process(args)

@mqtt_status()
def process(args):
    cos = create_cos_client(args)

    if not cos:
        raise ValueError(f"could not create COS instance")

    notification = args.get('notification', {})
    key = args.get('key', notification.get('object_name', ''))

    # parse the key
    choir_id, song_id, def_id, run_id, row_num, rows_hash = parse_key(key)

    src_bucket = args['final_parts_bucket']
    dst_bucket = args['preview_bucket']

    video_part_keys = args['video_part_keys']
    audio_part_keys = args['audio_part_keys']

    geo = args['geo']
    host = args['endpoint']
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
    
    ###
    ### Combine video and audio
    ###
    
    # Create a temp dir for our files to use
    with tempfile.TemporaryDirectory() as tmpdir:
        # video
        if len(video_part_keys) > 1:
            # Multiple video parts
            video_parts = []
            for video_part_key in video_part_keys:
                video_url = get_input_url(video_part_key)
                video_part = ffmpeg.input(video_url,
                                          seekable=0,
                                          thread_queue_size=64)
                video_parts.append(video_part)
            video = ffmpeg.filter(video_parts, 'vstack',
                                  inputs=len(video_parts))
        else:
            # Just a single video part
            video_url = get_input_url(video_part_keys[0])
            video = ffmpeg.input(video_url,
                                 seekable=0,
                                 thread_queue_size=64)
            
        # audio
        if len(audio_part_keys) > 1:
            # Multiple audio parts
            audio_parts = []
            for audio_part_key in audio_part_keys:
                audio_url = get_input_url(audio_part_key)
                audio_part = ffmpeg.input(audio_url,
                                          seekable=0,
                                          thread_queue_size=64)
                audio_parts.append(audio_part)
            audio = ffmpeg.filter(audio_parts,
                                  'amix',
                                  inputs=len(audio_parts))
        else:
            # Just a single audio part
            audio_url = get_input_url(audio_part_keys[0])
            audio = ffmpeg.input(audio_url,
                                 seekable=0,
                                 thread_queue_size=64)
        audio = audio.filter('loudnorm',
                             i=-14)

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
               'run_id': run_id,
               'def_id': def_id,
               'render_time': int(t2-t1),
               'status': 'merged'}

        return ret

def parse_key(key):
    choir_id, song_id, def_id, run_id, section_id = Path(key).stem.split('+')
    renderer, row_num, rows_hash = section_id.split('-')
    return choir_id, song_id, def_id, run_id, row_num, rows_hash

def calc_hash_of_keys(keys):
    rows = [ int(parse_key(x)[4]) for x in keys ]
    return calc_hash_rows(rows)

def calc_hash_rows(rows):
    val = '-'.join([ str(x) for x in sorted(rows) ])
    hash = hashlib.sha1(val.encode('utf-8')).hexdigest()
    return hash[:8]

