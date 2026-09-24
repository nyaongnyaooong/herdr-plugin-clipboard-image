# Clipboard Image

Herdr plugin that saves a clipboard image into a temporary file and inserts its path into the focused pane. Text paste falls back to Herdr's focused-pane input.

## Install from a local checkout

```sh
herdr plugin link /path/to/clipboard-image
herdr server reload-config
```

The Windows plugin includes a startup watcher that intercepts Ctrl+V while Herdr is focused. The action can also be invoked as `clipboard-image.paste`.