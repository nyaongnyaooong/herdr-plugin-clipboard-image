# Clipboard Image

Pastes clipboard images into the focused Herdr pane. Windows uses a foreground-aware Ctrl+V watcher. Linux provides an explicit action that reads images from Wayland with `wl-paste` or from X11 with `xclip`.

## Install

```sh
herdr plugin link /path/to/clipboard-image
herdr server reload-config
```

On Windows, the startup watcher intercepts Ctrl+V only while Herdr is focused. Invoke `clipboard-image.paste` to run the action directly.

On Linux desktops, invoke `clipboard-image.paste-linux`; it also accepts file URIs and text from the clipboard. A headless server cannot read the clipboard of the computer you are connecting from. Herdr bridges image paste during `herdr --remote`. For a saved SSH machine, this plugin's Windows watcher detects the selected machine and transfers the clipboard image over that machine's saved SSH target. Codex CLI receives a bracketed paste of the remote image path, which its composer can turn into an image attachment. Cursor CLI receives a workspace-relative `@path` file reference, following Cursor's documented CLI workaround. Cursor images are copied to `herdr-clipboard-images` under the pane's working directory; files older than 48 hours are removed on the next paste. The same `@path` handling applies to local Cursor CLI panes. The watcher must be installed on the Windows client.
