"""A bounded local HTTP backend, compatible with the RKLLM text server API."""
import base64,json,re,urllib.request,threading,tempfile,sys
from pathlib import Path
from .process import run
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('model service redirect refused')
class Backend:
    def __init__(self,config,cancel=None):self.config=config;self.cancel=cancel or threading.Event();self.native=None
    def close(self):
        if self.native:self.native.close();self.native=None
    def complete(self,messages,tools):
        if self.cancel.is_set():raise RuntimeError('已取消')
        if self.config['backend']=='rkllm_native':
            from .native_backend import NativeBackend
            if self.native is None:self.native=NativeBackend(self.config,self.cancel)
            return self.native.complete(messages,tools)
        if self.config['backend']=='mock':
            if messages[-1]['role']=='tool':return {'role':'assistant','content':'[模拟调度；工具结果是真实本地数据] '+messages[-1]['content']}
            text=messages[-1]['content']
            if isinstance(text,list):return {'role':'assistant','content':'[模拟模式] 图片已接收，但未运行视觉模型，不能判断图片中的物体。'}
            tool='recent_alarms' if any(x in text for x in ['告警','报警']) else 'device_status' if any(x in text for x in ['设备','状态','配置']) else None
            if tool:return {'role':'assistant','content':None,'tool_calls':[{'id':'mock_1','type':'function','function':{'name':tool,'arguments':'{}'}}]}
            return {'role':'assistant','content':'[模拟模式] 已收到：'+text+'。当前用于验证交互流程，尚未运行真实语言模型。'}
        payload={'model':self.config['model'],'messages':messages,'stream':False,'max_tokens':self.config['max_tokens'],'temperature':.2}
        if tools and self.config.get('enable_tools',True):payload['tools']=tools
        with tempfile.TemporaryDirectory(prefix='edge-http-') as folder:
            job=Path(folder)/'request.json';out=Path(folder)/'response.json'
            job.write_text(json.dumps({'url':self.config['server_url'].rstrip('/')+'/v1/chat/completions','timeout':self.config['request_timeout'],'payload':payload},ensure_ascii=False),encoding='utf8')
            run([sys.executable,'-X','utf8','-m','edge_agent.http_worker',str(job),str(out)],self.config['request_timeout']+3,self.cancel)
            if not out.is_file() or out.stat().st_size>2*1024*1024:raise ValueError('invalid response file')
            result=json.loads(out.read_text(encoding='utf8'))
        if 'error' in result:
            if result.get('value_error'):raise ValueError(result['error'])
            raise RuntimeError('本地模型请求失败：'+result['error'])
        msg=result['response']['choices'][0]['message']
        if not isinstance(msg,dict):raise ValueError('invalid model response')
        content=msg.get('content')
        if content is not None and not isinstance(content,str):raise ValueError('invalid model content')
        # Official Qwen server may return tool calls as XML-wrapped JSON in text.
        if not msg.get('tool_calls') and content and '<tool_call>' in content:
            calls=[]
            for i,chunk in enumerate(re.findall(r'<tool_call>\s*(.*?)\s*</tool_call>',content,re.S)):
                item=json.loads(chunk);calls.append({'id':f'local_{i}','type':'function','function':{'name':item['name'],'arguments':json.dumps(item.get('arguments',{}))}})
            if not calls:raise ValueError('malformed tool call')
            msg={'role':'assistant','content':None,'tool_calls':calls}
        return {'role':'assistant','content':msg.get('content'),'tool_calls':msg.get('tool_calls',[])}
