"""Download pinned offline ASR weights; no audio is sent to any service."""
import concurrent.futures
import hashlib
import json
import time
import urllib.request
import urllib.error
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REV = '2365baeacb507f821a0c8120fcee3d484dba7a07'
REPO = 'csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17'
SHA256 = 'c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51'
SIZE = 239233841


def digest(path):
    with path.open('rb') as f:
        h = hashlib.sha256()
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mirror', action='store_true', help='Use hf-mirror.com; official model SHA256 is still mandatory')
    args = parser.parse_args()
    host = 'hf-mirror.com' if args.mirror else 'huggingface.co'
    base = f'https://{host}/{REPO}/resolve/{REV}/'
    text_base = f'https://{host}/{REPO}/raw/{REV}/'
    root = ROOT/'models/sensevoice-int8'
    root.mkdir(parents=True, exist_ok=True)
    target = root/'model.int8.onnx'
    if not target.exists() or digest(target) != SHA256:
        parts = ROOT/'models/asr-staging/sensevoice-parts'
        parts.mkdir(parents=True, exist_ok=True)
        chunk = 1024 * 1024
        def fetch(start):
            end = min(SIZE, start + chunk) - 1
            part = parts/str(start)
            if part.exists() and part.stat().st_size == end-start+1:
                return part
            for attempt in range(3):
                try:
                    request = urllib.request.Request(base+f'model.int8.onnx?download=true&part={start}', headers={'Range':f'bytes={start}-{end}'})
                    with urllib.request.urlopen(request, timeout=30) as response:
                        if response.status != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{SIZE}':
                            raise RuntimeError('server returned an unexpected range')
                        data = response.read(end-start+2)
                    if len(data) != end-start+1:
                        raise RuntimeError('incomplete model chunk')
                    part.write_bytes(data)
                    return part
                except Exception:
                    if attempt == 2: raise
                    time.sleep(1)
        starts = list(range(0, SIZE, chunk))
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(fetch, start) for start in starts]
            for count, task in enumerate(concurrent.futures.as_completed(futures), 1):
                task.result()
                if count % 16 == 0 or count == len(starts):
                    print(f'Downloaded {count}/{len(starts)} chunks', flush=True)
        staging = root/'model.verified-download.part'
        with staging.open('wb') as output:
            for start in starts:
                output.write((parts/str(start)).read_bytes())
        if digest(staging) != SHA256:
            raise RuntimeError('SHA256 mismatch; model NOT activated')
        staging.replace(target)
        for start in starts:
            (parts/str(start)).unlink()
        parts.rmdir()
    for name in ('tokens.txt', 'README.md'):
        destination = root/name
        if not destination.exists():
            try:
                with urllib.request.urlopen(text_base+name, timeout=30) as response:
                    data = response.read(2 * 1024 * 1024)
            except urllib.error.HTTPError as exc:
                # Some mirrors reject urllib's user agent for raw text.
                if exc.code != 403 or not shutil.which('curl'):raise
                data = subprocess.run(['curl','-fLsS','--connect-timeout','8',
                    '--max-time','30','--max-filesize','2097152',text_base+name],
                    check=True,capture_output=True,timeout=35).stdout
            if not data or data.lstrip().startswith(b'<!DOCTYPE'):
                raise RuntimeError(f'invalid {name}')
            temp = root/(name+'.part')
            temp.write_bytes(data)
            temp.replace(destination)
    lines = (root/'tokens.txt').read_text(encoding='utf-8').splitlines()
    if len(lines) != 25055 or any(int(line.rsplit(' ',1)[1]) != index for index,line in enumerate(lines)):
        raise RuntimeError('unexpected token table; configuration was not changed')
    (root/'provenance.json').write_text(json.dumps(dict(repository=REPO,revision=REV,download_host=host,
        official_model_sha256=SHA256,files={name:digest(root/name) for name in ('model.int8.onnx','tokens.txt','README.md')}),indent=2),encoding='utf-8')
    print('SenseVoice model verified. Application configuration was not changed.',flush=True)


if __name__ == '__main__':
    main()
