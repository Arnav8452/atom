#!/usr/bin/env bash
# Rebuild assets/atom/ with unified code-generated sprites.
# Needs python-cairo + ffmpeg.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 tools/render_all.py "$@"
