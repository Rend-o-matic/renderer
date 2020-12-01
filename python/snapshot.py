from pathlib import Path
from functools import partial

from choirless_lib import create_signed_url

import ffmpeg

SAMPLE_RATE = 44100


def main(args):

    notification = args.get('notification', {})
    key = notification.get('object_name', args['key'])
    choir_id, song_id, part_id = Path(key).stem.split('.')[0].split('+')
    bucket = args.get('bucket', notification.get('bucket_name', args['preview_bucket']))
    dst_bucket = args.get('dst_bucket', args['snapshots_bucket'])

    if key.endswith(".jpg"):
        return {}

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
                            bucket)

    get_output_url = partial(create_signed_url,
                             host,
                             'PUT',
                             cos_api_key,
                             cos_api_secret,
                             geo,
                             dst_bucket)

    output_key = str(Path(key).with_suffix('.jpg'))

    stream = ffmpeg.input(get_input_url(key),
                          seekable=0)
    out = ffmpeg.output(stream,
                        get_output_url(output_key),
                        format='singlejpeg',
                        method='PUT',
                        seekable=0,
                        vframes=1)
    stdout, stderr = out.run()

    ret = {"status": "ok",
           "snapshot_key": output_key,
           "choir_id": choir_id,
           "song_id": song_id,
           "part_id": part_id,
           "status": "new"}

    return ret
