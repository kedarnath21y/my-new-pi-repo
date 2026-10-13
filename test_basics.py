import unittest
from log.log_config import LogConfig
from log.log_metrics import LogMetrics
from log.log_handler import CustomLogger
from uart.serial_config import SerialConfig
from uart.serial_handler import SerialHandler

class FirmwareBasicTests(unittest.TestCase):

    def test_21_serial_config_defaults(self):
        """TC-21: Verify SerialConfig applies correct default timeouts."""
        config = SerialConfig("COM1", 9600, b'\n', 100, 100)
        self.assertEqual(config.write_timeout_s, 2.0)
        self.assertEqual(config.hardware_read_timeout_s, 0.1)

    def test_22_log_config_instantiation(self):
        """TC-22: Verify LogConfig rejects zero/negative limits."""
        with self.assertRaises(ValueError):
            LogConfig("./logs", True, max_bytes=0, queue_capacity=10, drain_timeout_s=1)

    def test_23_log_metrics_increments(self):
        """TC-23: Verify LogMetrics counters increment correctly."""
        metrics = LogMetrics()
        metrics.inc_write_error()
        metrics.inc_dropped_record(5)
        self.assertEqual(metrics.write_error_count, 1)
        self.assertEqual(metrics.dropped_record_count, 5)

    def test_24_custom_logger_formatting(self):
        """TC-24: Verify log string formatting structure."""
        class MockHandler:
            def __init__(self): self.last_msg = ""
            def _enqueue(self, msg): self.last_msg = msg
            
        handler = MockHandler()
        logger = CustomLogger("TestNode", handler)
        logger.info("Booting up")
        
        self.assertIn("[INFO]", handler.last_msg)
        self.assertIn("TestNode:", handler.last_msg)
        self.assertIn("Booting up\n", handler.last_msg)

    def test_25_serial_handler_initial_state(self):
        """TC-25: Verify driver state before hardware allocation."""
        config = SerialConfig("COM1", 9600, b'\n', 100, 100)
        handler = SerialHandler(config)
        self.assertFalse(handler.is_open)

if __name__ == '__main__':
    unittest.main(verbosity=2)
