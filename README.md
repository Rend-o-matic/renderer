# Choirless renderer

This repository holds the [IBM Cloud Functions](https://cloud.ibm.com/functions) serverless actions that allow a choir's video contributions to be resized, correct for latency offsets and finally combined into a video wall.

Some actions are built in Python, the rest in Node.js.

## Actions

The following actions can be found in this repository:

- `convert_format` - uses [ffmpeg](https://ffmpeg.org/) to convert user-generated videos in `.webm` format into `.mp4` format for further processing.
- `calculate_alignment` - compares two audio streams using [librosa](https://github.com/librosa/librosa) to calculate the latency between them.
- `trim_clip` - time-shifts a video by a supplied offset to bring it align with the others.
- `pass_to_sticher` - development function to call the `stitcher` action.
- `renderer` - given a choirId & songId, pulls the list of song parts from the Choirless API then calls `stitcher` to render them together.
- `stitcher` - a thin wrapper around the [Stitcheroo](https://github.com/Choirless/Stitcheroo) library to join a supplied list of videos together.

## Docker

The actions use libraries which are not available by default in the IBM Cloud Functions service. As such, Docker is used to build images based on the IBM Cloud Functions runtime base images, but adding additional libraries needed by our code. Full instructions in each module's README.
