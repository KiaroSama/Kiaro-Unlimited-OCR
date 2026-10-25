"""Optional hardware sampler kept off the token-generation critical path."""
import subprocess
import threading
import time


class Monitor:
    def __init__(self):
        self.updated = 0
        self.value = {}
        self.worker = None
        self.closed = False

    def read(self):
        if not self.closed and time.monotonic() - self.updated >= 2 and (self.worker is None or not self.worker.is_alive()):
            self.updated = time.monotonic()
            self.worker = threading.Thread(target=self.sample, daemon=True)
            self.worker.start()
        return self.value.copy()

    def sample(self):
        import psutil
        memory = psutil.virtual_memory()
        value = {'cpu': psutil.cpu_percent(interval=0.1), 'ram_used': round(memory.used/2**30, 1),
                 'ram_total': round(memory.total/2**30, 1), 'gpu': None,
                 'vram_used': None, 'vram_total': None, 'power': None}
        try:
            result = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total,power.draw',
                '--format=csv,noheader,nounits', '--id=0'], capture_output=True, text=True,
                encoding='utf-8', timeout=3, stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode == 0:
                fields = result.stdout.strip().split(',')
                for key, field in zip(('gpu', 'vram_used', 'vram_total', 'power'), fields):
                    try:
                        value[key] = float(field.strip())
                    except ValueError:
                        pass
        except (OSError, subprocess.TimeoutExpired):
            pass
        self.value = value

    def close(self):
        self.closed = True
        if self.worker:
            self.worker.join(timeout=4)
