import time
from functools import partial
from pathlib import Path

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
    
    stream = ffmpeg.input(get_input_url(key))
    video = stream.filter('fps', fps=25, round='up')
    video = video.filter('scale', 640, -1)
    audio = stream.audio
    audio = audio.filter('loudnorm',
                         i=-14,
                         dual_mono=True,
                         print_format='summary')
    audio = audio.filter('aresample', 44100)
    pipeline = ffmpeg.output(audio,
                             video,
                             get_output_url(output_key),
                             format='nut',
                             acodec='pcm_f32le',
                             vcodec='libx264',
                             method='PUT',
                             preset='slow',
                             seekable=0,
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

