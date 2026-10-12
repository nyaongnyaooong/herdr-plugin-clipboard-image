#!/usr/bin/env python3
"""Paste the macOS clipboard into the focused Herdr pane."""

import os
import subprocess
import sys

import paste_watch

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
TERMINALS = ("ghostty", "terminal", "iterm2", "warp", "wezterm", "kitty", "alacritty", "hyper", "herdr")


def is_terminal_app(app_name):
    name = (app_name or "").lower()
    if name in ("herdr", "herdr.exe"):
        return True
    for terminal in TERMINALS:
        if terminal in name:
            return True
    return False


def matching_machine(title, machines):
    text = title or ""
    if not text:
        return None
    for machine in machines:
        label = machine.get("label") or ""
        if not label:
            continue
        if text == label or text.startswith(label + ": "):
            return machine
    return None


def title_matches_workspace(title, workspace_label):
    text = title or ""
    label = workspace_label or ""
    if not text or not label:
        return False
    if text == label or text.endswith(": " + label) or text.endswith(label):
        return True
    return False


def resolve_paste_target(app_name, title, machines, selected_machine, workspace_label):
    """Return (matched, machine). machine is None for a local pane."""
    if not is_terminal_app(app_name):
        return False, None
    machine = matching_machine(title, machines)
    if machine:
        return True, machine
    if title_matches_workspace(title, workspace_label):
        return True, None
    name = (app_name or "").lower()
    if name in ("herdr", "herdr.exe"):
        return True, selected_machine
    if not title:
        return True, None
    return False, None


def plugin_root():
    configured = os.environ.get("HERDR_PLUGIN_ROOT")
    if configured:
        return configured
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def helper_path():
    return os.path.join(plugin_root(), "bin", "paste-watch-macos")


def ensure_helper():
    binary = helper_path()
    source = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paste-watch-macos.swift")
    if os.path.isfile(binary) and os.path.getmtime(binary) >= os.path.getmtime(source):
        return binary
    os.makedirs(os.path.dirname(binary), exist_ok=True)
    compile_helper(source, binary)
    return binary


def compile_helper(source, binary):
    proc = subprocess.run(
        ["swiftc", "-O", "-o", binary, source, "-framework", "AppKit", "-framework", "ApplicationServices"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail or "Could not compile the macOS clipboard helper")


def export_clipboard(dest_dir):
    binary = ensure_helper()
    proc = subprocess.run([binary, "export", dest_dir], capture_output=True)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(detail or "Could not read the macOS clipboard")
    text = proc.stdout.decode("utf-8", "replace")
    newline = text.find("\n")
    if newline < 0:
        return "empty", ""
    kind = text[:newline].strip()
    payload = text[newline + 1 :]
    return kind, payload


def send_text(pane_id, text):
    env = os.environ.copy()
    env.pop("HERDR_PANE_ID", None)
    env.pop("HERDR_TAB_ID", None)
    proc = subprocess.run(
        [paste_watch.herdr_bin(), "pane", "send-text", pane_id, text],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail or "Could not send text to the focused pane")


def notify(title, body):
    subprocess.run(
        [paste_watch.herdr_bin(), "notification", "show", title, "--body", body, "--sound", "none"],
        capture_output=True,
    )


def focused_pane_id():
    pane = paste_watch.focused_pane()
    pane_id = (pane or {}).get("pane_id")
    if not pane_id:
        raise RuntimeError("No focused Herdr pane was found")
    return pane_id


def watch_target():
    paste_watch.refresh_workspace_label()
    return resolve_paste_target(
        os.environ.get("HERDR_PASTE_APP", ""),
        os.environ.get("HERDR_PASTE_TITLE", ""),
        paste_watch.saved_machines,
        paste_watch.selected_machine,
        paste_watch.workspace_label,
    )


def paste_text(payload):
    text = payload
    if not text:
        return 1
    pane_id = focused_pane_id()
    send_text(pane_id, text)
    return 0


def main():
    supplied = sys.argv[1] if len(sys.argv) > 1 else ""
    from_watch = os.environ.get("HERDR_PASTE_FROM_WATCH") == "1"
    machine = None
    if from_watch:
        matched, machine = watch_target()
        if not matched:
            return 0
    if supplied and os.path.isfile(supplied):
        paste_watch.deliver_saved_image(supplied, machine)
        return 0

    kind, payload = export_clipboard(paste_watch.stage_dir())
    if kind == "image" and payload.strip() and os.path.isfile(payload.strip()):
        paste_watch.deliver_saved_image(payload.strip(), machine)
        return 0
    if kind == "text" and payload:
        return paste_text(payload)
    if kind == "file" and payload.strip() and os.path.isfile(payload.strip()):
        suffix = os.path.splitext(payload.strip())[1].lower()
        if suffix in IMAGE_SUFFIXES:
            paste_watch.deliver_saved_image(payload.strip(), machine)
            return 0
        send_text(focused_pane_id(), " " + payload.strip() + " ")
        return 0
    message = "클립보드에서 이미지, 파일, 텍스트를 찾지 못했습니다."
    print(message, file=sys.stderr)
    notify("클립보드 이미지", message)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
