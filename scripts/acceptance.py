"""Repeatable real-model acceptance. Generates fixtures; never captures devices."""
import argparse,json,sys,time,threading,uuid,platform
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from edge_agent.config import load
from edge_agent.agent import Agent
from edge_agent.runtime import LocalServer
from edge_agent.devices import synthesize,transcribe,ffmpeg_path
from edge_agent.process import run
from edge_agent.doctor import report

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',default=str(ROOT/'config/desktop.json'));p.add_argument('--tts',action='store_true');args=p.parse_args()
    c=load(args.config)
    if c['backend']=='mock':raise ValueError('真实验收拒绝mock后端')
    native_board=c['backend']=='rkllm_native' and platform.system()=='Linux' and platform.machine() in ('aarch64','arm64')
    server=LocalServer(c);a=None;results={'backend':c['backend'],'model':c['model'],'hardware_used':native_board,'peripherals_validated':False,'checks':[]}
    def check(name,fn,condition):
        t=time.monotonic();value=fn();ok=bool(condition(value));results['checks'].append({'name':name,'passed':ok,'seconds':round(time.monotonic()-t,3),'result':value})
        print(name,':',value,flush=True)
        if not ok:raise AssertionError(name+' failed')
    try:
        server.start();a=Agent(c)
        check('中文对话',lambda:a.ask('请用一句简短的中文介绍你能做什么。'),lambda x:bool(x) and '模拟模式' not in x)
        check('算术',lambda:a.ask('(23+17)*3-8'),lambda x:x=='112')
        check('真实设备状态',lambda:a.ask('你好，请查看设备状态。'),lambda x:'sensors_started' in x and 'false' in x)
        from PIL import Image,ImageDraw
        root=Path(c['input_dir'])/'validation'/uuid.uuid4().hex;root.mkdir(parents=True,exist_ok=True);fixture=root/'acceptance-shapes.png'
        image=Image.new('RGB',(448,448),'white');draw=ImageDraw.Draw(image);draw.rectangle((30,40,205,215),fill='red');draw.ellipse((270,270,420,420),fill='blue');image.save(fixture)
        check('真实视觉推理',lambda:a.ask('图片中有哪些颜色和形状？用中文回答。',fixture),lambda x:'红' in x and '蓝' in x and ('方' in x or '矩形' in x) and '圆' in x)
        if args.tts:
            source=synthesize(c,'你好，请查看设备状态。');wav=root/'acceptance-voice.wav'
            run([ffmpeg_path(),'-y','-i',str(source),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(wav)],30)
            check('真实中文语音识别',lambda:transcribe(c,wav),lambda x:'设备' in x.replace(' ','') and '状态' in x.replace(' ',''))
        # Exercise actual HTTP request cancellation, then prove the next request works.
        if c['backend']=='rkllm_http':
            errors=[]
            def long_request():
                try:a.ask('请详细列举一百种动物，并依次解释每一种动物的特点。')
                except Exception as exc:errors.append(str(exc))
            thread=threading.Thread(target=long_request);thread.start();time.sleep(.25);a.cancel();thread.join(6)
            if thread.is_alive():raise AssertionError('取消后请求没有及时退出')
            check('取消后恢复',lambda:a.ask('用两个字表示问候。'),lambda x:bool(x))
            results['checks'].append({'name':'取消请求','passed':bool(errors),'result':errors})
        results['doctor']=report(c)
    finally:
        try:
            if a is not None:a.close()
        finally:
            server.close();out=ROOT/'data/acceptance.json';out.parent.mkdir(exist_ok=True);out.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    if not all(x['passed'] for x in results['checks']):raise AssertionError('验收存在未通过项目')
    print('PASS：真实模型验收完成；'+('包含板卡原生NPU推理；' if native_board else '')+'未验证摄像头、真人录音及扬声器听感。')
if __name__=='__main__':main()
