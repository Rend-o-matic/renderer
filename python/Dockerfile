# https://github.com/apache/openwhisk/blob/master/docs/actions-docker.md
FROM choirless/librosa_ml:release-2.0

RUN apt-get update && \
    apt-get install -y libsm6 libxext6 libxrender-dev x264 libx264-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install importlib_resources "choirless_smiler>=1.1.0" aiohttp

