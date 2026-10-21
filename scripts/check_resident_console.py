"""Scripted menu smoke test, no microphone or camera access."""
import subprocess,time,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'data/resident-20261003'
out.mkdir(parents=True,exist_ok=True)
with (out/'console.log').open('w') as log:
    p=subprocess.Popen(['bash','scripts/board_console.sh','--npu'],cwd=ROOT,
        stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,text=True)
    try:
        p.communicate('1\n请只用两个汉字向我问好。\n请只用两个汉字向我问好。\n/reset\n/quit\n6\n0\n',timeout=120)
    except BaseException:
        p.kill();p.wait();raise
text=(out/'console.log').read_text()
assert p.returncode==0,text[-2500:]
assert text.count('助手：')==2 and '已清空' in text and 'rkllm_native' in text,text
print('PASS console chat, reset, return to menu, doctor, exit')
