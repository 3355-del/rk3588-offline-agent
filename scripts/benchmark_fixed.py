"""Small fixed real-model suite on Linux board; no peripheral capture.

Scores are exact task checks, not a general model-accuracy benchmark.
"""
import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from edge_agent.agent import Agent
from edge_agent.config import load
from edge_agent.runtime import LocalServer


def percentile(values, p):
    if not values: return None
    ordered=sorted(values)
    return ordered[max(0, math.ceil(p*len(ordered))-1)]


def snapshot():
    def read(p):
        try: return p.read_text().strip()
        except OSError: return None
    thermal={p.parent.name:read(p) for p in Path('/sys/class/thermal').glob('thermal_zone*/temp')}
    cpu={p.parent.name:read(p) for p in Path('/sys/devices/system/cpu/cpufreq').glob('policy*/scaling_cur_freq')}
    cooling={p.parent.name:read(p) for p in Path('/sys/class/thermal').glob('cooling_device*/cur_state')}
    return {'temperature_millic':thermal,'cpu_frequency_khz':cpu,'cooling_state':cooling,
            'npu_load':read(Path('/sys/kernel/debug/rknpu/load'))}


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def provenance(executable):
    p=Path(executable).resolve()
    result={'executable':str(p),'sha256':sha(p),'libraries':{}}
    run=subprocess.run(['ldd',str(p)],capture_output=True,text=True,timeout=10)
    result['ldd']=run.stdout;result['ldd_exit_code']=run.returncode
    for line in run.stdout.splitlines():
        words=line.split()
        if '=>' in words:
            name=words[words.index('=>')+1]
            if name.startswith('/') and Path(name).is_file():result['libraries'][name]=sha(name)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    parser.add_argument('--repeats',type=int,default=3)
    args=parser.parse_args()
    if platform.system()!='Linux' or platform.machine() not in ('aarch64','arm64'):
        raise RuntimeError('This benchmark must run on the Linux ARM board')
    if not 1<=args.repeats<=10:parser.error('repeats must be 1..10')
    c=load(args.config)
    if c['backend'] not in ('rkllm_native','rkllm_http'):raise ValueError('Real backend required')
    out=ROOT/'data'/('fixed-eval-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
    out.mkdir();print(out,flush=True)
    c.update(input_dir=str(out),max_tokens=64)
    from PIL import Image,ImageDraw
    cases=[]
    for name,color,shape,expected in [('red-square','red','square',['红','方']),('blue-circle','blue','circle',['蓝','圆']),('green-triangle','green','triangle',['绿','三角'])]:
        image=Image.new('RGB',(448,448),'white');draw=ImageDraw.Draw(image)
        if shape=='square':draw.rectangle((100,100,348,348),fill=color)
        elif shape=='circle':draw.ellipse((100,100,348,348),fill=color)
        else:draw.polygon([(224,80),(70,360),(378,360)],fill=color)
        path=out/(name+'.png');image.save(path)
        cases.append((name,'vision','图中彩色图形是什么颜色、什么形状？只用一句中文回答。',path,expected))
    cases += [('translation','text','请把英文单词 apple 翻译成中文，只回答译文。',None,['苹果']),
              ('capital','text','中国的首都是哪座城市？只回答城市名。',None,['北京'])]
    report={'completed':False,'backend':c['backend'],'config_sha256':sha(args.config),'cases':[],
            'first_token_note':'Native first nonempty text callback is measured inside the C++ request (includes lazy model/vision initialization); not GUI display latency. CPU non-streaming first token is unmeasured.',
            'scope':'Synthetic shapes and two fixed text questions; keyword checks are not general accuracy or mAP.',
            'thermal_note':'Frequency/cooling snapshots do not alone establish absence or cause of throttling.'}
    report['script_sha256']=sha(__file__)
    report['effective_parameters']={key:c.get(key) for key in ('max_tokens','context_tokens','cpu_threads','vision_width','vision_height','native_resident')}
    report['repeats']=args.repeats
    report['percentile_method']='nearest rank; warm summary excludes the entire first pass; small samples only'
    report['cache_note']='Process started anew; OS page cache was not cleared. Repeated images/prompts may benefit from runtime caches.'
    report['fixtures']={p.name:sha(p) for p in out.glob('*.png')}
    report['runtime']=provenance(c['native_executable'] if c['backend']=='rkllm_native' else c['llama_executable'])
    a=Agent(c);server=LocalServer(c);stop=threading.Event();monitor=None;child=None
    def sample():
        with (out/'samples.jsonl').open('w') as f:
            while not stop.is_set():
                row=snapshot();row['monotonic']=time.monotonic()
                if child is not None:
                    try:
                        row['rss_kib']=int(next(x for x in Path(f'/proc/{child.pid}/status').read_text().splitlines() if x.startswith('VmRSS:')).split()[1])
                    except (OSError,StopIteration):pass
                f.write(json.dumps(row)+'\n');f.flush()
                temps=[int(x) for x in row['temperature_millic'].values() if x is not None]
                if temps and max(temps)>=80000:a.cancel();stop.set()
                stop.wait(1)
    try:
        temps=[int(x) for x in snapshot()['temperature_millic'].values() if x is not None]
        if temps and max(temps)>=65000:raise RuntimeError('Board too warm to start; wait for cooling')
        monitor=threading.Thread(target=sample,daemon=True);monitor.start()
        start=time.monotonic()
        if c['backend']=='rkllm_native':
            from edge_agent.native_backend import NativeBackend
            a.backend.native=NativeBackend(c,a.cancel_event)
            a.backend.native.worker.start(time.monotonic()+c['request_timeout'])
            child=a.backend.native.worker.child
        else:
            server.start(a.cancel_event);child=server.child
            if child is None:raise RuntimeError('Refuse to reuse an existing server; isolated loading measurement required')
        report['service_ready_seconds']=time.monotonic()-start
        report['load_timing_note']=('Native ready marker precedes lazy model initialization; first request includes initialization.'
                                   if c['backend']=='rkllm_native' else 'HTTP service health readiness includes server loading.')
        for repeat in range(args.repeats):
            for name,kind,prompt,image,expected in cases:
                if stop.is_set():raise RuntimeError('Thermal guard stopped benchmark')
                a.reset();start=time.monotonic();answer=a.ask(prompt,image)
                report['cases'].append({'id':name,'kind':kind,'repeat':repeat,'phase':'warm' if repeat else 'first_pass','seconds':time.monotonic()-start,
                                        'prompt':prompt,
                                        'answer':answer,'expected_keywords':expected,'passed':all(x in answer for x in expected)})
                if a.backend.native:report['cases'][-1]['native_metrics']=a.backend.native.last_metrics
                print(name,report['cases'][-1]['seconds'],report['cases'][-1]['passed'],flush=True)
        report['completed']=True
    except BaseException as exc:
        report['error']=type(exc).__name__+': '+str(exc)
        raise
    finally:
        try:a.close()
        finally:
            server.close();stop.set()
            if monitor:monitor.join(5)
            report['model_exit_code']=child.poll() if child else None
            report['first_request_seconds']=report['cases'][0]['seconds'] if report['cases'] else None
            report['summary_warm']={kind:{'n':len(values),'p50_seconds':percentile(values,.5),'p95_seconds':percentile(values,.95)}
                               for kind in ('text','vision')
                               for values in [[x['seconds'] for x in report['cases'] if x['kind']==kind and x['phase']=='warm']]}
            report['checks_passed']=sum(x['passed'] for x in report['cases'])
            (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':main()
