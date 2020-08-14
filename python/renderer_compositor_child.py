import json
import math
import os
import numpy as np
from functools import partial
import time
from pathlib import Path
import ffmpeg

from choirless_lib import mqtt_status, create_signed_url, create_cos_client

helper = lambda x: {'tag': f"{x['compositor']}-{x['row_num']}"}
@mqtt_status(helper)
def main(args):

    args['endpoint'] = args.get('endpoint', args.get('ENDPOINT'))
    cos = create_cos_client(args)

    if not cos:
        raise ValueError(f"could not create COS instance")

    notification = args.get('notification', {})
    definition_key = args.get('definition_key', notification.get('object_name', ''))

    # infer choir, song, and definition id from filename
    choir_id, song_id, def_id = Path(definition_key).stem.split('+', 3)

    definition_bucket = args['definition_bucket']
    src_bucket = args['trimmed_bucket']
    dst_bucket = args['final_parts_bucket']

    # the compositor to run (audio / video)
    compositor = args['compositor']
    
    # the row number we are processing
    row_num = int(args['row_num'])
    rows_hash = args['rows_hash']

    # run id used to group all our files together
    run_id = args['run_id']
    
    print(f"We are the child {compositor} process, run id: {run_id} row: {row_num}")
    
    # Download the definition file for this job
    definition_object = cos.get_object(
        Bucket=definition_bucket,
        Key=definition_key,
    )
    definition = json.load(definition_object['Body'])
    
    output_spec = definition['output']
    input_specs = definition['inputs']

    # Calculate number of rows
    rows = set()
    for spec in input_specs:
        x, y = spec['position']
        rows.add(y)
    rows = sorted(rows)
    num_rows = len(rows)

    # The output key
    output_key = f"{choir_id}+{song_id}+{def_id}+{run_id}+{compositor}-{row_num}-{rows_hash}.nut"
    
    # Create partial functions to get signed urls for input / output
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

    video_pipeline = gen_video_pipeline(choir_id, song_id, def_id, run_id,
                                        input_specs, output_spec,
                                        output_key,
                                        row_num, rows,
                                        get_input_url, get_output_url,
                                        args)

    audio_pipeline = gen_audio_pipeline(choir_id, song_id, def_id, run_id,
                                        input_specs, output_spec,
                                        output_key,
                                        row_num, rows,
                                        get_input_url, get_output_url,
                                        args)

    kwargs = {}
    if 'duration' in args:
        kwargs['t'] = int(args['duration'])

    output_url = get_output_url(output_key)
    
    pipeline = ffmpeg.output(video_pipeline,
                             audio_pipeline,
                             output_url,
                             format='nut',
                             pix_fmt='yuv420p',
                             acodec='pcm_s16le',
                             vcodec='mpeg2video',
                             method='PUT',
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

    ret = {"status": "ok",
           "definition_key": definition_key,
           "dst_key": output_key,
           "render_time": int(t2-t1),
           "row_num": row_num,
           "run_id": run_id,
           "rows_hash": rows_hash,
           }

    return ret


def specs_for_row(specs, row):
    for spec in specs:
        x, y = spec['position']
        if y == row:
            yield spec

def calc_bounding_box(specs):
    top = np.inf
    bottom = -np.inf
    for spec in specs:
        x, y = spec['position']
        width, height = spec['size']
        if y < top:
            top = y
        if (y + height) > bottom:
            bottom = y + height

    return top, bottom            


def gen_video_pipeline(choir_id, song_id, def_id, run_id,
                       input_specs, output_spec,
                       output_key,
                       row_num, rows,
                       get_input_url, get_output_url,
                       args):
    
    # Calculate all the spacing and padding needed
    row_input_specs = tuple(specs_for_row(input_specs, row_num))
    total_top, total_bottom = calc_bounding_box(input_specs)
    top, bottom = calc_bounding_box(row_input_specs)
    margin = 10

    total_output_width, total_output_height = output_spec['size']
    output_width = total_output_width
    output_height = bottom - top + margin

    # by default rows are at top
    row_y = 0
    
    if top == total_top:
        # first row, pad it further
        output_height += top
        row_y = top
    if bottom == total_bottom:
        # last row, pad it further
        output_height += (total_output_height - total_bottom)

    # Main combination process
    video_inputs = []
    coords = []

    for spec in row_input_specs:
        # Get the part spec and input
        part_id = spec['part_id']
        x, y = spec['position']
        width, height = spec['size']
        part_key = f"{choir_id}+{song_id}+{part_id}.nut"
        part_url = get_input_url(part_key)

        # main stream input
        stream = ffmpeg.input(part_url,
                              seekable=0,
                              thread_queue_size=64)

        # video
        video = stream.video
        video = video.filter('scale', width, height)
        video_inputs.append(video)
        coords.append((x, row_y))

    layout = '|'.join([ f"{x}_{row_y}" for x, row_y in coords ])
        
    if len(video_inputs) > 1:
        video_pipeline = ffmpeg.filter(video_inputs,
                                       'xstack',
                                       inputs=len(video_inputs),
                                       fill='black',
                                       layout=layout)
        video_pipeline = video_pipeline.filter('pad',
                                               output_width,
                                               output_height)
    else:
        x, y = coords[0]
        video_pipeline = video_inputs[0]
        video_pipeline = video_pipeline.filter('pad',
                                               output_width,
                                               output_height,
                                               x,
                                               y)

    return video_pipeline


def gen_audio_pipeline(choir_id, song_id, def_id, run_id,
                       input_specs, output_spec,
                       output_key,
                       row_num, rows,
                       get_input_url, get_output_url,
                       args):
    
    # Calculate the max row length, needed for volume compensation
    # on uneven rows
    max_row_len = 0
    for r in rows:
        l = len(tuple(specs_for_row(input_specs, r)))
        if l > max_row_len:
            max_row_len = l
            
    # Get the row input specs
    row_input_specs = tuple(specs_for_row(input_specs, row_num))
    
    # Main combination process
    audio_inputs = []
    layouts = []

    for spec in row_input_specs:
        # Get the part spec and input
        part_id = spec['part_id']
        part_key = f"{choir_id}+{song_id}+{part_id}.nut"
        part_url = get_input_url(part_key)

        # main stream input
        stream = ffmpeg.input(part_url,
                              seekable=0,
                              thread_queue_size=64)

        # audio
        audio = stream.audio
        panning = float(spec.get('panning', 0))
        volume = float(spec.get('volume', 1))
        volume *= len(row_input_specs) / float(max_row_len)
        audio = audio.filter('volume',
                             volume=volume)
        audio = audio.filter('stereotools',
                             mpan=panning)
        audio_inputs.append(audio)
        
    audio_pipeline = ffmpeg.filter(audio_inputs, 'amix', inputs=len(audio_inputs))

    return audio_pipeline
