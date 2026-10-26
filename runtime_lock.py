"""One process per database, using OS-released locks on Linux and Windows."""
import os
from pathlib import Path


class RuntimeLock:
    def __init__(self,path):self.path=Path(path);self.file=None

    def acquire(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        stream=self.path.open('a+b')
        try:
            if os.name=='nt':
                import msvcrt
                if self.path.stat().st_size==0:stream.write(b'\0');stream.flush()
                stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            stream.close();raise RuntimeError('Bộ chạy lịch đang hoạt động ở tiến trình khác.') from None
        self.file=stream;return self

    def release(self):
        if self.file:
            if os.name=='nt':
                import msvcrt
                self.file.seek(0);msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
            self.file.close();self.file=None

    def __enter__(self):return self.acquire()
    def __exit__(self,*args):self.release()
