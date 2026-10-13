import time
from log.log_handler import LogHandler
from log.log_config import LogConfig

from uart.serial_config import SerialConfig
from uart.serial_driver import SerialDriver

class FirmwareService:
    def __init__(self):
        self.log_config = LogConfig(
            log_dir="./logs",
            console_output=True,
            max_bytes=1048576,  
            queue_capacity=1000,
            drain_timeout_s=3.0
        )
        self.log_handler = LogHandler(self.log_config)
        self.log_handler.start()

        self.sys_logger = self.log_handler.get_logger("ServiceLayer")
        self.uart_logger = self.log_handler.get_logger("UARTDriver")

        self.sys_logger.info("Initializing System Services...")
        self.uart_config = SerialConfig(
            port="/dev/ttyS0", 
            baudrate=115200,
            delimiter=b'\n',
            max_frame_bytes=256,
            rx_buffer_limit_bytes=1024,
            write_timeout_s=2.0,
            hardware_read_timeout_s=0.1
        )
        self.uart_driver = SerialDriver(self.uart_config, logger=self.uart_logger) 

    def _on_uart_frame(self, payload: bytes):
        self.sys_logger.info(f"Received frame: {payload}")
        try:
            self.uart_driver.send(b"ACK:" + payload + self.uart_config.delimiter)
        except Exception as e:
            self.sys_logger.error(f"Failed to send ACK: {e}")

    def _on_uart_error(self, error: Exception):
        self.sys_logger.error(f"UART connection dropped: {error}")
    def start(self):
        self.sys_logger.info("Starting up...")
        try:
            self.uart_driver.open()
            self.uart_driver.start_listening(
                on_frame=self._on_uart_frame,
                on_error=self._on_uart_error
            )
            self.sys_logger.info("UART Driver is successfully listening.")
        except Exception as e:
            self.sys_logger.error(f"Failed to start UART: {e}")

    def stop(self):
        self.sys_logger.info("Shutting down gracefully...")
        self.uart_driver.close()
        self.log_handler.stop()

    def run(self):
        self.start()
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            self.sys_logger.warning("Keyboard interrupt detected. Exiting...")
        finally:
            self.stop()

if __name__ == "__main__":
    service = FirmwareService()
    service.run()
