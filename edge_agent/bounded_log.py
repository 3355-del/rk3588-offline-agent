"""Drain child output into a bounded binary log, closing handles before rotation."""
import os
import threading
from pathlib import Path


class BoundedLog:
    def __init__(self, path, limit=8*1024*1024, backups=2):
        if limit < 1 or backups < 1:
            raise ValueError('Positive log limit and backup count required')
        self.path=Path(path);self.limit=limit;self.backups=backups
        self.thread=None;self.error=None;self.file=None
        if self.path.exists() and self.path.stat().st_size >= limit:
            # Previous unbounded logs are rotated once; cap their retained tail.
            with self.path.open('rb') as old:
                old.seek(max(0,self.path.stat().st_size-limit));tail=old.read(limit)
            with self.path.open('wb') as old: old.write(tail)
            self._rotate()
        self.file=self.path.open('ab')

    def _rotate(self):
        if self.file is not None: self.file.close();self.file=None
        for i in range(self.backups,1,-1):
            src=self.path.with_name(self.path.name+f'.{i-1}')
            if src.exists(): os.replace(src,self.path.with_name(self.path.name+f'.{i}'))
        if self.path.exists(): os.replace(self.path,self.path.with_name(self.path.name+'.1'))

    def write(self, data):
        while data:
            if self.file.tell() >= self.limit:
                self._rotate();self.file=self.path.open('ab')
            count=min(len(data),self.limit-self.file.tell())
            self.file.write(data[:count]);self.file.flush();data=data[count:]

    def start(self, pipe):
        def drain():
            try:
                while True:
                    chunk=pipe.read1(4096)
                    if not chunk: break
                    if self.error is None:
                        try: self.write(chunk)
                        except OSError as exc: self.error=exc
            except OSError as exc:
                self.error=exc
            finally:
                pipe.close()
        self.thread=threading.Thread(target=drain,name='model-log',daemon=True)
        self.thread.start()

    def close(self):
        if self.thread:
            self.thread.join(timeout=5)
            if self.thread.is_alive(): raise RuntimeError('Model log pipe did not close')
            self.thread=None
        if self.file: self.file.close();self.file=None
