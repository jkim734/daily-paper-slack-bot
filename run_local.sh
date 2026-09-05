#!/usr/bin/env bash
# ==============================================================================
# 로컬 Mac/Linux 스케줄러 실행용 스크립트
# ==============================================================================

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

mkdir -p logs

if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo "--- Run started at $(date) ---" >> logs/daily.log
python3 main.py "$@" >> logs/daily.log 2>&1
echo "--- Run finished at $(date) ---" >> logs/daily.log
