#!/usr/bin/env python3
"""Rotate images from an Imgur album into Ghostty, iTerm2, or macOS Terminal."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ALBUM_URL = "https://imgur.com/a/jsstNId"
APP_DIR = Path.home() / "Library" / "Application Support" / "terminal-bg-rotator"
MANIFEST_FILE = APP_DIR / "manifest.json"
STATE_FILE = APP_DIR / "state.json"
CACHE_DIR = APP_DIR / "cache"
ACTIVE_IMAGE = APP_DIR / "active.png"
ITERM_DYNAMIC_PROFILE = (
    Path.home()
    / "Library"
    / "Application Support"
    / "iTerm2"
    / "DynamicProfiles"
    / "terminal-bg-rotator.json"
)
ITERM_PROFILE_GUID = "8b4c3e8e-5d2b-4c75-a8f8-9d8f7b8d1e2a"
DEFAULT_TARGET = "ghostty"
DEFAULT_OPACITY = "0.25"
USER_AGENT = "terminal-bg-rotator/0.1"


def fetch(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        return response.read()


def atomic_write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb" if isinstance(data, bytes) else "w",
            encoding=None if isinstance(data, bytes) else "utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as file:
            file.write(data)
            temporary = Path(file.name)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def read_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def album_embed_url(album_url: str) -> str:
    album_url = album_url.rstrip("/")
    return album_url if album_url.endswith("/embed") else f"{album_url}/embed"


def parse_album(html: str) -> list[dict]:
    marker = '"album_images":'
    marker_index = html.find(marker)
    if marker_index == -1:
        raise RuntimeError("Could not find album image data in the Imgur page")

    object_start = html.find("{", marker_index + len(marker))
    if object_start == -1:
        raise RuntimeError("Imgur album data is malformed")

    try:
        album_images, _ = json.JSONDecoder().raw_decode(html[object_start:])
    except json.JSONDecodeError as error:
        raise RuntimeError("Could not parse Imgur album image data") from error

    images = []
    seen = set()
    for image in album_images.get("images", []):
        image_id = image.get("hash")
        extension = image.get("ext", ".png")
        if not image_id or image_id in seen:
            continue
        seen.add(image_id)
        images.append(
            {
                "id": image_id,
                "url": f"https://i.imgur.com/{image_id}{extension}",
                "width": image.get("width"),
                "height": image.get("height"),
            }
        )

    if not images:
        raise RuntimeError("Imgur album did not contain any images")
    return images


def sync_manifest(album_url: str) -> list[dict]:
    print(f"Reading album: {album_url}")
    html = fetch(album_embed_url(album_url)).decode("utf-8", errors="replace")
    images = parse_album(html)
    atomic_write(
        MANIFEST_FILE,
        json.dumps({"album_url": album_url, "images": images}, indent=2) + "\n",
    )
    print(f"Found {len(images)} images")
    return images


def load_images(album_url: str, refresh: bool = False) -> list[dict]:
    if refresh or not MANIFEST_FILE.exists():
        return sync_manifest(album_url)
    manifest = read_json(MANIFEST_FILE, {})
    images = manifest.get("images")
    if not isinstance(images, list) or not images:
        return sync_manifest(album_url)
    return images


def download_image(image: dict) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    destination = CACHE_DIR / f"{image['id']}.png"
    if destination.exists() and destination.stat().st_size > 0:
        return destination

    print(f"Downloading {image['id']}...")
    request = Request(image["url"], headers={"User-Agent": USER_AGENT})
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        with urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        header = temporary.read_bytes()[:8]
        if header != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError(f"Imgur returned a non-PNG response for {image['id']}")
        os.replace(temporary, destination)
    except (HTTPError, URLError) as error:
        raise RuntimeError(f"Could not download {image['url']}: {error}") from error
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def make_active(image_path: Path) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    temporary = APP_DIR / f".active.{os.getpid()}.tmp"
    try:
        shutil.copyfile(image_path, temporary)
        os.replace(temporary, ACTIVE_IMAGE)
    finally:
        if temporary.exists():
            temporary.unlink()


def make_iterm_image(image_path: Path, opacity: str) -> Path:
    try:
        image_opacity = float(opacity)
    except ValueError as error:
        raise ValueError("--opacity must be a number between 0 and 1") from error
    if not 0 <= image_opacity <= 1:
        raise ValueError("--opacity must be between 0 and 1")

    output = CACHE_DIR / f"{image_path.stem}.iterm-{image_opacity:g}.png"
    if output.exists() and output.stat().st_size > 0:
        return output

    try:
        from PIL import Image
    except ImportError as error:
        raise RuntimeError(
            "iTerm2 target requires Pillow; install it with: python3 -m pip install Pillow"
        ) from error

    with Image.open(image_path) as source:
        source_rgba = source.convert("RGBA")
        black = Image.new("RGBA", source_rgba.size, (0, 0, 0, 255))
        source_rgb = Image.alpha_composite(black, source_rgba).convert("RGB")
        subdued = Image.blend(Image.new("RGB", source_rgb.size), source_rgb, image_opacity)
        temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
        try:
            subdued.save(temporary, format="PNG")
            os.replace(temporary, output)
        finally:
            if temporary.exists():
                temporary.unlink()
    return output


def ghostty_config_path() -> Path:
    home = Path.home()
    app_support = home / "Library" / "Application Support" / "com.mitchellh.ghostty"
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "ghostty"
    candidates = [
        app_support / "config.ghostty",
        app_support / "config",
        xdg / "config.ghostty",
        xdg / "config",
    ]
    return next((path for path in candidates if path.exists()), candidates[0])


def update_ghostty(opacity: str) -> None:
    config = ghostty_config_path()
    existing = config.read_text(encoding="utf-8") if config.exists() else ""
    escaped_image = str(ACTIVE_IMAGE).replace("\\", "\\\\").replace('"', '\\"')
    block = (
        "# terminal-bg-rotator:start\n"
        f'background-image = "{escaped_image}"\n'
        f"background-image-opacity = {opacity}\n"
        "background-image-fit = cover\n"
        "background-image-position = center\n"
        "background-image-repeat = false\n"
        "# terminal-bg-rotator:end\n"
    )
    pattern = re.compile(
        r"^# terminal-bg-rotator:start\n.*?^# terminal-bg-rotator:end\n?",
        re.MULTILINE | re.DOTALL,
    )
    updated = pattern.sub(block, existing)
    if updated == existing:
        updated = existing.rstrip() + ("\n\n" if existing.strip() else "") + block
    atomic_write(config, updated)
    print(f"Ghostty config updated: {config}")

    if not app_is_running("Ghostty"):
        print("Ghostty is not running; the new image will apply to the next window.")
        return

    script = """
