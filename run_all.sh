#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pytest -q tests
python3 -m promofinder run samples/the_cleaner_was_the_heiress.zip --out outputs/demo
