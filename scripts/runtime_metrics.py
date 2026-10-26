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
                 'vram_used': None, 'vram_total': None, 'power': None,
                 'cpu_mhz': None, 'gpu_mhz': None, 'power_limit': None,
                 'swap_used': None, 'swap_total': None}
        try:
            frequency = psutil.cpu_freq()
            if frequency and frequency.current > 0:
                value['cpu_mhz'] = round(frequency.current)
            swap = psutil.swap_memory()
            value.update(swap_used=round(swap.used/2**30, 1), swap_total=round(swap.total/2**30, 1))
        except (OSError, NotImplementedError):
            pass
        try:
            result = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total,power.draw,power.limit,clocks.current.graphics',
                '--format=csv,noheader,nounits', '--id=0'], capture_output=True, text=True,
                encoding='utf-8', timeout=3, stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode == 0:
                fields = result.stdout.strip().split(',')
                for key, field in zip(('gpu', 'vram_used', 'vram_total', 'power', 'power_limit', 'gpu_mhz'), fields):
                    try:
                        import math
                        reading = float(field.strip())
                        if math.isfinite(reading) and reading >= 0:
                            value[key] = reading
                    except ValueError:
                        pass
        except (OSError, subprocess.TimeoutExpired):
            pass
        self.value = value

    def close(self):
        self.closed = True
        if self.worker:
            self.worker.join(timeout=4)
