import threading

class LogMetrics:
    def __init__(self):
        self._lock = threading.Lock()
        self.write_error_count = 0
        self.rotation_error_count = 0
        self.dropped_record_count = 0

    def inc_write_error(self):
        with self._lock: self.write_error_count += 1

    def inc_rotation_error(self):
        with self._lock: self.rotation_error_count += 1

    def inc_dropped_record(self, count: int = 1):
        with self._lock: self.dropped_record_count += count
