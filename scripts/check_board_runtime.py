"""Explicit CPU board smoke/steady run using only local model HTTP service."""
import argparse,json,sys,time,urllib.request,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from edge_agent.agent import Agent
from edge_agent.config import load
from edge_agent.runtime import LocalServer

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=int,default=180)
    args=parser.parse_args()
    if not 10<=args.seconds<=3600:raise ValueError('seconds must be 10..3600')
    c=load(ROOT/'config/linux-cpu.json');c['max_tokens']=96
    server=LocalServer(c);report={'backend':c['backend'],'checks':[],'samples':[],'completed':False}
    stop=threading.Event();monitor=None
    def sample():
        while not stop.wait(1):
            row={'seconds':round(time.monotonic()-start,2)}
            if server.child:
                try:
                    lines=Path(f'/proc/{server.child.pid}/status').read_text().splitlines()
                    row['server_rss_kib']=int(next(x for x in lines if x.startswith('VmRSS:')).split()[1])
                except (OSError,StopIteration):pass
            try:row['soc_celsius']=int(Path('/sys/class/thermal/thermal_zone0/temp').read_text())/1000
            except OSError:pass
            report['samples'].append(row)
    start=time.monotonic()
    try:
        server.start();report['startup_seconds']=round(time.monotonic()-start,3)
        monitor=threading.Thread(target=sample);monitor.start();agent=Agent(c)
        # Separate streaming probe measures server first-token latency, not GUI latency.
        payload={'model':c['model'],'messages':[{'role':'user','content':'请用一句话解释什么是摄像头。'}],'max_tokens':48,'stream':True}
        req=urllib.request.Request(c['server_url']+'/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        begin=time.monotonic();first=None;chunks=0
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req,timeout=c['request_timeout']) as response:
            for line in response:
                if line.startswith(b'data: ') and b'[DONE]' not in line:
                    event=json.loads(line[6:]);choices=event.get('choices',[])
                    if choices and choices[0].get('delta',{}).get('content'):
                        if first is None:first=time.monotonic()-begin
                        chunks+=1
        if first is None:raise AssertionError('no streamed text')
        report['stream_probe']={'first_content_seconds':round(first,3),'total_seconds':round(time.monotonic()-begin,3),'text_chunks':chunks,'note':'chunks are not token counts; measures direct model service, not non-streaming chat UI'}
        camera_log=ROOT/'data/camera-capture-20261002.log'
        if camera_log.exists():
            picture=Path(camera_log.read_text().strip());begin=time.monotonic()
            answer=agent.ask('简短描述图片中的物品。不推测人物身份。',picture)
            if not answer.strip():raise AssertionError('empty camera answer')
            report['checks'].append({'name':'camera-image-inference','passed':True,'seconds':round(time.monotonic()-begin,3),'answer_chars':len(answer),'note':'nonempty output only; semantic correctness requires user review'})
        event=ROOT/'data/integration/result.json'
        if event.exists():
            record=json.loads(event.read_text());answer=agent.ask('这张告警图片中是否有人？简短回答。',Path(record['screenshot']))
            report['checks'].append({'name':'alarm-snapshot-inference','passed':bool(answer.strip()),'event_id':record['event_id'],'answer':answer})
        steady=time.monotonic();rounds=0
        while time.monotonic()-steady<args.seconds:
            agent.reset();begin=time.monotonic()
            answer=agent.ask('请用一句简短的中文说明保持设备散热的作用。')
            if not answer.strip():raise AssertionError('empty steady response')
            rounds+=1
            report['checks'].append({'name':'steady-text','passed':True,'round':rounds,'seconds':round(time.monotonic()-begin,3)})
        report['steady_seconds']=round(time.monotonic()-steady,3);report['rounds']=rounds
        report['completed']=all(x['passed'] for x in report['checks'])
    finally:
        stop.set()
        if monitor:monitor.join()
        server.close();report['total_seconds']=round(time.monotonic()-start,3)
        (ROOT/'data/board-runtime-20261002.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('checks','samples')},ensure_ascii=False))

if __name__=='__main__':main()
