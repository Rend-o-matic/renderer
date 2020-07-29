# https://github.com/apache/openwhisk/blob/master/docs/actions-docker.md
FROM choirless/librosa_ml

RUN apt-get update && \
    apt-get install -y libsm6 libxext6 libxrender-dev nasm \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://ffmpeg.org/releases/ffmpeg-4.3.1.tar.gz -o /tmp/ffmpeg-4.3.1.tar.gz \
    && cd /tmp \
    && tar -xzf ffmpeg-4.3.1.tar.gz \
    && cd ffmpeg-4.3.1 \
    && ./configure \
    && make \
    && make install \
    && rm /tmp/ffmpeg-4.3.1.tar.gz

RUN pip3 install importlib_resources "choirless_smiler>=1.1.0" aiohttp

