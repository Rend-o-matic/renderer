# renderer

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT) [![Slack](https://img.shields.io/badge/Join-Slack-blue)](https://callforcode.org/slack)

This repository holds the [IBM Cloud Functions](https://cloud.ibm.com/functions) serverless actions that allow a choir's video contributions to be resized, correct for latency offsets, and finally combined into a video wall.

Some actions are built in Python, the rest in Node.js.

## Actions

The following actions can be found in this repository:

### JavaScript

- `renderer` - given a choirId & songId, pulls the list of song parts from the Choirless API then calls `stitcher` to render them together.

### Python

- `convert_format` - uses [FFmpeg](https://ffmpeg.org/) to convert user-generated videos in `.webm` format into `.mp4` format for further processing.
- `calculate_alignment` - compares two audio streams using [librosa](https://github.com/librosa/librosa) to calculate the latency between them.
- `trim_clip` - time-shifts a video by a supplied offset to bring it align with the others.
- `pass_to_sticher` - development function to call the `stitcher` action.

## Docker

The actions use libraries which are not available by default in the IBM Cloud Functions service. As such, Docker is used to build custom images based on the IBM Cloud Functions runtime base images, but with additional libraries needed by our code. Full instructions in each module's README.
