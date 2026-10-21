"""Explicit Linux device failure/cancellation checks; no physical unplug claim."""
import json,sys,tempfile,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from edge_agent.config import load
from edge_agent.devices import capture
from edge_agent.process import Cancelled

def main():
    c=load(ROOT/'config/linux-cpu.json');results=[]
    with tempfile.TemporaryDirectory(prefix='device-check-',dir=c['input_dir']) as folder:
        c['input_dir']=folder
        for kind,key,value in [('image','camera_linux','/dev/edge_agent_missing_camera'),('audio','audio_linux','hw:999,0')]:
            broken=dict(c);broken[key]=value;begin=time.monotonic()
            try:capture(broken,kind)
            except RuntimeError:pass
            else:raise AssertionError('invalid device unexpectedly succeeded')
            if list(Path(folder).iterdir()):raise AssertionError('failed capture left output')
            results.append({'check':kind+' invalid-device cleanup','passed':True,'seconds':round(time.monotonic()-begin,3)})
        cancel=threading.Event();timer=threading.Timer(.7,cancel.set);timer.start()
        try:
            try:capture(dict(c,audio_seconds=10),'audio',cancel)
            except Cancelled:pass
            else:raise AssertionError('recording cancellation did not propagate')
        finally:timer.cancel();timer.join()
        if list(Path(folder).iterdir()):raise AssertionError('cancelled recording left output')
        results.append({'check':'active microphone cancellation and cleanup','passed':True})
        audio=capture(dict(c,audio_seconds=1),'audio')
        if not audio.is_file():raise AssertionError('microphone did not recover')
        results.append({'check':'microphone works after cancellation','passed':True})
    (ROOT/'data/device-recovery-20261002.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results))

if __name__=='__main__':main()