tell application "Ghostty"
    repeat with terminalWindow in terminals
        perform action "reload_config" on terminalWindow
    end repeat
end tell
"""
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True
    )
    if result.returncode:
        print("Ghostty config was updated, but automatic reload failed.")
        if result.stderr.strip():
            print(result.stderr.strip())


def app_is_running(process_name: str) -> bool:
    processes = subprocess.run(
        ["ps", "-axo", "command="], capture_output=True, text=True
    ).stdout.splitlines()
    return any(Path(command.strip().split(" ", 1)[0]).name == process_name for command in processes)


def applescript_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_iterm2_profile(image_path: Path) -> None:
    ITERM_DYNAMIC_PROFILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(
        ITERM_DYNAMIC_PROFILE,
        json.dumps(
            {
                "Profiles": [
                    {
                        "Name": "Terminal BG Rotator",
                        "Guid": ITERM_PROFILE_GUID,
                        "Background Image Location": str(image_path),
                        "Background Image Opacity": 1.0,
                    }
                ]
            },
            indent=2,
        )
        + "\n",
    )


def install_iterm2_default() -> None:
    profile_image = (
        make_iterm_image(ACTIVE_IMAGE, DEFAULT_OPACITY)
        if ACTIVE_IMAGE.exists()
        else ACTIVE_IMAGE
    )
    write_iterm2_profile(profile_image)
    result = subprocess.run(
        [
            "defaults",
            "write",
            "com.googlecode.iterm2",
            "Default Bookmark Guid",
            "-string",
            ITERM_PROFILE_GUID,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        detail = result.stderr.strip() or "defaults write failed"
        raise RuntimeError(f"Could not set iTerm2's default profile: {detail}")
    print(f"Installed iTerm2 profile: {ITERM_DYNAMIC_PROFILE}")
    print("iTerm2 default profile set to Terminal BG Rotator.")
    if app_is_running("iTerm2"):
        print("Restart iTerm2 for the new default to take effect.")


def update_iterm2(opacity: str, live_image: Path) -> None:
    write_iterm2_profile(live_image)
    print(f"iTerm2 profile updated: {ITERM_DYNAMIC_PROFILE}")

    if not app_is_running("iTerm2"):
        print("iTerm2 is not running; the profile will be available next time it opens.")
        return

    # iTerm2 can cache an image by its path. Use the immutable cached image
    # for open sessions so replacing active.png is visible immediately.
    image = applescript_quote(str(live_image))
    script = f"""
