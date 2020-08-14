import time
from functools import partial
from pathlib import Path

import ffmpeg

from choirless_lib import mqtt_status, create_signed_url

SAMPLE_RATE = 44100


@mqtt_status()
def main(args):

    offset = float(args.get('offset')) / 1000
    key = args.get('rendition_key')

    src_bucket = args['converted_bucket']
    dst_bucket = args['trimmed_bucket']
    
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

    output_key = key # named the same

    kwargs = {}

    stream = ffmpeg.input(get_input_url(key),
                          ss=offset)
    pipeline = ffmpeg.output(stream,
                             get_output_url(output_key),
                             vcodec='libx264',
                             acodec='pcm_f32le',
                             format='nut',
                             method='PUT',
                             seekable=0)
    
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
