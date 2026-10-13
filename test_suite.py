import os
import unittest
from unittest.mock import patch, MagicMock

# Import your modules
from log.log_config import LogConfig
from log.log_handler import LogHandler
from uart.serial_config import SerialConfig
from uart.serial_exceptions import LinkNotOpen, FrameTooLarge, LinkWriteError
from uart.serial_driver import SerialDriver
from service.service_layer import FirmwareService

class FirmwareValidationTests(unittest.TestCase):

    # ---------------------------------------------------------
    # UART TESTS
    # ---------------------------------------------------------

    def test_01_uart_config_validation(self):
        """TC-01: Reject invalid parameters in SerialConfig"""
        with self.assertRaises(ValueError):
            SerialConfig(port="", baudrate=115200, delimiter=b'\n', max_frame_bytes=256, rx_buffer_limit_bytes=1024)
        with self.assertRaises(ValueError):
            SerialConfig(port="COM1", baudrate=-9600, delimiter=b'\n', max_frame_bytes=256, rx_buffer_limit_bytes=1024)

    def test_02_uart_link_not_open(self):
        """TC-02: Prevent send/receive operations if driver is closed"""
        config = SerialConfig("COM1", 115200, b'\n', 256, 1024)
        driver = SerialDriver(config)
        with self.assertRaises(LinkNotOpen):
            driver.send(b"HELLO")

    def test_03_uart_frame_too_large(self):
        """TC-03: Block payloads exceeding max_frame_bytes"""
        config = SerialConfig("COM1", 115200, b'\n', max_frame_bytes=10, rx_buffer_limit_bytes=1024)
        driver = SerialDriver(config)
        driver._is_open = True  # Mock open state
        
        with self.assertRaises(FrameTooLarge):
            driver.send(b"THIS_IS_LONGER_THAN_10_BYTES")

    @patch('uart.serial_handler.serial.Serial')
    def test_04_uart_hardware_fault(self, mock_serial_class):
        """TC-04: Handle hardware disconnect mid-write"""
        mock_serial_instance = MagicMock()
        import serial
        mock_serial_instance.write.side_effect = serial.SerialException("USB Unplugged")
        mock_serial_class.return_value = mock_serial_instance

        config = SerialConfig("COM1", 115200, b'\n', 256, 1024)
        driver = SerialDriver(config)
        driver.open()

        with self.assertRaises(LinkWriteError):
            driver.send(b"TEST")
        
        # Driver should auto-close on hardware fault
        self.assertFalse(driver.is_open)

    def test_05_uart_buffer_overflow_malformed(self):
        """TC-05: Handle buffer limits and discard empty frames"""
        config = SerialConfig("COM1", 115200, b'\n', 256, rx_buffer_limit_bytes=10)
        driver = SerialDriver(config)
        driver._is_open = True
        
        # Inject malformed (empty) frame: just the delimiter
        driver._rx_buffer.extend(b'\n')
        driver._process_buffer()
        self.assertEqual(driver.frame_error_count, 1)

        # Inject overflow data without delimiter (15 bytes > 10 byte limit)
        driver._rx_buffer.extend(b'123456789012345')
        driver._process_buffer()
        # Buffer should be cleared, error count goes up
        self.assertEqual(len(driver._rx_buffer), 0)
        self.assertEqual(driver.frame_error_count, 2)
        
# ---------------------------------------------------------
    # LOG TESTS
    # ---------------------------------------------------------

    @patch('os.makedirs')
    def test_06_log_fallback_directory(self, mock_makedirs):
        """TC-06: Route to fallback path if primary is inaccessible"""
        # Make the first call (primary dir) fail, second call (fallback) succeed
        mock_makedirs.side_effect = [OSError("Permission Denied"), None]
        
        config = LogConfig(log_dir="/root/forbidden", console_output=False, max_bytes=1000, queue_capacity=10, drain_timeout_s=1)
        handler = LogHandler(config)
        
        with patch('builtins.open', unittest.mock.mock_open()), \
             patch('os.path.getsize', return_value=0):
            handler.start()
            
        # Verify it skipped the primary and used fallback
        self.assertIn("fallback_logs", handler._filepath)

    def test_07_log_queue_capacity_drop(self):
        """TC-07: Drop records non-blockingly when queue is full"""
        config = LogConfig("./logs", False, 1000, queue_capacity=2, drain_timeout_s=1)
        handler = LogHandler(config)
        
        # Manually flag as started so the queue accepts logs
        handler._is_started = True 
        
        # Flood the queue
        handler._enqueue("MSG 1")
        handler._enqueue("MSG 2")
        handler._enqueue("MSG 3") # Should drop
        handler._enqueue("MSG 4") # Should drop
        
        self.assertEqual(len(handler._queue), 2)
        self.assertEqual(handler.metrics.dropped_record_count, 2)

    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('os.rename')
    @patch('os.path.exists', return_value=False)
    def test_08_log_rotation(self, mock_exists, mock_rename, mock_open):
        """TC-08: Rotate file when max_bytes exceeded"""
        config = LogConfig("./logs", False, max_bytes=100, queue_capacity=10, drain_timeout_s=1)
        handler = LogHandler(config)
        handler._filepath = "test.log"
        handler._current_file = MagicMock()
        
        # Simulate rotation condition
        handler._rotate()
        mock_rename.assert_called_once_with("test.log", "test.log.1")

    def test_09_log_disk_full_truncate(self):
        """TC-09: Revert partial writes via truncate on IOError"""
        config = LogConfig("./logs", False, 1000, 10, 1)
        handler = LogHandler(config)
        handler._current_file = MagicMock()
        handler._current_file_size = 50
        
        # Simulate disk full OSError during write
        handler._current_file.write.side_effect = OSError("No space left on device")
        
        handler._safe_write("NEW LOG LINE")
        
        # Ensure it attempted to truncate back to original size (50)
        handler._current_file.truncate.assert_called_once_with(50)
        self.assertEqual(handler.metrics.write_error_count, 1)
        
# ---------------------------------------------------------
    # INTEGRATION TEST
    # ---------------------------------------------------------

    @patch('uart.serial_handler.serial.Serial')
    def test_10_service_integration(self, mock_serial_class):
        """TC-10: Service Layer links UART callbacks to Log Handler correctly"""
        mock_serial_instance = MagicMock()
        mock_serial_instance.in_waiting = 1 # Fixes the TypeError by providing a real integer
        mock_serial_class.return_value = mock_serial_instance
        
        service = FirmwareService()
        
        # Suppress actual file IO for the test
        with patch('builtins.open', unittest.mock.mock_open()), \
             patch('os.path.getsize', return_value=0), \
             patch('os.makedirs'):
             
            service.start()
            
            # Simulate receiving a valid frame from hardware
            service.uart_driver._rx_buffer.extend(b"CMD_TEST\n")
            service.uart_driver._process_buffer()
            
            # The service callback `_on_uart_frame` should have fired and tried to send an ACK
            mock_serial_instance.write.assert_called_with(b"ACK:CMD_TEST\n")
            
            service.stop()

if __name__ == '__main__':
    unittest.main(verbosity=2)
