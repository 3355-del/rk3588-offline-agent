"""Bounded P2 NPU-only or P1 NPU + P2 CPU soak. No sensor acquisition."""
import argparse,hashlib,importlib.util,json,os,subprocess,sys,threading,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from edge_agent.agent import Agent
from edge_agent.config import load
from edge_agent.alarms import query,snapshot
from edge_agent.runtime import LocalServer

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--seconds',type=int,default=3600)
    parser.add_argument('--project-one',type=Path,default=Path('/path/to/project'))
    parser.add_argument('--mode',choices=['npu-alone','cpu-joint'],default='npu-alone',help='Do not run two NPU runtimes concurrently on this driver')
    args=parser.parse_args()
    if not 30<=args.seconds<=7200:raise ValueError('seconds must be 30..7200')
    out=ROOT/'data'/('joint-soak-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
    out.mkdir(parents=True);print(str(out),flush=True)
    joint=args.mode=='cpu-joint'
    c=load(ROOT/('config/linux-cpu.json' if joint else 'config/rk3588-native.json'))
    c.update(max_tokens=64,alarm_db=str(out/'alarms.sqlite3'),alarm_screenshot_dir=str(out/'shots'),input_dir=str(out/'inputs'))
    Path(c['input_dir']).mkdir()
    from PIL import Image,ImageDraw
    fixture=Path(c['input_dir'])/'shapes.png'
    im=Image.new('RGB',(448,448),'white');d=ImageDraw.Draw(im)
    d.rectangle((30,40,205,215),fill='red');d.ellipse((270,270,420,420),fill='blue');im.save(fixture)
    p1=args.project_one.resolve()
    spec=importlib.util.spec_from_file_location('soak_receiver',p1/'tools/alarm_receiver.py')
    rx=importlib.util.module_from_spec(spec);spec.loader.exec_module(rx);rx.initialize(c['alarm_db'])
    report={'completed':False,'mode':args.mode,'seconds_requested':args.seconds,'peripherals_used':False,
        'project_one_fps_target':5 if joint else None,'project_one_source':'existing person_h264.mp4' if joint else None,
        'rounds':0,'text_rounds':0,'vision_rounds':0,'alarm_checks':0,'model_pid':None,
        'max_rss_kib':0,'min_rss_kib':None,'max_temperature_c':0,'errors':[],
        'code_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
         ['edge_agent/native_worker.py','edge_agent/native_backend.py','native/edge_rkllm.cpp','scripts/check_joint_soak.py']}}
    a=Agent(c);model_server=LocalServer(c);child=None;monitor=None;stop=threading.Event();guard=[]
    def save():
        temp=out/'progress.tmp';temp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');os.replace(temp,out/'progress.json')
    def sample():
        with (out/'samples.jsonl').open('w') as file:
            while not stop.wait(2):
                row={'elapsed':round(time.monotonic()-start,3)}
                try:
                    row['temperature_c']=int(Path('/sys/class/thermal/thermal_zone0/temp').read_text())/1000
                    report['max_temperature_c']=max(report['max_temperature_c'],row['temperature_c'])
                    if row['temperature_c']>=85:guard.append('SoC temperature >=85C');a.cancel();return
                    native=a.backend.native
                    model_child=model_server.child if joint else native.worker.child if native else None
                    if model_child:
                        pid=model_child.pid
                        lines=Path(f'/proc/{pid}/status').read_text().splitlines()
                        row['rss_kib']=int(next(s for s in lines if s.startswith('VmRSS:')).split()[1])
                        if report['rounds']>=10:
                            report['max_rss_kib']=max(report['max_rss_kib'],row['rss_kib'])
                            report['min_rss_kib']=min(report['min_rss_kib'] or row['rss_kib'],row['rss_kib'])
                    row['npu_load']=Path('/sys/kernel/debug/rknpu/load').read_text().strip()
                except (OSError,StopIteration):pass
                file.write(json.dumps(row)+'\n');file.flush()
    with rx.AlarmServer(('127.0.0.1',0),rx.Handler) as server, (out/'project-one.log').open('w') as p1log, (out/'requests.jsonl').open('w') as requests:
        server.database=c['alarm_db'];receiver=threading.Thread(target=server.serve_forever,daemon=True);receiver.start()
        cfg=json.loads((p1/'evidence/single_dma_native/config.json').read_text())
        cfg.update(fps=5,run_seconds=args.seconds,screenshot_dir=c['alarm_screenshot_dir'])
        cfg['alarm'].update(host='127.0.0.1',port=server.server_address[1],outbox_dir=str(out/'outbox'))
        cfg['streams'][0]['source_uri']=str(p1/'fixtures/person_h264.mp4')
        conf=out/'project-one.json';conf.write_text(json.dumps(cfg),encoding='utf8')
        start=time.monotonic();last_save=0
        try:
            model_server.start()
            if joint and model_server.child is None:
                raise RuntimeError('A pre-existing CPU server occupies the test port; close it or select an isolated port before this test')
            start=time.monotonic()
            if joint:
                child=subprocess.Popen([str(p1/'build/multi_stream_alarm_demo'),str(conf)],cwd=p1,stdout=p1log,stderr=subprocess.STDOUT)
                report['project_one_pid']=child.pid
            monitor=threading.Thread(target=sample,daemon=True);monitor.start()
            while time.monotonic()-start<args.seconds:
                if guard:raise RuntimeError(guard[-1])
                if child and child.poll() is not None and time.monotonic()-start<args.seconds-2:
                    raise RuntimeError('project one exited before requested duration: '+str(child.returncode))
                visual=report['rounds']%10==0;a.reset();begin=time.monotonic()
                answer=a.ask('图片有哪些颜色和形状？用一句中文回答。' if visual else '请只用两个汉字向我问好。',fixture if visual else None)
                if not answer.strip() or visual and not ('红' in answer and '蓝' in answer and '圆' in answer):raise AssertionError('unexpected model answer: '+answer)
                pid=model_server.child.pid if joint else a.backend.native.worker.child.pid
                if report['model_pid'] is None:report['model_pid']=pid
                if pid!=report['model_pid']:raise AssertionError('resident process changed unexpectedly')
                row={'elapsed':round(time.monotonic()-start,3),'kind':'vision' if visual else 'text','seconds':round(time.monotonic()-begin,3),'answer':answer}
                requests.write(json.dumps(row,ensure_ascii=False)+'\n');requests.flush()
                report['rounds']+=1;report['vision_rounds' if visual else 'text_rounds']+=1
                if joint and (report['rounds']==1 or report['rounds']%20==0):
                    events=query(c,limit=1)['alarms']
                    if events:
                        event=events[0];picture,payload=snapshot(c,event['event_id'])
                        if payload.get('event_id')!=event['event_id']:raise AssertionError('event ID mismatch')
                        with Image.open(picture) as check:check.verify()
                        report['alarm_checks']+=1;report['last_event_id']=event['event_id']
                report['elapsed_seconds']=round(time.monotonic()-start,3)
                if report['elapsed_seconds']-last_save>=15:save();last_save=report['elapsed_seconds']
                time.sleep(.2)
            if child:
                report['project_one_exit_code']=child.wait(timeout=45)
                if child.returncode:raise RuntimeError('project one failed')
                if not report['alarm_checks']:raise AssertionError('no committed event/snapshot verified')
            if guard:raise RuntimeError(guard[-1])
            report['elapsed_seconds']=round(time.monotonic()-start,3)
            report['completed']=True
        except BaseException as exc:
            report['errors'].append(type(exc).__name__+': '+str(exc));raise
        finally:
            stop.set()
            if monitor:monitor.join(5)
            native_child=model_server.child if joint else a.backend.native.worker.child if a.backend.native else None
            a.close();model_server.close();report['model_reaped']=native_child is None or native_child.poll() is not None
            if child and child.poll() is None:
                child.terminate()
                try:child.wait(10)
                except subprocess.TimeoutExpired:child.kill();child.wait(5)
            server.shutdown();receiver.join();save()
            (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
