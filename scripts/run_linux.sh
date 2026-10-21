#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
mode="${1:---cpu}"
case "$mode" in
  --cpu) config=config/linux-cpu.json ;;
  --npu) config=config/rk3588-native.json ;;
  *) echo 'Usage: bash scripts/run_linux.sh --cpu|--npu [chat|gui|doctor]'; exit 2 ;;
esac
if (( $# > 0 )); then shift; fi
if (( $# == 0 )); then set -- chat; fi
exec .venv-linux/bin/python -X utf8 -m edge_agent --config "$config" "$@"
