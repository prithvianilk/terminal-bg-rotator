# terminal-bg-rotator

Rotate images from an Imgur album into Ghostty, iTerm2, or macOS Terminal.

Currently, this supports One Piece full-color spread images.

![iTerm2 with a subtle rotating background](assets/iterm2-demo.png)

The screenshot shows the intended result: the image remains visible while the
terminal text stays readable.

## Setup

```sh
python3 -m pip install -r requirements.txt
chmod +x terminal_bg_rotator.py
```

## Examples

```sh
./terminal_bg_rotator.py --target iterm2
./terminal_bg_rotator.py --target iterm2 --opacity 0.25
./terminal_bg_rotator.py --install-iterm2-default
./terminal_bg_rotator.py --target iterm2 --watch 30
```

The default target is Ghostty and the default image opacity is `0.25`.
The iTerm2 installer creates a dynamic profile named `Terminal BG Rotator` and
sets it as iTerm2's default profile. Restart iTerm2 after installing the profile.

The default album can be overridden with `--album URL`.
