#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
mode="${1:---cpu}"
case "$mode" in --cpu|--npu) ;; *) echo '请选择 --cpu 或 --npu'; exit 2 ;; esac
exec bash scripts/run_linux.sh "$mode" console
