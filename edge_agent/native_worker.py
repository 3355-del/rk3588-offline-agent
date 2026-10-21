"""Session-owned native worker; no network endpoint or shared background daemon."""
import atexit
import subprocess
import tempfile
import time
import weakref
from pathlib import Path
from .process import Cancelled

_live = weakref.WeakSet()


@atexit.register
def _shutdown():
    for worker in list(_live):
        worker.close()


class NativeWorker:
    def __init__(self, config, cancel):
        self.config = config
        self.cancel = cancel
        self.child = self.folder = self.log = None
        _live.add(self)

    def close(self, graceful=True):
        if self.child is not None:
            # EOF lets the idle C++ service leave getline and destroy its RKNN/
            # RKLLM contexts. Failed or cancelled requests must not wait for EOF.
            if self.child.stdin:
                try:
                    self.child.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
            if graceful and self.child.poll() is None:
                try:
                    self.child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
            if self.child.poll() is None:
                self.child.terminate()
                try:
                    self.child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.child.kill()
                    self.child.wait(timeout=3)
            self.child = None
        if self.log is not None:
            self.log.close()
            self.log = None
        if self.folder is not None:
            self.folder.cleanup()
            self.folder = None

    def __del__(self):
        self.close()

    def _check(self, deadline):
        if self.cancel.is_set():
            raise Cancelled('已取消')
        if time.monotonic() > deadline:
            raise TimeoutError('NPU请求超时，已释放常驻模型')
        if self.log.tell() > 8*1024*1024:
            raise RuntimeError('NPU进程日志超过限制，已释放模型')

    def _error(self):
        self.log.seek(max(0, self.log.tell()-2500))
        return self.log.read(2500).decode('utf8', 'replace')

    def wait(self, marker, deadline):
        while True:
            self._check(deadline)
            if marker.exists():
                return
            if self.child.poll() is not None:
                raise RuntimeError(self._error() or 'NPU工作进程意外退出')
            self.cancel.wait(.02)

    def start(self, deadline):
        if self.child is not None and self.child.poll() is None:
            return Path(self.folder.name)
        self.close()
        c = self.config
        try:
            self.folder = tempfile.TemporaryDirectory(prefix='edge-resident-')
            self.log = tempfile.TemporaryFile()
            self.child = subprocess.Popen([c['native_executable'], '--serve', c['rkllm_model'],
                c['rknn_vision_model'], str(c['vision_width']), str(c['vision_height']),
                str(c['max_tokens']), str(c['context_tokens']), self.folder.name],
                stdin=subprocess.PIPE, stdout=self.log, stderr=self.log, shell=False)
            root = Path(self.folder.name)
            self.wait(root/'ready', deadline)
            if (root/'ready').read_text() != 'edge-resident-v1':
                raise RuntimeError('NPU常驻协议不匹配，请重新编译')
            return root
        except BaseException:
            self.close(graceful=False)
            raise

    def submit(self, job, deadline):
        try:
            self._check(deadline)
            self.child.stdin.write((job.name+'\n').encode('ascii'))
            self.child.stdin.flush()
            self.wait(job/'done', deadline)
            if (job/'done').read_text() != '0':
                raise RuntimeError(self._error() or 'NPU推理失败')
        except BaseException:
            self.close(graceful=False)
            raise
