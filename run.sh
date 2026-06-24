#!/bin/sh

PROJECT="$PWD"
VENV="$PROJECT/.venv/bin/python3"

LOG_DIR="$PROJECT/logs"
timestamp=$(date '+%Y%m%d %H%M')
export LOG_FILE="$LOG_DIR/$timestamp.log"

mkdir -p "$LOG_DIR"
ls -1t "$LOG_DIR" | tail -n +9 | xargs -I {} rm -f "$LOG_DIR/{}"

echo "Script start @ $(date)"
$VENV -u run.py "$@"
echo "Script done @ $(date)"
