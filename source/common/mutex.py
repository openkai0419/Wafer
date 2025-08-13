import os
import tempfile
import time
import psutil

class SafeProcessLock:

    def __init__(self, name):
        self.name = name
        self.lock_file = os.path.join(tempfile.gettempdir(), f'{name}.lock')
        self.pid = os.getpid()
        self.acquired = False

    def acquire(self):
        while True:
            try:
                fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, 'w') as f:
                    f.write(str(self.pid))
                self.acquired = True
                return True
            except FileExistsError:
                try:
                    with open(self.lock_file, 'r') as f:
                        content = f.read().strip()
                        if not content.isdigit():
                            raise ValueError('Invalid PID content')
                        existing_pid = int(content)
                    if psutil.pid_exists(existing_pid):
                        try:
                            existing_proc = psutil.Process(existing_pid)
                            current_proc = psutil.Process(self.pid)
                            if existing_proc.exe() != current_proc.exe():
                                return False
                            else:
                                return False
                        except psutil.Error:
                            pass
                    os.remove(self.lock_file)
                except Exception:
                    try:
                        os.remove(self.lock_file)
                    except Exception:
                        return False
                time.sleep(0.1)

    def release(self):
        if self.acquired and os.path.exists(self.lock_file):
            try:
                with open(self.lock_file, 'r') as f:
                    if int(f.read().strip()) == self.pid:
                        os.remove(self.lock_file)
            except Exception:
                pass

    def __enter__(self):
        if not self.acquire():
            raise FileExistsError(f"Process '{self.name}' already running")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
