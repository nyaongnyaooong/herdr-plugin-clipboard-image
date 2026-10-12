# Clipboard Image

Pastes clipboard images into the focused Herdr pane. Windows uses a foreground-aware Ctrl+V watcher. macOS watches Cmd+V while Herdr's terminal is focused and also accepts an explicit paste action. Linux provides an explicit action that reads images from Wayland with `wl-paste` or from X11 with `xclip`.

## Install

```sh
herdr plugin link /path/to/clipboard-image
herdr server reload-config
```

On Windows, the startup watcher intercepts Ctrl+V only while Herdr is focused. Invoke `clipboard-image.paste` to run the action directly.

On macOS, the startup watcher intercepts Cmd+V while a terminal hosting Herdr is frontmost and the window title matches the workspace or a saved machine. The first run asks for Accessibility permission; grant it to the paste watcher, then press Cmd+V again. Invoke `clipboard-image.paste-macos` to paste the current image, file, or text without the watcher. Swift is required to compile the watcher.

On Linux desktops, invoke `clipboard-image.paste-linux`; it also accepts file URIs and text from the clipboard. A headless server cannot read the clipboard of the computer you are connecting from. Herdr bridges image paste during `herdr --remote`. For a saved SSH machine, this plugin's Windows watcher detects the remote machine from the active Herdr window and transfers the clipboard image over its saved SSH target. Codex CLI receives a bracketed paste of the remote image path, which its composer can turn into an image attachment. Cursor CLI receives a workspace-relative `@path` file reference, following Cursor's documented CLI workaround. Cursor images are copied to `herdr-clipboard-images` under the pane's working directory. The watcher removes staged images after the CLI starts processing the submitted turn; unsent files older than 48 hours are cleaned on the next paste. The same `@path` handling applies to local Cursor CLI panes. The watcher must be installed on the Windows or macOS client.
