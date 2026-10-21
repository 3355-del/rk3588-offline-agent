"""Linux validation commands own one session, including their descendants."""
import os
import signal
import subprocess
import threading
import time


def _signal_group(pid, sig):
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass


def _group_exists(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def run_owned(args, *, cwd, stdout, timeout, grace=10):
    """Run a Linux audit step; on every exit reclaim its private process group.

    SIGINT gives Python children a chance to execute finally. SIGKILL bounds
    cleanup if a child ignores it. Children must not detach into other sessions.
    """
    if os.name != 'posix':
        raise RuntimeError('Owned audit process groups require Linux/POSIX')
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Run audit steps from the main thread')
    child = None
    previous = signal.getsignal(signal.SIGTERM)

    def interrupted(signum, frame):
        raise KeyboardInterrupt('Audit terminated by SIGTERM')

    signal.signal(signal.SIGTERM, interrupted)
    try:
        child = subprocess.Popen(args, cwd=cwd, stdout=stdout,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        code = child.wait(timeout=timeout)
        if code:
            raise subprocess.CalledProcessError(code, args)
        return code
    finally:
        # Do not allow a second termination request to interrupt cleanup itself.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        old_int = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            if child is not None:
                _signal_group(child.pid, signal.SIGINT)
                deadline = time.monotonic() + grace
                while _group_exists(child.pid) and time.monotonic() < deadline:
                    child.poll()
                    time.sleep(.05)
                _signal_group(child.pid, signal.SIGKILL)
                child.wait(timeout=5)
        finally:
            signal.signal(signal.SIGINT, old_int)
            signal.signal(signal.SIGTERM, previous)
