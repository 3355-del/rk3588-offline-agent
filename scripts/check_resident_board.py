"""Same-input resident/one-shot comparison and bounded real-NPU reliability run."""
import argparse,json,sys,time,threading,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from edge_agent.agent import Agent
from edge_agent.config import load

def main():
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=180);args=p.parse_args()
    if not 10<=args.seconds<=3600:raise ValueError('seconds must be 10..3600')
    out=ROOT/'data/resident-20261003';out.mkdir(parents=True,exist_ok=True)
    c=load(ROOT/'config/rk3588-native.json');c['max_tokens']=64
    from PIL import Image,ImageDraw
    image=Path(c['input_dir'])/'resident-validation.png'
    im=Image.new('RGB',(448,448),'white');d=ImageDraw.Draw(im)
    d.rectangle((30,40,205,215),fill='red');d.ellipse((270,270,420,420),fill='blue');im.save(image)
    report={'completed':False,'peripherals_used':False,'max_tokens':64,'runs':[],'samples':[]}
    def save(): (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    a=None
    try:
        for resident in (False,True):
            a=Agent(dict(c,native_resident=resident))
            for kind in ('text','vision'):
                for repeat in range(4):
                    a.reset();start=time.monotonic()
                    answer=a.ask('请只用两个汉字向我问好。' if kind=='text' else '图片有哪些颜色和形状？用一句中文回答。',image if kind=='vision' else None)
                    row={'resident':resident,'kind':kind,'repeat':repeat,'seconds':round(time.monotonic()-start,3),'answer':answer}
                    if resident:row['pid']=a.backend.native.worker.child.pid
                    report['runs'].append(row);save();print(json.dumps(row,ensure_ascii=False),flush=True)
                    assert answer.strip()
                    if kind=='vision':assert '红' in answer and '蓝' in answer and '圆' in answer,answer
            if not resident:a.close();a=None
        worker=a.backend.native.worker;original_pid=worker.child.pid
        assert len({x['pid'] for x in report['runs'] if x['resident']})==1
        start=time.monotonic();rounds=0
        while time.monotonic()-start<args.seconds:
            a.reset()
            visual=rounds%10==0
            answer=a.ask('图片有哪些颜色和形状？用一句中文回答。' if visual else '请只用两个汉字向我问好。',image if visual else None)
            assert answer.strip()
            if visual:assert '红' in answer and '蓝' in answer and '圆' in answer
            assert worker.child.pid==original_pid
            row={'elapsed':round(time.monotonic()-start,3),'pid':original_pid}
            lines=Path(f'/proc/{original_pid}/status').read_text().splitlines()
            row['rss_kib']=int(next(x for x in lines if x.startswith('VmRSS:')).split()[1])
            row['temperature_c']=int(Path('/sys/class/thermal/thermal_zone0/temp').read_text())/1000
            report['samples'].append(row);rounds+=1;save()
        report['steady']={'rounds':rounds,'seconds':round(time.monotonic()-start,3)}
        errors=[]
        def long_request():
            try:a.ask('请详细介绍一百种动物。')
            except Exception as exc:errors.append(str(exc))
        t=threading.Thread(target=long_request);t.start();time.sleep(.5)
        before=time.monotonic();a.cancel();t.join(8)
        report['cancel']={'seconds':round(time.monotonic()-before,3),'errors':errors}
        assert not t.is_alive() and errors
        a.reset();report['after_cancel']=a.ask('请只用两个汉字向我问好。')
        assert worker.child.pid!=original_pid and report['after_cancel']
        before_timeout=worker.child
        a.config['request_timeout']=.01
        try:a.ask('请详细介绍一百种动物。')
        except TimeoutError:report['timeout_passed']=True
        else:raise AssertionError('expected actual worker timeout')
        assert before_timeout.poll() is not None
        a.config['request_timeout']=c['request_timeout']
        a.reset();report['after_timeout']=a.ask('请只用两个汉字向我问好。')
        child=worker.child;a.close();a=None
        report['close_reaped']=child.poll() is not None
        assert report['close_reaped'] and report['after_timeout']
        report['completed']=True
    finally:
        if a:a.close()
        save()
    print('PASS resident NPU benchmark, reuse, stability, cancel, timeout, close',flush=True)

if __name__=='__main__':main()
