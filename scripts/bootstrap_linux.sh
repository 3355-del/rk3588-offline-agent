#!/usr/bin/env bash
# Run from the project copied onto Debian/Ubuntu ARM64. Never flashes a board.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
mode="${1:---cpu}"
if [[ "$mode" != --cpu && "$mode" != --npu ]]; then echo 'Usage: bash scripts/bootstrap_linux.sh --cpu|--npu'; exit 2; fi
for program in python3 cmake c++ ffmpeg espeak-ng aplay; do
  if ! command -v "$program" >/dev/null; then
    echo "Missing $program. On Debian/Ubuntu install: python3-venv python3-tk build-essential cmake ffmpeg espeak-ng alsa-utils libgomp1"
    exit 1
  fi
done
if ! python3 -c 'import tkinter' >/dev/null 2>&1; then
  echo 'GUI unavailable: install python3-tk. CLI deployment can continue.'
fi
if [[ "$(uname -m)" != aarch64 ]]; then echo 'This deployment script targets ARM64 Linux.'; exit 1; fi
python3 -m venv .venv-linux
.venv-linux/bin/python -m pip install -r requirements.txt
.venv-linux/bin/python -X utf8 -m unittest discover -s tests -v
if [[ "$mode" == --cpu ]]; then
  if [[ ! -f runtime/llama-source/CMakeLists.txt ]]; then echo 'Missing pinned llama-source folder; copy the prepared runtime/llama-source from the PC.'; exit 1; fi
  cmake -S runtime/llama-source -B runtime/llama-linux -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=OFF -DLLAMA_OPENSSL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_APP=OFF -DLLAMA_USE_PREBUILT_UI=OFF
  cmake --build runtime/llama-linux --target llama-server -j 4
  config=config/linux-cpu.json
else
  cmake -S native -B native/build -DCMAKE_BUILD_TYPE=Release
  cmake --build native/build -j 4
  config=config/rk3588-native.json
fi
.venv-linux/bin/python -c 'import json,sys; c=json.load(open(sys.argv[1])); sys.exit(0 if c.get("tts_linux")=="piper" else 1)' "$config" && use_piper=yes || use_piper=no
if [[ "$use_piper" == yes ]]; then
  .venv-linux/bin/python -m pip install -r requirements-linux-voice.txt
  .venv-linux/bin/python scripts/setup_piper.py
fi
.venv-linux/bin/python -c 'import json,sys; c=json.load(open(sys.argv[1])); sys.exit(0 if c.get("asr_backend")=="sensevoice" else 1)' "$config" && use_sensevoice=yes || use_sensevoice=no
if [[ "$use_sensevoice" == yes ]]; then
  .venv-linux/bin/python -m pip install -r requirements-asr.txt
  .venv-linux/bin/python scripts/setup_sensevoice.py
fi
.venv-linux/bin/python -X utf8 -m edge_agent --config "$config" doctor
echo "Build finished. Verify the doctor output, then run: .venv-linux/bin/python -X utf8 -m edge_agent --config $config chat"
echo 'USB devices are configured separately. No camera/microphone has been started.'
