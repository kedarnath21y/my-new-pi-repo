import threading
from typing import Callable, Optional

from .serial_config import SerialConfig
from .serial_exceptions import LinkNotOpen, FrameTooLarge, LinkWriteError, LinkReadError
from .serial_handler import SerialHandler, DummyLogger

class SerialDriver:
    def __init__(self, config: SerialConfig, logger=None) -> None:
        self._config = config
        self._logger = logger or DummyLogger()
        self._handler = SerialHandler(config, self._logger)
        
        self._lock = threading.Lock()
        self._is_open: bool = False
        self._rx_buffer: bytearray = bytearray()
        self._frame_error_count: int = 0
        self._rx_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._on_frame_callback: Optional[Callable[[bytes], None]] = None
        self._on_error_callback: Optional[Callable[[Exception], None]] = None

    @property
    def is_open(self) -> bool:
        with self._lock: return self._is_open

    @property
    def frame_error_count(self) -> int:
        with self._lock: return self._frame_error_count

    def open(self) -> None:
        with self._lock:
            if self._is_open: return
            self._handler.open()
            self._rx_buffer.clear()
            self._frame_error_count = 0
            self._is_open = True

    def close(self) -> None:
        self.stop_listening()
        with self._lock:
            if not self._is_open: return
            self._is_open = False
            self._handler.close()
            self._rx_buffer.clear()

    def send(self, frame: bytes) -> None:
        with self._lock:
            if not self._is_open:
                raise LinkNotOpen("Cannot send: Serial driver is closed.")
            if len(frame) > self._config.max_frame_bytes:
                raise FrameTooLarge(f"Frame size {len(frame)} exceeds max {self._config.max_frame_bytes}")

        try:
            self._handler.send(frame)
        except LinkWriteError as e:
            self._logger.error(f"Write error on {self._config.port}, closing driver: {e}")
            self.close()
            raise

    def start_listening(self, on_frame: Callable[[bytes], None], on_error: Callable[[Exception], None]) -> None:
        with self._lock:
            if not self._is_open: raise LinkNotOpen("Cannot start listening: Port is closed.")
            if self._rx_thread is not None and self._rx_thread.is_alive(): return

            self._on_frame_callback = on_frame
            self._on_error_callback = on_error
            self._stop_event.clear()
            self._rx_thread = threading.Thread(target=self._rx_thread_loop, name="SerialRXThread", daemon=True)
            self._rx_thread.start()

    def stop_listening(self) -> None:
        self._stop_event.set()
        if self._rx_thread is not None:
            if self._rx_thread.is_alive() and threading.current_thread() != self._rx_thread:
                self._rx_thread.join(timeout=2.0)
            self._rx_thread = None

    def _rx_thread_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                chunk = self._handler.receive(timeout_s=self._config.hardware_read_timeout_s)
                if chunk:
                    with self._lock: self._rx_buffer.extend(chunk)
                    self._process_buffer()
            except LinkReadError as e:
                self._logger.error(f"Read error on {self._config.port}, closing driver: {e}")
                self.close()
                if self._on_error_callback: self._on_error_callback(e)
                break

    def _process_buffer(self) -> None:
        delimiter = self._config.delimiter
        delim_len = len(delimiter)
        
        while True:
            payload = None
            with self._lock:
                idx = self._rx_buffer.find(delimiter)
                if idx != -1:
                    payload = bytes(self._rx_buffer[:idx])
                    del self._rx_buffer[:idx + delim_len]
                else:
                    if len(self._rx_buffer) >= self._config.rx_buffer_limit_bytes:
                        self._logger.error(f"RX buffer overflow ({self._config.rx_buffer_limit_bytes}B). Discarding.")
                        self._rx_buffer.clear()
                        self._frame_error_count += 1
                    break 

            if payload is not None:
                if len(payload) == 0:
                    with self._lock: self._frame_error_count += 1
                    self._logger.warning("Malformed frame (empty payload) discarded.")
                    continue

                if self._on_frame_callback:
                    try: self._on_frame_callback(payload)
                    except Exception as e: self._logger.error(f"Callback exception: {e}")
