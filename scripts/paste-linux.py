#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

HERDR = os.environ.get("HERDR_BIN_PATH") or "herdr"


def run(args, *, data=None):
    return subprocess.run(args, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def herdr_json(args):
    result = run([HERDR, *args])
    if result.returncode:
        return {}
    text = result.stdout.decode("utf-8", "replace")
    start = text.find("{")
    if start < 0:
        return {}
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError:
        return {}


def focused_pane():
    pane_id = os.environ.get("HERDR_PANE_ID")
    if not pane_id:
        raw = os.environ.get("HERDR_PLUGIN_CONTEXT_JSON", "")
        try:
            context = json.loads(raw)
            pane_id = context.get("focused_pane_id")
        except (json.JSONDecodeError, AttributeError):
            pass
    if not pane_id:
        result = (herdr_json(["pane", "current"]).get("result") or {}).get("pane") or {}
        pane_id = result.get("pane_id")
    if not pane_id:
        raise RuntimeError("No focused Herdr pane was found")
    return pane_id


def clipboard_types():
    if shutil.which("wl-paste"):
        result = run(["wl-paste", "--list-types"])
        if result.returncode == 0:
            return ("wl", result.stdout.decode("utf-8", "replace").splitlines())
    if shutil.which("xclip"):
        result = run(["xclip", "-selection", "clipboard", "-t", "TARGETS", "-o"])
        if result.returncode == 0:
            return ("xclip", result.stdout.decode("utf-8", "replace").splitlines())
    return (None, [])


def clipboard_read(tool, mime):
    if tool == "wl":
        result = run(["wl-paste", "--no-newline", "--type", mime])
    elif tool == "xclip":
        result = run(["xclip", "-selection", "clipboard", "-t", mime, "-o"])
    else:
        return None
    return result.stdout if result.returncode == 0 else None


def send_text(pane_id, text):
    result = run([HERDR, "pane", "send-text", pane_id, text])
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(detail or "Could not send text to the focused pane")


def main():
    pane_id = focused_pane()
    supplied = os.environ.get("HERDR_CLIPBOARD_IMAGE_PATH")
    if supplied and os.path.isfile(supplied):
        send_text(pane_id, " " + supplied.replace("\\", "/") + " ")
        return 0

    tool, types = clipboard_types()
    image_types = ("image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "image/tiff")
    suffixes = {
        "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
        "image/webp": ".webp", "image/bmp": ".bmp", "image/tiff": ".tiff",
    }
    for mime in image_types:
        if mime in types:
            payload = clipboard_read(tool, mime)
            if payload:
                cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
                folder = cache / "herdr" / "clipboard-images"
                folder.mkdir(parents=True, exist_ok=True)
                cutoff = datetime.now().timestamp() - 2 * 24 * 60 * 60
                for old in folder.iterdir():
                    try:
                        if old.is_file() and old.stat().st_mtime < cutoff:
                            old.unlink()
                    except OSError:
                        pass
                path = folder / (datetime.now().strftime("clip-%Y%m%d-%H%M%S-%f") + suffixes[mime])
                path.write_bytes(payload)
                send_text(pane_id, " " + str(path) + " ")
                return 0

    for mime in ("text/uri-list", "text/plain;charset=utf-8", "text/plain", "UTF8_STRING"):
        if mime not in types:
            continue
        payload = clipboard_read(tool, mime)
        if not payload:
            continue
        text = payload.decode("utf-8", "replace")
        uris = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
        for uri in uris:
            parsed = urlparse(uri)
            candidate = unquote(parsed.path) if parsed.scheme == "file" else uri
            if os.path.isfile(candidate) and Path(candidate).suffix.lower() in {
                ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"
            }:
                send_text(pane_id, " " + candidate.replace("\\", "/") + " ")
                return 0
        if text:
            send_text(pane_id, text)
            return 0

    if tool is None:
        print("No wl-paste or xclip clipboard is available on this server.", file=sys.stderr)
        return 1
    result = run([HERDR, "pane", "send-keys", pane_id, "ctrl+v"])
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(detail or "Could not forward Ctrl+V")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)