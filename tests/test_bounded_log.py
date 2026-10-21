import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from edge_agent.bounded_log import BoundedLog


class BoundedLogTests(unittest.TestCase):
    def test_rotation_retains_tail_and_bounds_disk(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'server.log';log=BoundedLog(p,limit=32,backups=2)
            payload=bytes(range(256))*4
            log.write(payload);log.close()
            files=[p.with_name(p.name+'.2'),p.with_name(p.name+'.1'),p]
            self.assertEqual(b''.join(f.read_bytes() for f in files),payload[-96:])
            self.assertTrue(all(f.stat().st_size<=32 for f in files))

    def test_existing_large_log_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'server.log';p.write_bytes(b'x'*1000)
            log=BoundedLog(p,limit=32);log.write(b'end');log.close()
            self.assertEqual(p.read_bytes(),b'end')
            self.assertEqual(p.with_name(p.name+'.1').stat().st_size,32)

    def test_real_process_output_drains_without_blocking(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'server.log';log=BoundedLog(p,limit=4096)
            child=subprocess.Popen([sys.executable,'-c',"import sys;sys.stdout.buffer.write(b'x'*200000+b'TAIL')"],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            log.start(child.stdout)
            try: self.assertEqual(child.wait(timeout=10),0)
            finally:
                if child.poll() is None:child.kill();child.wait()
                log.close()
            self.assertIsNone(log.error)
            self.assertTrue(p.read_bytes().endswith(b'TAIL'))
            self.assertLessEqual(sum(f.stat().st_size for f in Path(folder).iterdir()),3*4096)
