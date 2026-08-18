#!/bin/bash
# start.sh — Wrapper script chuyển tiếp tới python main.py

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

python main.py "$@"
