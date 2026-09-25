"""Catch Ctrl+V in the Herdr window and insert a clipboard image path.

Herdr delivers Ctrl+V straight to the pane, so a keybinding never sees it.
This process watches the keyboard only while Herdr is the foreground window.
"""

import json
import os
import subprocess
import sys
import threading
import time
import ctypes
import shutil
import posixpath
import shlex
from ctypes import wintypes
from datetime import datetime, timedelta
from urllib.parse import urlparse

from PIL import ImageGrab

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_V = 0x56
CF_BITMAP = 2
CF_DIB = 8
CF_HDROP = 15
CF_DIBV5 = 17
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
LLKHF_UP = 0x80

LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]

STATE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.getcwd()), "herdr", "clipboard-image")
LOG_PATH = os.path.join(STATE_DIR, "paste.log")
hook_handle = None
hook_proc = None
last_paste = 0.0
paste_in_progress = False
paste_lock = threading.Lock()
workspace_label = ""
selected_machine = None
saved_machines = []


def log(message):
    os.makedirs(STATE_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%H:%M:%S")
    with open(LOG_PATH, "a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {message}\n")


def herdr_bin():
    return os.environ.get("HERDR_BIN_PATH") or "herdr"


def run_herdr(args, ignore_caller=False):
    env = None
    if ignore_caller:
        # The watcher inherits HERDR_PANE_ID from whichever pane started it.
        # herdr pane current treats that id as the target and ignores the tab
        # the user is actually looking at.
        env = os.environ.copy()
        env.pop("HERDR_PANE_ID", None)
        env.pop("HERDR_TAB_ID", None)
    try:
        proc = subprocess.run(
            [herdr_bin(), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except OSError as error:
        log(f"herdr failed: {error}")
        return {}
    text = proc.stdout or ""
    starts = [position for position in (text.find("{"), text.find("[")) if position >= 0]
    if not starts:
        return {}
    try:
        value, _ = json.JSONDecoder().raw_decode(text, min(starts))
        return value
    except json.JSONDecodeError:
        return {}


def stage_dir():
    path = os.path.join(os.environ.get("TEMP", STATE_DIR), "herdr-clipboard-images")
    os.makedirs(path, exist_ok=True)
    cutoff = datetime.now() - timedelta(days=2)
    for name in os.listdir(path):
        file_path = os.path.join(path, name)
        try:
            if datetime.fromtimestamp(os.path.getmtime(file_path)) < cutoff:
                os.remove(file_path)
        except OSError:
            pass
    return path


def stage_workspace_image(cwd, source_path):
    """Copy an image into the active workspace for Cursor's @path context."""
    folder = os.path.join(cwd, "herdr-clipboard-images")
    os.makedirs(folder, exist_ok=True)
    cutoff = datetime.now().timestamp() - 2 * 24 * 60 * 60
    for name in os.listdir(folder):
        if not name.startswith("clip-"):
            continue
        file_path = os.path.join(folder, name)
        try:
            if os.path.isfile(file_path) and os.path.getmtime(file_path) < cutoff:
                os.remove(file_path)
        except OSError:
            pass
    target_path = os.path.join(folder, os.path.basename(source_path))
    shutil.copy2(source_path, target_path)
    return target_path


def clipboard_has_image():
    return any(user32.IsClipboardFormatAvailable(fmt) for fmt in (CF_DIB, CF_DIBV5, CF_BITMAP))


def save_clipboard_image():
    grabbed = ImageGrab.grabclipboard()
    folder = stage_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if hasattr(grabbed, "save") and hasattr(grabbed, "size"):
        path = os.path.join(folder, f"clip-{stamp}.png")
        grabbed.save(path, "PNG")
        return path
    if isinstance(grabbed, list):
        for source in grabbed:
            if not isinstance(source, str):
                continue
            if os.path.splitext(source)[1].lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}:
                continue
            ext = os.path.splitext(source)[1]
            path = os.path.join(folder, f"clip-{stamp}{ext}")
            with open(source, "rb") as source_file, open(path, "wb") as dest_file:
                dest_file.write(source_file.read())
            return path
    return None


def is_status_pane(pane):
    return "ai-usage-status" in (pane.get("terminal_title") or "")


def focused_pane():
    result = (run_herdr(["pane", "current"], ignore_caller=True).get("result") or {})
    pane = result.get("pane") or {}
    if pane.get("pane_id") and not is_status_pane(pane):
        return pane
    tab_id = pane.get("tab_id")
    listed = (run_herdr(["pane", "list"], ignore_caller=True).get("result") or {}).get("panes") or []
    siblings = [
        item for item in listed
        if item.get("tab_id") == tab_id and item.get("pane_id") and not is_status_pane(item)
    ]
    if not siblings:
        return None
    return next((item for item in siblings if item.get("focused")), siblings[0])


def ssh_args(target):
    """Turn a saved SSH target into OpenSSH arguments."""
    if target.startswith("ssh://"):
        parsed = urlparse(target)
        if not parsed.hostname or parsed.password:
            raise ValueError("unsupported SSH target URI")
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        if parsed.username:
            host = f"{parsed.username}@{host}"
        args = ["ssh", "-T"]
        if parsed.port:
            args.extend(["-p", str(parsed.port)])
        return [*args, host]
    return ["ssh", "-T", target]


def upload_remote_image(machine, local_path, pane=None):
    """Copy a staged image to the selected saved machine over its SSH target."""
    target = machine.get("target")
    if not target:
        log("selected machine has no SSH target")
        return None
    ssh = shutil.which("ssh")
    if not ssh:
        log("ssh executable not found")
        return None

    name = os.path.basename(local_path)
    if not name.startswith("clip-") or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in name):
        log("refused unsafe clipboard image filename")
        return None
    agent = ((pane or {}).get("agent") or "").lower()
    pane_cwd = (pane or {}).get("foreground_cwd") or (pane or {}).get("cwd")
    if agent == "cursor" and pane_cwd and pane_cwd.startswith("/"):
        # Cursor CLI's documented workaround is an @path file reference. Keep
        # the temporary image under its workspace so the CLI can resolve it.
        remote_dir = posixpath.join(pane_cwd, "herdr-clipboard-images")
    else:
        remote_dir = "/tmp/herdr-clipboard-images"
    remote_path = posixpath.join(remote_dir, name)
    quoted_dir = shlex.quote(remote_dir)
    quoted_path = shlex.quote(remote_path)
    remote_command = (
        f"mkdir -p -- {quoted_dir} && "
        f"(find {quoted_dir} -maxdepth 1 -type f -name 'clip-*' -mmin +2880 -delete "
        f"2>/dev/null || true) && cat > {quoted_path}"
    )
    try:
        with open(local_path, "rb") as image_file:
            proc = subprocess.run(
                [ssh, *ssh_args(target)[1:], remote_command],
                input=image_file.read(),
                capture_output=True,
                timeout=45,
            )
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        log(f"remote image transfer failed: {error}")
        return None
    if proc.returncode != 0:
        detail = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        log(f"remote image transfer failed exit={proc.returncode} {detail[:300]}")
        return None
    return remote_path


def remove_remote_image(machine, remote_path):
    target = machine.get("target")
    ssh = shutil.which("ssh")
    if not target or not ssh:
        return
    try:
        subprocess.run(
            [ssh, *ssh_args(target)[1:], f"rm -f -- {shlex.quote(remote_path)}"],
            capture_output=True,
            timeout=15,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass


def remote_focused_pane(machine):
    """Return the focused non-status pane on a saved remote Herdr machine."""
    machine_id = machine.get("id") or machine.get("label")
    if not machine_id:
        log("selected machine has no Herdr machine id")
        return None

    current = run_herdr(["--machine", machine_id, "pane", "current"], ignore_caller=True)
    pane = ((current.get("result") or {}).get("pane") or {}) if isinstance(current, dict) else {}
    if pane.get("pane_id") and not is_status_pane(pane):
        return pane

    tab_id = pane.get("tab_id")
    listed = run_herdr(["--machine", machine_id, "pane", "list"], ignore_caller=True)
    panes = ((listed.get("result") or {}).get("panes") or []) if isinstance(listed, dict) else []
    siblings = [
        item for item in panes
        if item.get("tab_id") == tab_id and item.get("pane_id") and not is_status_pane(item)
    ]
    if not siblings:
        log(f"no focused remote pane machine={machine.get('label')}")
        return None
    return next((item for item in siblings if item.get("focused")), siblings[0])


def pane_agent_status(machine, pane_id):
    args = ["pane", "list"]
    if machine:
        machine_id = machine.get("id") or machine.get("label")
        if not machine_id:
            return None
        args = ["--machine", machine_id, *args]
    result = run_herdr(args, ignore_caller=True)
    panes = ((result.get("result") or {}).get("panes") or []) if isinstance(result, dict) else []
    pane = next((item for item in panes if item.get("pane_id") == pane_id), None)
    return (pane or {}).get("agent_status")


def delete_local_image(path):
    if not path or not os.path.basename(path).startswith("clip-"):
        return
    try:
        os.remove(path)
    except OSError:
        pass


def schedule_image_cleanup(machine, pane_id, image_path, initial_status, local_path=None):
    """Remove staged image files shortly after the CLI starts the submitted turn."""
    def worker():
        saw_idle = initial_status != "working"
        deadline = time.monotonic() + 5 * 60
        interval = 1.5 if machine else 0.5
        while time.monotonic() < deadline:
            status = pane_agent_status(machine, pane_id)
            if status and status != "working":
                saw_idle = True
            elif status == "working" and saw_idle:
                # Let the CLI finish reading the @path or attached image data.
                time.sleep(10)
                if machine:
                    remove_remote_image(machine, image_path)
                else:
                    delete_local_image(image_path)
                delete_local_image(local_path)
                log(f"cleaned submitted clipboard image pane={pane_id} machine={(machine or {}).get('label', 'local')}")
                return
            time.sleep(interval)

    threading.Thread(target=worker, daemon=True).start()


def paste_remote_path(machine, pane_id, remote_path):
    """Send a bracketed paste to the remote TUI so image paths are recognized."""
    machine_id = machine.get("id") or machine.get("label")
    if not machine_id or not pane_id:
        return False
    # A real terminal paste is bracketed. In particular, Codex turns pasted
    # local image paths into image attachments; typing the same path leaves text.
    pasted = f"\x1b[200~ {remote_path} \x1b[201~"
    env = os.environ.copy()
    env.pop("HERDR_PANE_ID", None)
    env.pop("HERDR_TAB_ID", None)
    try:
        proc = subprocess.run(
            [herdr_bin(), "--machine", machine_id, "pane", "send-text", pane_id, pasted],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        log(f"remote path paste failed: {error}")
        return False
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        log(f"remote path paste failed exit={proc.returncode} {detail[:300]}")
        return False
    return True


def still_in_remote_window(machine, expected_hwnd, expected_title):
    hwnd, name, title = foreground_window()
    matched, current_machine = foreground_route(name, title)
    return (
        hwnd == expected_hwnd
        and title == expected_title
        and matched
        and current_machine is not None
        and current_machine.get("id") == machine.get("id")
    )


def wait_for_control_release(timeout=1.0):
    deadline = time.monotonic() + timeout
    while user32.GetAsyncKeyState(VK_CONTROL) & 0x8000:
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


def paste_image(machine=None, expected_hwnd=None, expected_title=""):
    path = save_clipboard_image()
    if not path:
        log("clipboard has no image")
        return
    if machine:
        if not wait_for_control_release() or not still_in_remote_window(machine, expected_hwnd, expected_title):
            log(f"remote paste cancelled because the focused window changed machine={machine.get('label')}")
            return
        pane = remote_focused_pane(machine)
        if not pane:
            return
        uploaded_path = upload_remote_image(machine, path, pane)
        if not uploaded_path:
            return
        if not wait_for_control_release() or not still_in_remote_window(machine, expected_hwnd, expected_title):
            remove_remote_image(machine, uploaded_path)
            log(f"remote paste cancelled because the focused window changed machine={machine.get('label')}")
            return
        prompt_reference = uploaded_path
        agent = (pane.get("agent") or "").lower()
        if agent == "cursor":
            pane_cwd = pane.get("foreground_cwd") or pane.get("cwd") or ""
            reference = posixpath.relpath(uploaded_path, pane_cwd) if pane_cwd else uploaded_path
            prompt_reference = f"@{reference}"
        if not paste_remote_path(machine, pane.get("pane_id"), prompt_reference):
            remove_remote_image(machine, uploaded_path)
            log(f"remote path paste failed machine={machine.get('label')}")
            return
        log(
            f"pasted {prompt_reference} -> remote:{pane.get('pane_id')} "
            f"machine={machine.get('label')} title={expected_title!r}"
        )
        if agent in {"codex", "cursor"}:
            schedule_image_cleanup(
                machine,
                pane.get("pane_id"),
                uploaded_path,
                pane.get("agent_status"),
                local_path=path,
            )
        return

    pane = focused_pane()
    pane_id = (pane or {}).get("pane_id")
    if not pane_id:
        log("no focused pane")
        return
    shown = path.replace("\\", "/")
    if (pane.get("agent") or "").lower() == "cursor":
        pane_cwd = pane.get("foreground_cwd") or pane.get("cwd")
        if pane_cwd:
            try:
                workspace_image = stage_workspace_image(pane_cwd, path)
                shown = "@" + os.path.relpath(workspace_image, pane_cwd).replace("\\", "/")
            except OSError as error:
                log(f"could not stage image for Cursor CLI: {error}")
                return
    env = os.environ.copy()
    env.pop("HERDR_PANE_ID", None)
    env.pop("HERDR_TAB_ID", None)
    args = ["pane", "send-text", pane_id, f" {shown} "]
    try:
        proc = subprocess.run(
            [herdr_bin(), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except OSError as error:
        log(f"herdr paste failed: {error}")
        return
    title = pane.get("terminal_title") or ""
    log(f"pasted {shown} -> local:{pane_id} tab={pane.get('tab_id')} title={title!r} exit {proc.returncode}")
    if proc.returncode == 0 and (pane.get("agent") or "").lower() in {"codex", "cursor"}:
        image_path = workspace_image if (pane.get("agent") or "").lower() == "cursor" and pane_cwd else path
        schedule_image_cleanup(
            None,
            pane_id,
            image_path,
            pane.get("agent_status"),
            local_path=path if image_path != path else None,
        )


def foreground_window():
    hwnd = user32.GetForegroundWindow()
    title = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title, 512)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    name = ""
    if handle:
        try:
            size = wintypes.DWORD(512)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                name = os.path.basename(buffer.value).lower()
        finally:
            kernel32.CloseHandle(handle)
    return hwnd, name, title.value


def label_loop():
    while True:
        time.sleep(3)
        try:
            refresh_workspace_label()
        except Exception as error:
            log(f"label error: {error}")


def refresh_workspace_label():
    global workspace_label, selected_machine, saved_machines
    result = run_herdr(["workspace", "list"])
    workspaces = (result.get("result") or {}).get("workspaces") or []
    chosen = next((item for item in workspaces if item.get("focused")), None)
    if not chosen and workspaces:
        chosen = workspaces[0]
    workspace_label = (chosen or {}).get("label") or ""
    profiles = run_herdr(["machine", "list", "--json"])
    if isinstance(profiles, dict):
        profiles = (profiles.get("result") or {}).get("machines") or []
    saved_machines = [item for item in profiles if item.get("enabled")]
    selected_machine = next(
        (item for item in saved_machines if item.get("selected")),
        None,
    )


def foreground_route(name=None, title=None):
    if name is None or title is None:
        _, name, title = foreground_window()
    if name in {"herdr.exe", "windowsterminal.exe", "openconsole.exe"}:
        for machine in saved_machines:
            label = machine.get("label") or ""
            if label and (title == label or title.startswith(f"{label}: ")):
                return True, machine
    if name == "herdr.exe":
        return True, selected_machine
    if name not in {"windowsterminal.exe", "openconsole.exe"}:
        return False, None
    if selected_machine:
        label = selected_machine.get("label") or ""
        if label and (title == label or title.startswith(f"{label}: ")):
            return True, selected_machine
    if workspace_label and (title.endswith(f": {workspace_label}") or title.endswith(workspace_label)):
        return True, None
    return False, None


def schedule_paste(machine=None, expected_hwnd=None, expected_title=""):
    global last_paste, paste_in_progress
    now = time.monotonic()
    with paste_lock:
        if paste_in_progress or now - last_paste < 0.4:
            return
        last_paste = now
        paste_in_progress = True

    def worker():
        global paste_in_progress
        try:
            paste_image(machine, expected_hwnd, expected_title)
        finally:
            with paste_lock:
                paste_in_progress = False

    threading.Thread(target=worker, daemon=True).start()


def hook_callback(code, wparam, lparam):
    try:
        if code == 0 and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            ctrl = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
            alt = bool(user32.GetAsyncKeyState(VK_MENU) & 0x8000)
            if info.vkCode == VK_V and ctrl and not alt and not (info.flags & LLKHF_UP):
                hwnd, name, title = foreground_window()
                matched, machine = foreground_route(name, title)
                image = clipboard_has_image()
                target = (machine or {}).get("label", "local") if matched else "none"
                log(f"ctrl+v app={name} title={title!r} match={matched} target={target} image={image}")
                if matched and image:
                    schedule_paste(machine, hwnd, title)
                    return 1
    except Exception as error:
        log(f"hook error: {error}")
    return user32.CallNextHookEx(hook_handle, code, wparam, lparam)


def main():
    global hook_handle, hook_proc
    os.makedirs(STATE_DIR, exist_ok=True)
    refresh_workspace_label()
    threading.Thread(target=label_loop, daemon=True).start()
    hook_proc = HOOKPROC(hook_callback)
    hook_handle = user32.SetWindowsHookExW(WH_KEYBOARD_LL, hook_proc, None, 0)
    if not hook_handle:
        log(f"hook failed {kernel32.GetLastError()}")
        return 1
    log(f"watching Ctrl+V label={workspace_label} target=focused-tab")
    message = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(message), None, 0, 0) != 0:
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))
    user32.UnhookWindowsHookEx(hook_handle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
