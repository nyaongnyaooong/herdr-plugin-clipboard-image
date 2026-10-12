#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$script_dir/.." && pwd)
source="$script_dir/paste-watch-macos.swift"
bin="$root/bin/paste-watch-macos"

mkdir -p "$root/bin"
swiftc -O -o "$bin" "$source" -framework AppKit -framework ApplicationServices
chmod +x "$bin"