tell application "iTerm2"
    repeat with currentWindow in windows
        repeat with currentTab in tabs of currentWindow
            repeat with currentSession in sessions of currentTab
                set background image of currentSession to {image}
            end repeat
        end repeat
    end repeat
end tell
"""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        print("iTerm2 did not respond within 10 seconds; rotation continued without live refresh.")
        return
    if result.returncode:
        print("iTerm2 profile was updated, but open sessions could not be refreshed.")
        if result.stderr.strip():
            print(result.stderr.strip())


def terminal_note() -> None:
    print(
        "Terminal uses the active image path. One time, choose this file in "
        f"Terminal > Settings > Profiles > Text > Image:\n  {ACTIVE_IMAGE}\n"
        "New Terminal windows will use the latest image; reopen existing windows "
        "if they do not refresh."
    )


def load_state() -> dict:
    return read_json(STATE_FILE, {"index": -1, "image_id": None})


def choose_image(images: list[dict], randomize: bool) -> tuple[int, dict]:
    state = load_state()
    previous = int(state.get("index", -1))
    if randomize and len(images) > 1:
        index = random.randrange(len(images))
        if index == previous:
            index = (index + 1) % len(images)
    else:
        index = (previous + 1) % len(images)
    return index, images[index]


def rotate(images: list[dict], target: str, randomize: bool, opacity: str) -> None:
    index, image = choose_image(images, randomize)
    print(f"Image {index + 1}/{len(images)}: {image['id']}")
    cached_image = download_image(image)
    make_active(cached_image)

    if target in ("ghostty", "both", "all"):
        update_ghostty(opacity)
    if target in ("terminal", "both", "all"):
        terminal_note()
    if target in ("iterm2", "all"):
        update_iterm2(opacity, make_iterm_image(cached_image, opacity))

    atomic_write(
        STATE_FILE,
        json.dumps(
            {"index": index, "image_id": image["id"], "updated_at": time.time()},
            indent=2,
        )
        + "\n",
    )
    print(f"Active image: {ACTIVE_IMAGE}")


def print_status(images: list[dict]) -> None:
    state = load_state()
    index = state.get("index", -1)
    current = images[index]["id"] if isinstance(index, int) and 0 <= index < len(images) else "none"
    print(f"Album images: {len(images)}")
    print(f"Current image: {current}")
    print(f"Active path: {ACTIVE_IMAGE}")
    print(f"Cache path: {CACHE_DIR}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--album", default=ALBUM_URL, help="Imgur album URL")
    parser.add_argument(
        "--target",
        choices=("ghostty", "terminal", "iterm2", "both", "all"),
        default=os.environ.get("TERMINAL_BG_TARGET", DEFAULT_TARGET),
    )
    parser.add_argument("--opacity", default=DEFAULT_OPACITY)
    parser.add_argument("--random", action="store_true", help="Choose a random image")
    parser.add_argument("--refresh", action="store_true", help="Refresh the album manifest")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--watch", type=float, metavar="MINUTES", help="Rotate repeatedly")
    parser.add_argument(
        "--install-iterm2-default",
        action="store_true",
        help="Install the iTerm2 profile and make it the default profile",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.install_iterm2_default:
            install_iterm2_default()
            return
        images = load_images(args.album, refresh=args.refresh)
        if args.status:
            print_status(images)
            return
        if args.refresh:
            print("Manifest refreshed.")
            return

        if args.watch is None:
            rotate(images, args.target, args.random, args.opacity)
            return

        if args.watch <= 0:
            raise ValueError("--watch must be greater than zero")
        while True:
            rotate(images, args.target, args.random, args.opacity)
            time.sleep(args.watch * 60)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
