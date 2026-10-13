import serial
from .serial_config import SerialConfig
from .serial_exceptions import SerialError, LinkWriteError, LinkReadError, LinkNotOpen

class DummyLogger:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass

class SerialHandler:
    def __init__(self, config: SerialConfig, logger=None) -> None:
        self._config = config
        self._logger = logger or DummyLogger()
        self._serial: serial.Serial | None = None

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def open(self) -> None:
        if self.is_open:
            self._logger.warning(f"Port {self._config.port} is already open.")
            return

        try:
            self._serial = serial.Serial(
                port=self._config.port, baudrate=self._config.baudrate,
                timeout=self._config.hardware_read_timeout_s,
                write_timeout=self._config.write_timeout_s, exclusive=True
            )
            self._logger.info(f"Port {self._config.port} opened successfully.")
        except serial.SerialException as e:
            self._serial = None
            raise SerialError(f"Failed to open {self._config.port}: {e}") from e

    def close(self) -> None:
        if self._serial is not None:
            try: self._serial.close()
            except Exception: pass
            finally:
                self._serial = None
                self._logger.info(f"Port {self._config.port} closed.")
                
    def send(self, frame: bytes) -> None:
        if not self.is_open:
            raise LinkNotOpen("Cannot send: Link is not open.")
        try:
            self._serial.write(frame)
            self._serial.flush()
        except serial.SerialTimeoutException as e:
            self.close()
            raise LinkWriteError("Hardware write timed out.") from e
        except (serial.SerialException, OSError, AttributeError) as e:
            self.close()
            raise LinkWriteError(f"Hardware failure during write: {e}") from e

    def receive(self, timeout_s: float | None = None) -> bytes | None:
        if not self.is_open:
            raise LinkNotOpen("Cannot receive: Link is not open.")
        try:
            if timeout_s is not None: self._serial.timeout = timeout_s
            bytes_to_read = max(1, self._serial.in_waiting)
            chunk = self._serial.read(bytes_to_read)
            if timeout_s is not None: self._serial.timeout = self._config.hardware_read_timeout_s
            return chunk if chunk else None
        except (serial.SerialException, OSError, AttributeError) as e:
            self.close()
            raise LinkReadError(f"Hardware failure during read: {e}") from e
