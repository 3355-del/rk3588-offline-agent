import base64,copy,http.server,json,sqlite3,tempfile,threading,unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from edge_agent.config import load
from edge_agent.agent import Agent
from edge_agent.backend import Backend
from edge_agent.tools import execute
from edge_agent.devices import capture

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.c=load(Path(__file__).resolve().parents[1]/'config/mock.json');self.c['input_dir']=str(self.root);self.c['alarm_db']=str(self.root/'alarms.sqlite3')
    def test_mock_honesty(self):
        a=Agent(self.c);self.assertIn('模拟',a.ask('你好'));self.assertIn('sensors_started',a.ask('设备状态'));self.assertIn('尚未创建',a.ask('告警'))
    def test_image_and_traversal(self):
        p=self.root/'test.png';p.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jP1sAAAAASUVORK5CYII='))
        a=Agent(self.c);self.assertIn('未运行视觉模型',a.ask('看图',p))
        with self.assertRaises(ValueError):a.ask('看图',Path(__file__))
        a.config=dict(self.c,backend='rkllm_http')
        with self.assertRaises(ValueError):a.ask('看图',p)
    def test_tool_allowlist(self):
        for n,args in [('shell',{}),('recent_alarms',{'limit':True}),('recent_alarms',{'path':'secret'}),('device_status',{'extra':1})]:
            with self.assertRaises(ValueError):execute(n,args,self.c)
    def test_read_only_alarms(self):
        with closing(sqlite3.connect(self.c['alarm_db'])) as db,db:
            db.execute('CREATE TABLE alarms(id INTEGER PRIMARY KEY,event_id TEXT,payload TEXT,received_at TEXT)')
            db.execute('INSERT INTO alarms VALUES(1,?,?,?)',('a',json.dumps({'class_name':'person','screenshot':'test.png'}),'now'))
        result=execute('recent_alarms',{},self.c);self.assertEqual(result['alarms'][0]['event']['class_name'],'person')
    def test_tool_loop_bound_and_history(self):
        class Forever:
            def complete(self,m,t):return {'role':'assistant','tool_calls':[{'id':'a','function':{'name':'device_status','arguments':'{}'}}]}
        a=Agent(self.c,Forever())
        with self.assertRaises(RuntimeError):a.ask('test')
        self.assertEqual(a.turns,[]);self.assertFalse(a.lock.locked())
        a=Agent(self.c)
        for _ in range(20):a.ask('hello')
        self.assertEqual(len(a.turns),self.c['history_turns']);a.reset();self.assertEqual(a.turns,[])
    def test_busy_rejected(self):
        a=Agent(self.c);a.lock.acquire()
        try:
            with self.assertRaises(RuntimeError):a.ask('test')
        finally:a.lock.release()
    def test_config(self):
        from edge_agent.config import DEFAULT
        original=json.loads(DEFAULT.read_text(encoding='utf-8-sig'))
        for k,v in [('server_url','https://example.com'),('server_url','http://localhost:8080'),('server_url','http://127.0.0.1:8080/evil'),('request_timeout',True),('max_tokens',0),('supports_images','yes')]:
            bad=dict(original);bad[k]=v;p=self.root/'bad.json';p.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):load(p)
    def test_capture_is_explicit_and_bounded(self):
        with patch('edge_agent.devices.ffmpeg_path',return_value=None),patch('edge_agent.devices.run') as run:
            with self.assertRaises(RuntimeError):capture(self.c,'image')
            run.assert_not_called()
    def test_http_adapter_and_redirect(self):
        requests=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body)
                if body['messages'][-1]['content']=='redirect':self.send_response(302);self.send_header('Location','https://example.com');self.end_headers();return
                response={'choices':[{'message':{'role':'assistant','content':'<tool_call>{"name":"device_status","arguments":{}}</tool_call>'}}]};data=json.dumps(response).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def log_message(self,*args):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            backend=Backend(dict(self.c,backend='rkllm_http',server_url=f'http://127.0.0.1:{server.server_port}'))
            msg=backend.complete([{'role':'user','content':'test'}],[]);self.assertEqual(msg['tool_calls'][0]['function']['name'],'device_status');self.assertFalse(requests[0]['stream'])
            with self.assertRaises(ValueError):backend.complete([{'role':'user','content':'redirect'}],[])
        finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':unittest.main()
