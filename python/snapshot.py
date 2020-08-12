import io
import json
import os
import librosa
import numpy as np
import tempfile
from pathlib import Path

from choirless_lib import create_cos_client

import ffmpeg

SAMPLE_RATE = 44100


def main(args):

    cos = create_cos_client(args)

    if not cos:
        raise ValueError(f"could not create COS instance")

    notification = args.get('notification', {})
    key = args.get('key', notification.get('object_name', ''))

    bucket = args['preview_bucket']

    if key.endswith(".jpg"):
        return {}

    # Create a temp dir for our files to use
    with tempfile.TemporaryDirectory() as tmpdir:

        # download file to temp dir
        file_path = Path(tmpdir, key)
        new_path = file_path.with_name(f'{file_path.stem}.jpg')

        cos.download_file(bucket, key, str(file_path))

        stream = ffmpeg.input(str(file_path))
        out = ffmpeg.output(stream, str(new_path), **{'vframes': 1})
        stdout, stderr = out.run()

        cos.upload_file(str(new_path), bucket, str(new_path.name))

        ret = {"status": "ok",
               "snapshot_key": str(new_path.name)}

        return ret
