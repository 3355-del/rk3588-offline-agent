"""Real process lock tests; no NPU access, isolated temporary lock file."""
import select
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(sys.platform=='linux' and shutil.which('g++'),'Linux C++ lease test')
class SessionLeaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='edge-lease-test-')
        cls.root=Path(cls.tmp.name)
        source=cls.root/'probe.cpp'
        source.write_text('''#include "npu_session_lease.h"
#include <iostream>
int main(int argc,char** argv) {
  try {NpuSessionLease lease(argv[1]);lease.acquire(argv[2][0]=='x');
    std::cout<<"ready"<<std::endl;std::string line;std::getline(std::cin,line);return 0;
  } catch(const std::exception& e){std::cerr<<e.what();return 3;}
}''')
        cls.exe=cls.root/'probe'
        native=Path(__file__).resolve().parents[1]/'native'
        subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-I',str(native),str(source),'-o',str(cls.exe)],check=True,capture_output=True)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def start(self,mode):
        child=subprocess.Popen([str(self.exe),str(self.root/'lock'),mode],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        def cleanup():
            if child.poll() is None:child.kill()
            child.communicate(timeout=3)
        self.addCleanup(cleanup)
        self.assertTrue(select.select([child.stdout],[],[],3)[0],'lock probe did not respond')
        return child

    def test_shared_detection_sessions_coexist(self):
        first=self.start('s');self.assertEqual(first.stdout.readline().strip(),'ready')
        second=self.start('s');self.assertEqual(second.stdout.readline().strip(),'ready')
        exclusive=self.start('x');_,err=exclusive.communicate(timeout=3)
        self.assertEqual(exclusive.returncode,3);self.assertIn('--cpu',err)

    def test_exclusive_blocks_both_modes_and_crash_releases(self):
        owner=self.start('x');self.assertEqual(owner.stdout.readline().strip(),'ready')
        for mode in ('s','x'):
            contender=self.start(mode);contender.communicate(timeout=3)
            self.assertEqual(contender.returncode,3)
        owner.kill();owner.wait(timeout=3)
        replacement=self.start('x');self.assertEqual(replacement.stdout.readline().strip(),'ready')

    def test_normal_exit_releases(self):
        owner=self.start('x');self.assertEqual(owner.stdout.readline().strip(),'ready')
        owner.communicate('\n',timeout=3);self.assertEqual(owner.returncode,0)
        replacement=self.start('s');self.assertEqual(replacement.stdout.readline().strip(),'ready')
