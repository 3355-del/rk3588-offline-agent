import unittest,tempfile,sys,threading,time,json,sqlite3,subprocess
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
from edge_agent.config import load
from edge_agent.agent import Agent
from edge_agent.arithmetic import calculate
from edge_agent.process import run,Cancelled
from edge_agent.alarms import query,snapshot
from edge_agent.native_backend import NativeBackend

class BusinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.c=load(Path(__file__).resolve().parents[1]/'config/mock.json');self.c.update(input_dir=str(self.root/'inputs'),alarm_db=str(self.root/'alarms.sqlite3'),alarm_screenshot_dir=str(self.root/'shots'))
    def test_real_arithmetic_without_llm(self):
        a=Agent(self.c);self.assertEqual(a.ask('1+3'),'4');self.assertEqual(a.ask('计算 (5+3)÷2'),'4')
        for expression in ('__import__("os").system("whoami")','1<<2','2**999999','[1]*1000','float("nan")'):
            with self.assertRaises((ValueError,SyntaxError)):calculate(expression)
        with self.assertRaises(ZeroDivisionError):calculate('1/0')
    def test_timeout_cancellation_and_process_exit(self):
        started=time.monotonic()
        with self.assertRaises(TimeoutError):run([sys.executable,'-c','import time;time.sleep(30)'],.15)
        self.assertLess(time.monotonic()-started,4)
        stop=threading.Event();timer=threading.Timer(.15,stop.set);timer.start()
        try:
            with self.assertRaises(Cancelled):run([sys.executable,'-c','import time;time.sleep(30)'],20,stop)
        finally:timer.join()
        self.assertEqual(run([sys.executable,'-c','print("alive")'],5).strip(),'alive')
    def test_alarm_filter_and_screenshot_confinement(self):
        (self.root/'shots').mkdir();(self.root/'shots/one.ppm').write_bytes(b'P6\n1 1\n255\n\xff\x00\x00')
        with closing(sqlite3.connect(self.c['alarm_db'])) as db,db:
            db.execute('CREATE TABLE alarms(id INTEGER PRIMARY KEY,event_id TEXT,payload TEXT,received_at TEXT)')
            for i in range(30):db.execute('INSERT INTO alarms VALUES(?,?,?,?)',(i,str(i),json.dumps({'stream_id':i%2,'timestamp_ms':i,'screenshot':'one.ppm'}),'now'))
            db.execute('INSERT INTO alarms VALUES(?,?,?,?)',(99,'bad',json.dumps({'screenshot':'../outside.png'}),'now'))
        rows=query(self.c,3,stream_id=0,since_ms=20)['alarms'];self.assertEqual([r['event_id'] for r in rows],['28','26','24'])
        dest,_=snapshot(self.c,'1');self.assertTrue(dest.is_file())
        with self.assertRaises(ValueError):snapshot(self.c,'bad')
    def test_capture_error_removes_partial_file(self):
        from edge_agent.devices import capture
        c=dict(self.c,camera_windows='test camera',camera_linux='/dev/test')
        def fail(args,*unused):Path(args[-1]).write_bytes(b'partial');raise RuntimeError('unplugged')
        with patch('edge_agent.devices.ffmpeg_path',return_value='ffmpeg'),patch('edge_agent.devices.run',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'unplugged'):capture(c,'image')
        self.assertEqual(list(Path(c['input_dir']).iterdir()),[])
    def test_native_protocol_without_hardware(self):
        # Fixture verifies file protocol only. It does NOT claim an NPU inference pass.
        model=self.root/'llm.rkllm';model.write_bytes(b'fixture')
        c=dict(self.c,native_resident=False,native_executable=sys.executable,rkllm_model=str(model),rknn_vision_model=str(self.root/'vision.rknn'))
        def adapter(args,*unused):
            self.assertEqual(args[4],'-');self.assertIn('hello',Path(args[3]).read_text(encoding='utf8'));Path(args[7]).write_text('protocol ok',encoding='utf8')
        with patch('edge_agent.native_backend.run',side_effect=adapter):self.assertEqual(NativeBackend(c).complete([{'role':'user','content':'hello'}],[])['content'],'protocol ok')
    def test_chinese_exit(self):
        result=subprocess.run([sys.executable,'-X','utf8','-m','edge_agent','--config','config/mock.json','chat'],input='退出\n',text=True,encoding='utf8',capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0);self.assertNotIn('已收到',result.stdout)

if __name__=='__main__':unittest.main()
