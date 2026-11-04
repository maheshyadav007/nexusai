#!/usr/bin/env bash
# Unix entry point for deployment profiles, hosting and publication. Windows builds use desktop.cmd.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
pins="$repo/desktop/toolchain.json"
node_version=$(sed -n 's/.*"node": "\([^"]*\)".*/\1/p' "$pins")
case $(uname -s) in Linux) platform=linux ;; Darwin) platform=darwin ;; *) echo 'Use desktop.cmd on Windows.' >&2; exit 1 ;; esac
case $(uname -m) in x86_64) arch=x64 ;; arm64|aarch64) arch=arm64 ;; *) echo 'Unsupported architecture.' >&2; exit 1 ;; esac
tools="$repo/.release/tools"
mkdir -p "$tools"
if ! command -v node >/dev/null || [[ $(node --version) != "v$node_version" ]]; then
  archive="node-v${node_version}-${platform}-${arch}.tar.gz"
  node_dir="$tools/node-v${node_version}-${platform}-${arch}"
  if [[ ! -x $node_dir/bin/node ]]; then
    curl --fail --location --retry 2 "https://nodejs.org/dist/v${node_version}/SHASUMS256.txt" -o "$tools/node-checksums.txt"
    curl --fail --location --retry 2 "https://nodejs.org/dist/v${node_version}/$archive" -o "$tools/$archive"
    expected=$(awk -v name="$archive" '$2 == name {print $1}' "$tools/node-checksums.txt")
    if command -v sha256sum >/dev/null; then actual=$(sha256sum "$tools/$archive" | awk '{print $1}'); else actual=$(shasum -a 256 "$tools/$archive" | awk '{print $1}'); fi
    [[ -n $expected && $actual == "$expected" ]] || { echo 'Node checksum mismatch.' >&2; exit 1; }
    tar -xzf "$tools/$archive" -C "$tools"
  fi
  export PATH="$node_dir/bin:$PATH"
fi
cd "$repo/desktop"
npm ci --ignore-scripts --no-audit --no-fund
node release.cjs "$@"
