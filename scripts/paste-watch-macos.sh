#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$script_dir/.." && pwd)
source="$script_dir/paste-watch-macos.swift"
bin="$root/bin/paste-watch-macos"

mkdir -p "$root/bin"
if [ ! -x "$bin" ] || [ "$source" -nt "$bin" ]; then
    swiftc -O -o "$bin" "$source" -framework AppKit -framework ApplicationServices
fi

state=${HERDR_PLUGIN_STATE_DIR:-${XDG_STATE_HOME:-"$HOME/.local/state"}/herdr/plugins/clipboard-image}
mkdir -p "$state"
pid_file="$state/watch.pid"
if [ -f "$pid_file" ]; then
    old_pid=$(cat "$pid_file" 2>/dev/null || true)
    if [ "$old_pid" != "$$" ] && printf '%s' "$old_pid" | grep -Eq '^[0-9]+$'; then
        old_command=$(ps -p "$old_pid" -o args= 2>/dev/null || true)
        if printf '%s' "$old_command" | grep -q 'paste-watch-macos'; then
            kill "$old_pid" 2>/dev/null || true
        fi
    fi
fi

export HERDR_PLUGIN_ROOT="${HERDR_PLUGIN_ROOT:-$root}"
echo "$$" >"$pid_file"
exec "$bin" watch
