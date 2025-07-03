import os
import tempfile
import psutil
import time

class SafeProcessLock:
    def __init__(self, name: str):
        self.name = name
        self.lock_file = os.path.join(tempfile.gettempdir(), f"{name}.lock")
        self.pid = os.getpid()
        self.acquired = False

    def acquire(self):
        while True:
            try:
                # O_EXCL + O_CREAT を指定して排他的にファイルを作成する
                fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as f:
                    f.write(str(self.pid))
                self.acquired = True
                return True
            except FileExistsError:
                try:
                    with open(self.lock_file, "r") as f:
                        content = f.read().strip()
                        if not content.isdigit():
                            raise ValueError("Invalid PID content")
                        existing_pid = int(content)

                    if psutil.pid_exists(existing_pid):
                        try:
                            existing_proc = psutil.Process(existing_pid)
                            current_proc = psutil.Process(self.pid)

                            if existing_proc.exe() != current_proc.exe():
                                return False  # 他のプログラムが保持中のロック
                            else:
                                # 同一 exe でも既にロックが存在 = 自分以外が同じプログラムを起動中
                                return False
                        except psutil.Error:
                            pass
                    # プロセスが存在しない or アクセスできない → stale lock
                    os.remove(self.lock_file)
                except Exception:
                    # ロックファイル破損など
                    try:
                        os.remove(self.lock_file)
                    except Exception:
                        return False  # 削除できない = 他プロセスが保持している可能性
                # ループして再試行
                time.sleep(0.1)

    def release(self):
        if self.acquired and os.path.exists(self.lock_file):
            try:
                with open(self.lock_file, "r") as f:
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
