import os
import sys
import time
import threading
from typing import Dict, Optional

from .log_config import LogConfig
from .log_exceptions import LogSinkUnavailable
from .log_metrics import LogMetrics

class CustomLogger:
    def __init__(self, name: str, handler: 'LogHandler'):
        self._name = name
        self._handler = handler

    def _format(self, level: str, msg: str) -> str:
        t = time.localtime()
        t_str = f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d} {t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}"
        return f"[{t_str}] [{level}] {self._name}: {msg}\n"

    def debug(self, msg: str): self._handler._enqueue(self._format("DEBUG", msg))
    def info(self, msg: str): self._handler._enqueue(self._format("INFO", msg))
    def warning(self, msg: str): self._handler._enqueue(self._format("WARNING", msg))
    def error(self, msg: str): self._handler._enqueue(self._format("ERROR", msg))


class LogHandler:
    def __init__(self, config: LogConfig):
        self._config = config
        self.metrics = LogMetrics()
        
        self._is_started = False
        self._queue: list[str] = []
        self._lock = threading.Lock()
        
        self._drain_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._loggers: Dict[str, CustomLogger] = {}
        
        self._current_file = None
        self._current_file_size = 0
        self._filepath = os.path.join(self._config.log_dir, "system.log")
        self._last_stderr_error_time = 0

    def get_logger(self, name: str) -> CustomLogger:
        with self._lock:
            if name not in self._loggers:
                self._loggers[name] = CustomLogger(name, self)
            return self._loggers[name]

    def _enqueue(self, record: str):
        with self._lock:
            if not self._is_started:
                if self._config.console_output: sys.stdout.write(record)
                return

            if len(self._queue) >= self._config.queue_capacity:
                self.metrics.inc_dropped_record()
                return  
                
            self._queue.append(record)
    def _resolve_destination(self) -> None:
        directories_to_try = [
            self._config.log_dir, 
            os.path.join(os.getcwd(), "fallback_logs"),
            "/tmp/system_logs"
        ]
        for directory in directories_to_try:
            try:
                os.makedirs(directory, exist_ok=True)
                self._filepath = os.path.join(directory, "system.log")
                self._current_file = open(self._filepath, "a", encoding="utf-8")
                self._current_file_size = os.path.getsize(self._filepath)
                if directory != self._config.log_dir:
                    sys.stderr.write(f"[WARNING] Primary log dir inaccessible. Falling back to: {self._filepath}\n")
                return
            except OSError:
                continue
        raise LogSinkUnavailable("All attempts to resolve and create a log destination failed.")

    def start(self) -> None:
        with self._lock:
            if self._is_started: return
            self._resolve_destination()
            self._stop_event.clear()
            self._is_started = True
            
            self._drain_thread = threading.Thread(target=self._drain_loop, name="LogDrainThread", daemon=True)
            self._drain_thread.start()

    def _rotate(self):
        try:
            self._current_file.close()
            backup_path = f"{self._filepath}.1"
            if os.path.exists(backup_path): os.remove(backup_path) 
            os.rename(self._filepath, backup_path)
            
            self._current_file = open(self._filepath, "a", encoding="utf-8")
            self._current_file_size = 0
        except OSError:
            self.metrics.inc_rotation_error()
            self._current_file = open(self._filepath, "w", encoding="utf-8") # Truncate to free space
            self._current_file_size = 0

    def _report_write_error(self, exception_msg: str):
        self.metrics.inc_write_error()
        now = time.time()
        if now - self._last_stderr_error_time > 5.0:  
            sys.stderr.write(f"[ERROR] LogHandler IO Failure: {exception_msg}. Records dropping.\n")
            self._last_stderr_error_time = now

    def _safe_write(self, record: str) -> None:
        chars_to_write = len(record)
        chars_written = 0
        
        while chars_written < chars_to_write:
            try:
                chunk = record[chars_written:]
                written = self._current_file.write(chunk)
                if written == 0: raise IOError("Zero bytes written - disk full.")
                
                chars_written += written
                self._current_file_size += len(chunk[:written].encode("utf-8"))
            except OSError as e:
                self._report_write_error(str(e))
                try: self._current_file.truncate(self._current_file_size) # Revert partial write
                except OSError: pass 
                time.sleep(1.0) # Stall prevention
                break
        try: self._current_file.flush()
        except OSError: pass
        if self._current_file_size >= self._config.max_bytes: self._rotate()

    def _drain_loop(self):
        while not self._stop_event.is_set() or self._queue:
            record = None
            with self._lock:
                if self._queue: record = self._queue.pop(0)

            if record:
                if self._config.console_output: sys.stdout.write(record)
                self._safe_write(record)
            else:
                time.sleep(0.05) 

    def stop(self) -> None:
        with self._lock:
            if not self._is_started: return
            self._stop_event.set()

        if self._drain_thread and self._drain_thread.is_alive():
            self._drain_thread.join(timeout=self._config.drain_timeout_s)

        with self._lock:
            if self._queue:
                self.metrics.inc_dropped_record(len(self._queue))
                self._queue.clear()
            if self._current_file:
                try: self._current_file.close()
                except Exception: pass
                self._current_file = None
            self._is_started = False
