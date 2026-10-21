"""Actual RKLLM/RKNN subprocess adapter. No emulated inference on an SDK failure."""
import base64,io,tempfile,threading,time,uuid,shutil,json,math
from contextlib import contextmanager
from pathlib import Path
from .process import run

class NativeBackend:
    def __init__(self,config,cancel=None):
        self.config=config;self.cancel=cancel or threading.Event()
        self.last_metrics={}
        from .native_worker import NativeWorker
        self.worker=NativeWorker(config,self.cancel)
    def close(self):self.worker.close()
    @contextmanager
    def job(self,deadline):
        if not self.config.get('native_resident',True):
            with tempfile.TemporaryDirectory(prefix='edge-rkllm-') as folder:yield Path(folder)
            return
        root=self.worker.start(deadline)/uuid.uuid4().hex
        root.mkdir()
        try:yield root
        finally:shutil.rmtree(root,ignore_errors=True)
    def complete(self,messages,tools):
        self.last_metrics={}
        c=self.config
        for key in ('native_executable','rkllm_model'):
            if not Path(c[key]).is_file():raise RuntimeError(f'缺少 {key}: {c[key]}')
        lines=[];image=None
        for message in messages:
            content=message.get('content') or ''
            if isinstance(content,list):
                text=[]
                for part in content:
                    if part['type']=='text':text.append(part['text'])
                    elif part['type']=='image_url':
                        if image is not None:raise ValueError('每次最多一张图片')
                        url=part['image_url']['url']
                        if not url.startswith(('data:image/png;base64,','data:image/jpeg;base64,')):raise ValueError('只允许本地图片数据')
                        image=base64.b64decode(url.split(',',1)[1],validate=True)
                content='\n'.join(text)
            # rkllm_run supplies its own model chat template; flatten previous turns explicitly.
            lines.append(f"{message['role']}: {content}")
        prompt='以下是对话记录。请回答最后一条 user 消息。\n'+'\n'.join(lines)+'\nassistant:'
        if len(prompt.encode('utf8'))>60000:raise ValueError('上下文过长，请清空会话后重试')
        deadline=time.monotonic()+c['request_timeout']
        with self.job(deadline) as root:
            question=root/'prompt.txt';answer=root/'answer.txt';question.write_text(prompt,encoding='utf8');rgb='-'
            if image is not None:
                if not Path(c['rknn_vision_model']).is_file():raise RuntimeError('缺少 RKNN 视觉编码器模型')
                from PIL import Image,ImageOps
                Image.MAX_IMAGE_PIXELS=20_000_000
                with Image.open(io.BytesIO(image)) as im:
                    im=ImageOps.exif_transpose(im).convert('RGB')
                    im=ImageOps.pad(im,(c['vision_width'],c['vision_height']),method=Image.Resampling.BICUBIC,color=(0,0,0))
                    pixels=root/'rgb.bin';pixels.write_bytes(im.tobytes());rgb=str(pixels)
            if c.get('native_resident',True):self.worker.submit(root,deadline)
            else:
                run([c['native_executable'],c['rkllm_model'],c['rknn_vision_model'],str(question),rgb,
                     str(c['vision_width']),str(c['vision_height']),str(answer),str(c['max_tokens']),str(c['context_tokens'])],c['request_timeout'],self.cancel)
            if not answer.is_file() or answer.stat().st_size>1024*1024:raise RuntimeError('RKLLM 未生成有效回答文件')
            text=answer.read_text(encoding='utf8').strip()
            if not text:raise RuntimeError('RKLLM 返回空回答')
            metrics=answer.with_name(answer.name+'.metrics.json')
            if metrics.exists():
                if metrics.stat().st_size>4096:raise RuntimeError('Invalid native metrics size')
                value=json.loads(metrics.read_text(encoding='utf8'))
                first,total=value.get('native_first_text_ms'),value.get('native_total_ms')
                if any(type(x) not in (int,float) or not math.isfinite(x) for x in (first,total)) or not 0<=first<=total:
                    raise RuntimeError('Invalid native timing metrics')
                self.last_metrics=value
            return {'role':'assistant','content':text}
