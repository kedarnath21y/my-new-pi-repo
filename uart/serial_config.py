from dataclasses import dataclass

@dataclass(frozen=True)
class SerialConfig:
    port: str
    baudrate: int
    delimiter: bytes
    max_frame_bytes: int
    rx_buffer_limit_bytes: int
    write_timeout_s: float = 2.0
    hardware_read_timeout_s: float = 0.1

    def __post_init__(self) -> None:
        if not self.port: raise ValueError("Serial port must be non-empty.")
        if self.baudrate <= 0: raise ValueError("Baudrate must be positive.")
        if not self.delimiter: raise ValueError("Delimiter cannot be empty.")
        if self.max_frame_bytes <= 0: raise ValueError("max_frame_bytes > 0 required.")
        if self.rx_buffer_limit_bytes <= 0: raise ValueError("rx_buffer_limit_bytes > 0 required.")
        if self.write_timeout_s <= 0: raise ValueError("write_timeout_s > 0 required.")
        if self.hardware_read_timeout_s <= 0: raise ValueError("hardware_read_timeout_s > 0 required.")
