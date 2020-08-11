# https://github.com/apache/openwhisk/blob/master/docs/actions-docker.md

FROM choirless/librosa_ml:release-2.4

RUN apt-get update && \
    apt-get install -y libsm6 libxext6 libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install importlib_resources "choirless_smiler>=1.2.1" aiohttp