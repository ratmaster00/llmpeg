# llmpeg

Describe what you want done to a media file in plain English; Gemini writes the ffmpeg command, you confirm, it runs.

    llmpeg clip.mkv "make a 720p mp4 under 20MB for discord"
    llmpeg --nofile "10 second 720p test video with color bars and a 440Hz tone"

## Install

Needs `ffmpeg` on your PATH and a free Gemini API key (https://aistudio.google.com/apikey).

    pipx install git+https://github.com/ratmaster00/llmpeg

First run creates `~/.config/llmpeg.conf`; put your `api_key` there (or set `GEMINI_API_KEY`).

## Flags

- `-y` skip the confirmation prompt
- `-v` show the prompt, raw response and live ffmpeg output
- `--nofile` no input file (generate from scratch)
- `LLMPEG_MODEL` env var overrides the model

It always shows the command before running, never overwrites existing files, and offers to feed ffmpeg errors back to the model.
For feature requests, open an issue, email me (address in my github profile), or contact `karto.sh` on Discord. Whatever you prefer!

## REMEMBER, IT'S STILL A PROOF OF CONCEPT, THERE WILL BE BUGS. (especially since it's vibecoded)
