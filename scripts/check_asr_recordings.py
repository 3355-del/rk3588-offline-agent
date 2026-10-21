"""Replay existing recordings without acquiring audio devices or invoking an LLM."""
import argparse
import json
import re
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from edge_agent.config import load
from edge_agent.devices import transcribe
from edge_agent.process import Cancelled


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True)
    parser.add_argument('--audio',action='append',required=True)
    parser.add_argument('--expected',required=True,help='Ground truth shared by the supplied recordings')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    config=load(args.config);rows=[]
    normalized=lambda text:re.sub(r'[^\w]','',text)
    for path in args.audio:
        start=time.monotonic();text=transcribe(config,path)
        row=dict(kind='recording',file=str(path),text=text,wall_seconds=time.monotonic()-start,
                 passed=normalized(text)==normalized(args.expected))
        rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    with tempfile.TemporaryDirectory(dir=config['input_dir'],prefix='asr-check-') as folder:
        path=Path(folder)/'silence.wav'
        with wave.open(str(path),'wb') as wav:
            wav.setparams((1,2,16000,0,'NONE','not compressed'));wav.writeframes(b'\0\0'*80000)
        text=transcribe(config,path)
        rows.append(dict(kind='digital_silence',text=text,passed=not text.strip()))
        stop=threading.Event();stop.set();start=time.monotonic()
        try:transcribe(config,path,stop);cancelled=False
        except Cancelled:cancelled=True
        rows.append(dict(kind='cancellation',passed=cancelled,wall_seconds=time.monotonic()-start))
    report=dict(backend=config['asr_backend'],results=rows,passed=all(row['passed'] for row in rows))
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS' if report['passed'] else 'FAIL',flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':sys.exit(main())
