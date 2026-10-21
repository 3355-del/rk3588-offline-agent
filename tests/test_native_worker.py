"""Exercise process ownership and failure recovery without requiring an NPU."""
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from edge_agent.native_worker import NativeWorker
from edge_agent.process import Cancelled
from edge_agent.backend import Backend

FAKE = '''
import sys,time,os
from pathlib import Path
root=Path(sys.argv[-1]);(root/'ready').write_text('edge-resident-v1')
for line in sys.stdin:
    job=root/line.strip();text=(job/'prompt.txt').read_text(encoding='utf-8')
    if text=='crash':sys.exit(9)
    if text=='sleep':time.sleep(30)
    (job/'answer.txt').write_text(str(os.getpid()))
    (job/'answer.txt.metrics.json').write_text('{"native_first_text_ms":'+('3' if 'badmetrics' in text else '1')+',"native_total_ms":2}')
    (job/'done').write_text('0')
'''


class NativeWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.script=Path(self.tmp.name)/'worker.py'
        self.script.write_text(FAKE)
        real_popen=subprocess.Popen
        self.patch=patch('edge_agent.native_worker.subprocess.Popen',
            side_effect=lambda args,**kw:real_popen([sys.executable,str(self.script),args[-1]],**kw))
        self.patch.start()
        self.cancel=threading.Event()
        self.worker=NativeWorker(dict(native_executable='fake',rkllm_model='fake',
            rknn_vision_model='fake',vision_width=448,vision_height=448,max_tokens=32,context_tokens=4096),self.cancel)

    def tearDown(self):
        self.worker.close();self.patch.stop();self.tmp.cleanup()

    def job(self,text):
        root=self.worker.start(time.monotonic()+5)
        job=root/uuid.uuid4().hex;job.mkdir();(job/'prompt.txt').write_text(text,encoding='utf-8')
        return job

    def test_reuses_pid_and_close_reaps_process(self):
        job=self.job('one');child=self.worker.child
        self.worker.submit(job,time.monotonic()+5)
        first=(job/'answer.txt').read_text()
        job2=self.job('two');self.worker.submit(job2,time.monotonic()+5)
        self.assertEqual(first,(job2/'answer.txt').read_text())
        root=Path(self.worker.folder.name);self.worker.close()
        self.assertEqual(child.returncode,0);self.assertFalse(root.exists())

    def test_timeout_releases_and_next_request_recovers(self):
        job=self.job('sleep');child=self.worker.child
        begin=time.monotonic()
        with self.assertRaises(TimeoutError):self.worker.submit(job,time.monotonic()+.15)
        self.assertLess(time.monotonic()-begin,2.5)
        self.assertIsNotNone(child.poll())
        job=self.job('recovered');self.worker.submit(job,time.monotonic()+5)
        self.assertTrue((job/'answer.txt').exists())

    def test_cancel_releases_and_recovers(self):
        job=self.job('sleep');child=self.worker.child
        self.cancel.set()
        with self.assertRaises(Cancelled):self.worker.submit(job,time.monotonic()+5)
        self.assertIsNotNone(child.poll());self.cancel.clear()
        job=self.job('recovered');self.worker.submit(job,time.monotonic()+5)
        self.assertTrue((job/'answer.txt').exists())

    def test_crash_is_not_reused(self):
        job=self.job('crash')
        with self.assertRaises(RuntimeError):self.worker.submit(job,time.monotonic()+5)
        self.assertIsNone(self.worker.child)
        job=self.job('recovered');self.worker.submit(job,time.monotonic()+5)
        self.assertTrue((job/'answer.txt').exists())

    def test_dispatcher_keeps_one_backend_until_close(self):
        backend=Backend({'backend':'rkllm_native'})
        with patch('edge_agent.native_backend.NativeBackend') as adapter:
            adapter.return_value.complete.return_value={'role':'assistant','content':'ok'}
            backend.complete([],[]);backend.complete([],[])
            self.assertEqual(adapter.call_count,1)
            backend.close();adapter.return_value.close.assert_called_once()
            backend.complete([],[])
            self.assertEqual(adapter.call_count,2)
            backend.close()

    def test_native_adapter_reads_callback_metrics(self):
        from edge_agent.native_backend import NativeBackend
        c=dict(self.worker.config,native_executable=str(self.script),rkllm_model=str(self.script),request_timeout=5)
        backend=NativeBackend(c)
        try:
            backend.complete([{'role':'user','content':'hello'}],[])
            self.assertEqual(backend.last_metrics,{'native_first_text_ms':1,'native_total_ms':2})
            with self.assertRaisesRegex(RuntimeError,'timing metrics'):
                backend.complete([{'role':'user','content':'badmetrics'}],[])
            self.assertEqual(backend.last_metrics,{})
        finally:backend.close()


if __name__=='__main__':unittest.main()
