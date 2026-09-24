# Clipboard Image

Pastes clipboard images into the focused Herdr pane. Windows uses a foreground-aware Ctrl+V watcher. Linux provides an explicit action that reads images from Wayland with `wl-paste` or from X11 with `xclip`.

## Install

```sh
herdr plugin link /path/to/clipboard-image
herdr server reload-config
```

On Windows, the startup watcher intercepts Ctrl+V only while Herdr is focused. Invoke `clipboard-image.paste` to run the action directly.

On Linux desktops, invoke `clipboard-image.paste-linux`; it also accepts file URIs and text from the clipboard. A headless server cannot read a local desktop clipboard. When using `herdr --remote`, Herdr bridges the connecting client's image clipboard to the remote pane.
