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
    
    args['endpoint'] = args.get('endpoint', args.get('ENDPOINT'))
    cos = create_cos_client(args)

    if not cos:
        raise ValueError(f"could not create COS instance")

    notification = args.get('notification', {})
    key = args.get('key', notification.get('object_name', ''))

    # parse the key
    choir_id, song_id, def_id, run_id, row_num, rows_hash = parse_key(key)

    src_bucket = args['final_parts_bucket']

    ## Check all parts present if, not abort
    key_prefix =  f'{choir_id}+{song_id}+{def_id}+{run_id}'
    contents = cos.list_objects(
        Bucket=src_bucket,
        Prefix=key_prefix
    )
    row_keys = [ x['Key'] for x in contents.get('Contents', []) \
                           if x['Size'] > 0 ]

    # Sort to make sure we are in correct order
    row_keys.sort(key=lambda x: int(parse_key(x)[4]))

    # Calc hash of found parts to make sure we have all, if not abort
    if calc_hash_of_keys(row_keys) != rows_hash:
        ret = {'status': 'missing rows'}
        return ret

    args['row_keys'] = row_keys
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
    dst_bucket = args['preprod_bucket']
    misc_bucket = args['misc_bucket']

    # Download the definition file for this job
    definition_bucket = args['definition_bucket']
    definition_key = f'{choir_id}+{song_id}+{def_id}.json'
    definition_object = cos.get_object(
        Bucket=definition_bucket,
        Key=definition_key,
    )
    definition = json.load(definition_object['Body'])
    output_spec = definition['output']

    row_keys = args['row_keys']

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
    
    # video
    if len(row_keys) > 1:
        # Multiple video parts
        video_parts = []
        audio_parts = []
        for row_key in row_keys:
            _, _, _, _, row_num, _ = parse_key(row_key)
            row_url = get_input_url(row_key)
            row_part = ffmpeg.input(row_url,
                                    seekable=0,
                                    thread_queue_size=64)
            if row_num != -1:
                video_parts.append(row_part.video)
            audio_parts.append(row_part.audio)

        video = ffmpeg.filter(video_parts, 'vstack',
                              inputs=len(video_parts))
        audio = ffmpeg.filter(audio_parts,
                              'amix',
                              inputs=len(audio_parts))
    else:
        # Just a single video part
        row_key = row_keys[0]
        _, _, _, _, row_num, _ = parse_key(row_key)
        row_url = get_input_url(row_key)
        row_part = ffmpeg.input(row_url,
                                seekable=0,
                                thread_queue_size=64)
        if row_num != -1:
            video = row_part.video
        else:
            video = None
        audio = row_part.audio

    # Output
    output_key = f'{choir_id}+{song_id}+{def_id}-preprod.nut'
    output_url = get_output_url(output_key)

    kwargs = {}
    if 'duration' in args:
        kwargs['t'] = int(args['duration'])

    if 'loglevel' in args:
        kwargs['v'] = args['loglevel']

    pipeline = ffmpeg.output(audio,
                             video,
                             output_url,
                             format='nut',
                             pix_fmt='yuv420p',
                             acodec='pcm_s16le',
                             vcodec='mpeg2video',
                             method='PUT',
                             r=25,
                             seekable=0,
                             qscale=1,
                             qmin=1,
                             **kwargs
    )

    cmd = pipeline.compile()
    print("ffmpeg command to run: ", cmd)
    t1 = time.time()
    pipeline.run()
    t2 = time.time()

    ret = {'dst_key': output_key,
           'run_id': run_id,
           'def_id': def_id,
           'render_time': int(t2-t1),
           'status': 'merged'}

    return ret

def parse_key(key):
    choir_id, song_id, def_id, run_id, section_id = Path(key).stem.split('+')
    row_num, rows_hash = section_id.split('@')
    return choir_id, song_id, def_id, run_id, int(row_num), rows_hash

def calc_hash_of_keys(keys):
    rows = [ int(parse_key(x)[4]) for x in keys ]
    return calc_hash_rows(rows)

def calc_hash_rows(rows):
    val = '-'.join([ str(x) for x in sorted(rows) ])
    hash = hashlib.sha1(val.encode('utf-8')).hexdigest()
    return hash[:8]

