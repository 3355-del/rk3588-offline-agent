"""Explicit on-board test: project-one NPU file detection -> project-two event/snapshot.

Uses isolated outputs and an existing non-private detection fixture; no sensor capture.
"""
import argparse
import importlib.util
import json
import sys
import subprocess
import threading
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from edge_agent.config import load
from edge_agent.alarms import query,snapshot

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project-one',type=Path,default=Path('/path/to/project'))
    args=parser.parse_args();p=args.project_one.resolve()
    c=load(ROOT/'config/linux-cpu.json')
    root=ROOT/'data/integration';root.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('integration_receiver',p/'tools/alarm_receiver.py')
    rx=importlib.util.module_from_spec(spec);spec.loader.exec_module(rx)
    rx.initialize(c['alarm_db'])
    before={r['event_id'] for r in query(c,limit=100)['alarms']}
    with rx.AlarmServer(('127.0.0.1',0),rx.Handler) as server:
        server.database=c['alarm_db'];thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        cfg=json.loads((p/'evidence/single_dma_native/config.json').read_text())
        cfg.update(fps=15,run_seconds=8,screenshot_dir=c['alarm_screenshot_dir'])
        cfg['alarm'].update(port=server.server_address[1],outbox_dir=str(root/'outbox'))
        cfg['streams'][0]['source_uri']=str(p/'fixtures/person_h264.mp4')
        conf=root/'project-one.json';conf.write_text(json.dumps(cfg),encoding='utf8')
        try:
            with (root/'project-one.log').open('w') as log:
                subprocess.run([str(p/'build/multi_stream_alarm_demo'),str(conf)],cwd=p,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=40)
            events=[r for r in query(c,limit=100)['alarms'] if r['event_id'] not in before]
            if not events:raise AssertionError('no new committed hardware alarms')
            event=events[0];picture,payload=snapshot(c,event['event_id'])
            if payload.get('event_id')!=event['event_id']:raise AssertionError('event id mismatch')
            from PIL import Image
            with Image.open(picture) as im:im.verify()
            result={'passed':True,'new_events':len(events),'event_id':event['event_id'],'screenshot':str(picture),'source':'project-one real NPU inference on existing person_h264 file'}
            (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
            print(json.dumps(result,ensure_ascii=False))
        finally:server.shutdown();thread.join()

if __name__=='__main__':main()
