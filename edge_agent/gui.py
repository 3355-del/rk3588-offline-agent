"""Small local Chinese UI. All business actions run off Tk's event thread."""
import queue,threading,json,platform,os,uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,scrolledtext
from .agent import Agent
from .devices import capture,transcribe,speak,import_input,list_devices
from .runtime import LocalServer
from .doctor import report
from .alarms import query,readable,snapshot

class App:
    def __init__(self,root,config):
        self.root=root;self.c=config;self.agent=Agent(config);self.server=LocalServer(config)
        self.events=queue.Queue();self.busy=False;self.cancel=threading.Event();self.closed=False;self.closing=False;self.image=None;self.last_answer=''
        root.title('离线端侧智能体');root.geometry('1020x760');root.minsize(820,620)
        frame=ttk.Frame(root,padding=14);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='离线端侧智能体',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
        self.status=tk.StringVar(value='就绪 · '+config['backend'])
        ttk.Label(frame,textvariable=self.status).pack(anchor='w',pady=(4,10))
        self.log=scrolledtext.ScrolledText(frame,wrap='word',font=('Microsoft YaHei UI',11),state='disabled');self.log.pack(fill='both',expand=True)
        bar=ttk.Frame(frame);bar.pack(fill='x',pady=8)
        for label,fn in [('选择图片',self.choose_image),('拍照提问',self.photo),('录音提问',self.voice),('导入语音',self.audio_file),('播报回答',self.play),('设备自检',self.doctor),('最近告警',self.alarms)]:ttk.Button(bar,text=label,command=fn).pack(side='left',padx=2)
        bar2=ttk.Frame(frame);bar2.pack(fill='x')
        ttk.Label(bar2,text='告警事件ID：').pack(side='left');self.event_id=ttk.Entry(bar2,width=38);self.event_id.pack(side='left')
        ttk.Button(bar2,text='查看该告警截图',command=self.alarm_image).pack(side='left',padx=5)
        self.attachment=tk.StringVar(value='未附图片');ttk.Label(frame,textvariable=self.attachment).pack(anchor='w',pady=6)
        self.entry=tk.Text(frame,height=3,wrap='word',font=('Microsoft YaHei UI',11));self.entry.pack(fill='x');self.entry.bind('<Control-Return>',lambda e:self.send())
        bottom=ttk.Frame(frame);bottom.pack(fill='x',pady=(8,0))
        ttk.Button(bottom,text='发送（Ctrl+Enter）',command=self.send).pack(side='right')
        ttk.Button(bottom,text='停止',command=self.stop).pack(side='right',padx=6)
        ttk.Button(bottom,text='清空会话',command=self.reset).pack(side='left')
        ttk.Button(bottom,text='移除图片',command=self.clear_image).pack(side='left',padx=6)
        ttk.Button(bottom,text='设备设置',command=self.settings).pack(side='left',padx=6)
        self.say('说明','选择文件后会复制到本项目 inputs；只有点击拍照或录音才启动对应设备。模型启动和推理在本地进行。')
        root.protocol('WM_DELETE_WINDOW',self.close);root.after(100,self.poll)
    def say(self,who,text):
        self.log.configure(state='normal');self.log.insert('end',f'{who}：{text}\n\n')
        if int(self.log.index('end-1c').split('.')[0])>1000:self.log.delete('1.0','200.0')
        self.log.see('end');self.log.configure(state='disabled')
    def work(self,label,fn):
        if self.closing:return
        if self.busy:self.say('提示','当前操作尚未结束，请等待或点击停止。');return
        self.busy=True;self.cancel.clear();self.status.set(label)
        def worker():
            try:self.events.put(('result',fn()))
            except Exception as exc:self.events.put(('error',str(exc)))
            finally:self.events.put(('done',None))
        threading.Thread(target=worker,daemon=True).start()
    def poll(self):
        if self.closed:return
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='result' and value:
                    who,text=value;self.say(who,text)
                    if who=='助手':self.last_answer=text
                elif kind=='error':self.say('操作失败',value)
                elif kind=='done':self.busy=False;self.status.set('就绪 · '+self.c['backend'])
                elif kind=='image':self.image=value;self.attachment.set('已附图片：'+str(value.name))
        except queue.Empty:pass
        self.root.after(100,self.poll)
    def ask(self,text,image=None):
        if self.cancel.is_set():raise RuntimeError('已取消')
        self.server.start(self.cancel)
        if self.cancel.is_set():raise RuntimeError('已取消')
        answer=self.agent.ask(text,image)
        if self.cancel.is_set():raise RuntimeError('已取消')
        return '助手',answer
    def send(self):
        text=self.entry.get('1.0','end').strip()
        if not text:return
        if self.busy:self.say('提示','请等待当前操作结束。');return
        image=self.image;self.say('你',text+(' [附图片]' if image else ''));self.entry.delete('1.0','end');self.clear_image()
        self.work('正在加载模型 / 回答…',lambda:self.ask(text,image))
    def choose_image(self):
        if self.busy:return
        file=filedialog.askopenfilename(title='选择要分析的图片',filetypes=[('图片','*.png *.jpg *.jpeg')])
        if file:
            try:self.image=import_input(self.c,file);self.attachment.set('已附图片：'+self.image.name)
            except Exception as exc:self.say('错误',str(exc))
    def clear_image(self):self.image=None;self.attachment.set('未附图片')
    def photo(self):
        text=self.entry.get('1.0','end').strip() or '请描述摄像头拍到的画面。'
        self.work('正在拍照并分析…',lambda:self.ask(text,capture(self.c,'image',self.cancel)))
    def voice(self):
        def operation():
            text=transcribe(self.c,capture(self.c,'audio',self.cancel),self.cancel)
            if not text:raise RuntimeError('未识别到语音，请重试')
            self.events.put(('result',('语音识别',text)));return self.ask(text)
        self.work(f"正在录音（{self.c['audio_seconds']}秒）并识别…",operation)
    def audio_file(self):
        if self.busy:return
        file=filedialog.askopenfilename(title='选择16kHz单声道PCM语音',filetypes=[('PCM WAV','*.wav')])
        if not file:return
        def operation():
            text=transcribe(self.c,import_input(self.c,file,'audio'),self.cancel)
            if not text:raise RuntimeError('未识别到语音')
            self.events.put(('result',('语音识别',text)));return self.ask(text)
        self.work('识别音频并回答…',operation)
    def play(self):
        if not self.last_answer:self.say('提示','还没有可播报的回答。');return
        text=self.last_answer[:2000];self.work('正在播报…',lambda:(speak(text,self.c,self.cancel) or ('提示','播报结束')))
    def doctor(self):self.work('检查软件与部署文件…',lambda:('自检',json.dumps(report(self.c),ensure_ascii=False,indent=2)))
    def settings(self):
        if self.busy or self.closing:return
        dialog=tk.Toplevel(self.root);dialog.title('摄像头、麦克风与扬声器设置');dialog.transient(self.root);dialog.grab_set()
        fields={};suffix='linux' if platform.system()=='Linux' else 'windows'
        names=[('camera_'+suffix,'摄像头设备'),('audio_'+suffix,'麦克风设备'),('capture_width','采集宽度'),('capture_height','采集高度'),('audio_seconds','录音秒数')]
        if suffix=='linux':names.insert(2,('audio_output_linux','扬声器输出（ALSA）'))
        for row,(key,label) in enumerate(names):
            ttk.Label(dialog,text=label).grid(row=row,column=0,padx=10,pady=6)
            field=ttk.Entry(dialog,width=44);field.insert(0,str(self.c[key]));field.grid(row=row,column=1,padx=10);fields[key]=field
        ttk.Label(dialog,text='Windows填写设备显示名；Linux填写 /dev/videoN 与 ALSA 名称。').grid(row=len(names),columnspan=2,padx=10,pady=10)
        def enumerate_devices():
            dialog.destroy();self.work('列举设备（不录音、不拍照）…',lambda:('设备列表',list_devices(self.cancel)))
        def save():
            from .config import load
            target=Path(self.c['_config_path']);temp=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
            try:
                raw=json.loads(target.read_text(encoding='utf-8-sig'))
                for key,field in fields.items():raw[key]=int(field.get()) if key in ('capture_width','capture_height','audio_seconds') else field.get().strip()
                temp.write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf8');load(temp);os.replace(temp,target)
                self.c.update(load(target));dialog.destroy();self.say('提示','设备配置已保存。尚未启动任何采集。')
            except Exception as exc:self.say('配置未保存',str(exc))
            finally:temp.unlink(missing_ok=True)
        ttk.Button(dialog,text='列出设备',command=enumerate_devices).grid(row=len(names)+1,column=0,pady=10)
        ttk.Button(dialog,text='保存',command=save).grid(row=len(names)+1,column=1,pady=10)
    def alarms(self):self.work('查询告警…',lambda:('告警',readable(query(self.c))))
    def alarm_image(self):
        eid=self.event_id.get().strip()
        def operation():
            path,event=snapshot(self.c,eid)
            # Project one currently saves PPM; normalize explicitly for the VLM.
            from PIL import Image
            with Image.open(path) as im:
                converted=path.with_suffix('.png');im.convert('RGB').save(converted)
            self.events.put(('image',converted));return '提示','截图已附加，请输入问题并发送。检测告警不是视觉模型复核结论。'
        self.work('加载告警截图…',operation)
    def reset(self):
        if self.busy:return
        self.agent.reset();self.last_answer='';self.clear_image();self.say('提示','已清空会话记忆。')
    def stop(self):
        self.cancel.set();self.agent.cancel();self.status.set('正在停止本次操作…')
    def close(self):
        self.closing=True;self.stop();self.finish_close()
    def finish_close(self):
        if self.busy:self.root.after(100,self.finish_close);return
        self.closed=True;self.agent.close();self.server.close();self.root.destroy()

def main(config):
    root=tk.Tk();App(root,config);root.mainloop()
