"""Own only the model server started here; never stop a pre-existing server."""
import json,socket,subprocess,time,urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from .backend import NoRedirect
from .bounded_log import BoundedLog

def health(config):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    try:
        with opener.open(config['server_url'].rstrip('/')+'/health',timeout=2) as r:
            value=json.loads(r.read(16384))
        return value.get('status')=='ok'
    except (OSError,ValueError):return False

class LocalServer:
    def __init__(self,config):self.c=config;self.child=None;self.log=None
    def start(self,cancel=None):
        if self.c['backend']!='rkllm_http' or 'llama_executable' not in self.c:return
        u=urlsplit(self.c['server_url'])
        with socket.socket(socket.AF_INET6 if ':' in u.hostname else socket.AF_INET) as s:
            occupied=s.connect_ex((u.hostname,u.port or 80))==0
        if occupied:
            if health(self.c):return
            raise RuntimeError('模型服务端口被占用且未就绪，请检查已启动的服务')
        for key in ('llama_executable','gguf_model','gguf_projector'):
            if not Path(self.c[key]).is_file():raise RuntimeError(f'缺少 {key}，请运行 scripts/setup_assets.py')
        root=Path(__file__).resolve().parents[1]/'data';root.mkdir(exist_ok=True)
        self.log=BoundedLog(root/'model-server.log')
        c=self.c;args=[c['llama_executable'],'-m',c['gguf_model'],'--mmproj',c['gguf_projector'],'--host',u.hostname,'--port',str(u.port or 80),'--alias',c['model'],'-c',str(c['context_tokens']),'-n',str(c['max_tokens']),'-t',str(c['cpu_threads']),'-ngl','0','--no-mmproj-offload','--parallel','1']
        try:
            self.child=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.log.start(self.child.stdout)
            deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                if cancel and cancel.is_set():raise RuntimeError('已取消模型加载')
                if self.log.error:raise RuntimeError('模型日志写入失败：'+str(self.log.error))
                if self.child.poll() is not None:raise RuntimeError('模型服务启动失败，详见 data/model-server.log')
                if health(c):return
                time.sleep(.2)
            raise TimeoutError('模型加载超时，详见 data/model-server.log')
        except BaseException:self.close();raise
    def close(self):
        if self.child and self.child.poll() is None:
            self.child.terminate()
            try:self.child.wait(timeout=5)
            except subprocess.TimeoutExpired:self.child.kill();self.child.wait(timeout=5)
        self.child=None
        if self.log:self.log.close();self.log=None
