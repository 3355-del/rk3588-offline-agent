"""Real native NPU probe. Uses generated pixels; never records peripherals."""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from edge_agent.config import load
from edge_agent.agent import Agent


def main():
    c = load(ROOT / 'config/rk3588-native.json')
    out = ROOT / 'data/npu-20261002'
    out.mkdir(parents=True, exist_ok=True)
    from PIL import Image, ImageDraw
    im = Image.new('RGB', (c['vision_width'], c['vision_height']), 'white')
    d = ImageDraw.Draw(im)
    d.rectangle((30, 40, 205, 215), fill='red')
    d.ellipse((270, 270, 420, 420), fill='blue')
    rgb = out / 'probe.rgb'
    rgb.write_bytes(im.tobytes())
    prompt = out / 'prompt.txt'
    prompt.write_text('图片中有哪些颜色和形状？用一句中文回答。', encoding='utf8')
    answer = out / 'answer.txt'
    command = [c['native_executable'], c['rkllm_model'], c['rknn_vision_model'],
               str(prompt), str(rgb), str(c['vision_width']), str(c['vision_height']),
               str(answer), '96', str(c['context_tokens'])]
    started = time.monotonic()
    samples = []
    with (out / 'native-runtime.log').open('w') as log:
        p = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            while p.poll() is None:
                if time.monotonic() - started > 180:
                    raise TimeoutError('native probe exceeded 180 seconds')
                sample = {'elapsed': round(time.monotonic() - started, 3)}
                for key, path in [('npu_load', '/sys/kernel/debug/rknpu/load'),
                                  ('temperature', '/sys/class/thermal/thermal_zone0/temp')]:
                    try:
                        sample[key] = Path(path).read_text().strip()
                    except OSError:
                        pass
                try:
                    sample['rss_kib'] = next(int(x.split()[1]) for x in
                        Path(f'/proc/{p.pid}/status').read_text().splitlines() if x.startswith('VmRSS:'))
                except (OSError, StopIteration):
                    pass
                samples.append(sample)
                time.sleep(1)
        finally:
            if p.poll() is None:
                p.kill()
            p.wait()
    result = {'exit_code': p.returncode, 'seconds': round(time.monotonic()-started, 3),
              'samples': samples, 'peripherals_validated': False}
    (out / 'probe.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    if p.returncode:
        raise RuntimeError('native inference failed; see native-runtime.log')
    text = answer.read_text(encoding='utf8')
    result['answer'] = text
    assert '红' in text and '蓝' in text and '圆' in text, text
    a = Agent(c)
    errors = []
    def request():
        try:
            a.ask('请详细介绍一百种动物。')
        except Exception as exc:
            errors.append(str(exc))
    t = threading.Thread(target=request)
    t.start()
    time.sleep(2)
    cancel_start = time.monotonic()
    a.cancel()
    t.join(8)
    result['cancel_seconds'] = round(time.monotonic()-cancel_start, 3)
    result['cancel_passed'] = not t.is_alive() and bool(errors)
    result['cancel_errors'] = errors
    assert result['cancel_passed'], result
    result['recovery_answer'] = a.ask('请只用两个汉字向我问好。')
    assert result['recovery_answer'].strip()
    (out / 'probe.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='samples'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
