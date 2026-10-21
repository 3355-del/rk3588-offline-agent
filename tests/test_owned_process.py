"""Real lightweight parent/child cleanup tests; no hardware or models."""
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from edge_agent.owned_process import run_owned


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux process groups')
class OwnedProcessTests(unittest.TestCase):
    def test_success_and_nonzero(self):
        with tempfile.TemporaryDirectory() as folder, open(os.devnull,'w') as log:
            self.assertEqual(run_owned([sys.executable,'-c','pass'],cwd=folder,stdout=log,timeout=3,grace=.2),0)
            with self.assertRaises(subprocess.CalledProcessError):
                run_owned([sys.executable,'-c','raise SystemExit(7)'],cwd=folder,stdout=log,timeout=3,grace=.2)

    def test_timeout_reclaims_descendant_and_runs_finally(self):
        with tempfile.TemporaryDirectory() as folder, open(os.devnull,'w') as log:
            root=Path(folder)
            descendant="import signal,time;signal.signal(signal.SIGINT,signal.SIG_IGN);time.sleep(60)"
            program=("import subprocess,sys,time,pathlib\n"
                     f"p=subprocess.Popen([sys.executable,'-c',{descendant!r}])\n"
                     "pathlib.Path('pid').write_text(str(p.pid))\n"
                     "try: time.sleep(60)\n"
                     "finally: pathlib.Path('finally').write_text('yes')\n")
            with self.assertRaises(subprocess.TimeoutExpired):
                run_owned([sys.executable,'-c',program],cwd=folder,stdout=log,timeout=1,grace=.3)
            self.assertTrue((root/'finally').exists())
            self.assert_dead(int((root/'pid').read_text()))

    def assert_dead(self,pid):
        for _ in range(40):
            try:
                state=Path(f'/proc/{pid}/stat').read_text().split(') ',1)[1].split()[0]
            except FileNotFoundError:
                return
            if state=='Z': return  # killed, awaiting init's reap
            time.sleep(.05)
        self.fail(f'process {pid} remains running')

    def test_sigterm_reclaims_group(self):
        with tempfile.TemporaryDirectory() as folder, open(os.devnull,'w') as log:
            root=Path(folder)
            program="import os,pathlib,time;pathlib.Path('pid').write_text(str(os.getpid()));time.sleep(60)"
            runner=("import sys\n"
                    f"sys.path.insert(0,{str(Path(__file__).resolve().parents[1])!r})\n"
                    "from edge_agent.owned_process import run_owned\n"
                    f"run_owned([sys.executable,'-c',{program!r}],cwd={folder!r},stdout=sys.stdout,timeout=30,grace=.3)\n")
            p=subprocess.Popen([sys.executable,'-B','-c',runner],stdout=log,stderr=log)
            try:
                deadline=time.monotonic()+5
                while not (root/'pid').exists() and time.monotonic()<deadline: time.sleep(.02)
                self.assertTrue((root/'pid').exists())
                p.send_signal(signal.SIGTERM);p.wait(timeout=5)
                self.assertNotEqual(p.returncode,0)
                self.assert_dead(int((root/'pid').read_text()))
            finally:
                if p.poll() is None: p.kill();p.wait()
