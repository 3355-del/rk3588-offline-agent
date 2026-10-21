"""Verify both real binaries refuse conflicting leases BEFORE SDK initialization."""
import fcntl,hashlib,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from edge_agent.config import load

def main():
    out=ROOT/'data'/('conflict-guard-'+time.strftime('%Y%m%d-%H%M%S'));out.mkdir()
    c=load(ROOT/'config/rk3588-native.json')
    prompt=out/'prompt.txt';prompt.write_text('请说你好',encoding='utf8')
    binary=Path(c['native_executable']).resolve()
    p1=Path('/path/to/project')
    cfg=json.loads((p1/'evidence/single_dma_native/config.json').read_text())
    cfg.update(run_seconds=1,screenshot_dir=str(out/'shots'))
    cfg['alarm']['outbox_dir']=str(out/'outbox')
    cfg['streams'][0]['source_uri']=str(p1/'fixtures/person_h264.mp4')
    conf=out/'p1.json';conf.write_text(json.dumps(cfg))
    commands=[('p1-blocked-by-exclusive',fcntl.LOCK_EX,[str(p1/'build/multi_stream_alarm_demo'),str(conf)],p1),
      ('p2-blocked-by-shared',fcntl.LOCK_SH,[str(binary),c['rkllm_model'],c['rknn_vision_model'],str(prompt),'-',
        str(c['vision_width']),str(c['vision_height']),str(out/'answer.txt'),'64','4096'],ROOT)]
    rows=[]
    with os.fdopen(os.open('/run/lock/rk3588-projects-npu.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o660),'a') as lock:
        for name,mode,command,cwd in commands:
            fcntl.flock(lock,mode|fcntl.LOCK_NB)
            try:
                start=time.monotonic()
                r=subprocess.run(command,cwd=cwd,capture_output=True,text=True,timeout=15)
            finally:fcntl.flock(lock,fcntl.LOCK_UN)
            log=r.stdout+r.stderr;(out/(name+'.log')).write_text(log)
            row={'case':name,'exit_code':r.returncode,'seconds':round(time.monotonic()-start,3),
                 'executable':command[0],'executable_sha256':hashlib.sha256(Path(command[0]).read_bytes()).hexdigest(),
                 'passed':r.returncode!=0 and 'NPU occupied by an incompatible project session' in log}
            rows.append(row)
            (out/'result.json').write_text(json.dumps(rows,indent=2))
            if not row['passed']:raise AssertionError(log)
    print(out);print(json.dumps(rows,indent=2))

if __name__=='__main__':main()
