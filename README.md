# Clipboard Image

Pastes clipboard images into the focused Herdr pane. Windows uses a foreground-aware Ctrl+V watcher. Linux provides an explicit action that reads images from Wayland with `wl-paste` or from X11 with `xclip`.

## Install

```sh
herdr plugin link /path/to/clipboard-image
herdr server reload-config
```

On Windows, the startup watcher intercepts Ctrl+V only while Herdr is focused. Invoke `clipboard-image.paste` to run the action directly.

On Linux desktops, invoke `clipboard-image.paste-linux`; it also accepts file URIs and text from the clipboard. A headless server cannot read the clipboard of the computer you are connecting from. Image paste during `herdr --remote` or a saved SSH machine is handled by the local Herdr client (`keys.remote_image_paste`, default `ctrl+v`), not by this plugin. The Windows Ctrl+V watcher runs only when the plugin is installed on that Windows machine.
