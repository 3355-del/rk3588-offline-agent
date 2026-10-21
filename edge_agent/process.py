"""Bounded subprocess execution; cancellation terminates only this owned process."""
import subprocess,time,tempfile,threading

class Cancelled(RuntimeError):pass

def run(args,timeout,cancel=None,input_text=None,allow_failure=False):
    cancel=cancel or threading.Event()
    if cancel.is_set():raise Cancelled('已取消')
    with tempfile.TemporaryFile() as log, tempfile.TemporaryFile() as stdin:
        if input_text is not None:stdin.write(input_text.encode('utf8'));stdin.seek(0)
        child=subprocess.Popen(args,stdin=stdin,stdout=log,stderr=log,shell=False,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        deadline=time.monotonic()+timeout
        try:
            while child.poll() is None:
                if cancel.wait(.05):raise Cancelled('已取消')
                if time.monotonic()>deadline:raise TimeoutError('操作超时，已停止本次子进程')
                if log.tell()>8*1024*1024:raise RuntimeError('子进程输出超过限制')
            log.seek(0);output=log.read(8*1024*1024).decode('utf8','replace')
            if cancel.is_set():raise Cancelled('已取消')
            if child.returncode and not allow_failure:raise RuntimeError(output[-2500:] or f'子进程退出码 {child.returncode}')
            return output
        finally:
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=3)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=3)
