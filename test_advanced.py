import os
import time
import threading
import unittest
from unittest.mock import patch, MagicMock

from log.log_config import LogConfig
from log.log_handler import LogHandler
from uart.serial_config import SerialConfig
from uart.serial_exceptions import LinkReadError
from uart.serial_driver import SerialDriver
from service.service_layer import FirmwareService

class FirmwareAdvancedTests(unittest.TestCase):

    # ---------------------------------------------------------
    # UART ADVANCED TESTS
    # ---------------------------------------------------------

    def test_11_uart_multi_frame_processing(self):
        """TC-11: Process multiple concatenated frames in a single chunk."""
        config = SerialConfig("COM1", 115200, b'\n', 256, 1024)
        driver = SerialDriver(config)
        driver._is_open = True
        
        callback_mock = MagicMock()
        driver._on_frame_callback = callback_mock
        
        # Inject two full frames and one partial frame seamlessly
        driver._rx_buffer.extend(b"FRAME_1\nFRAME_2\nPARTIAL")
        driver._process_buffer()
        
        # Verify the callback was fired exactly twice with correct payloads
        self.assertEqual(callback_mock.call_count, 2)
        callback_mock.assert_any_call(b"FRAME_1")
        callback_mock.assert_any_call(b"FRAME_2")
        # Verify partial frame remains in buffer securely
        self.assertEqual(driver._rx_buffer, bytearray(b"PARTIAL"))

    @patch('uart.serial_handler.serial.Serial')
    def test_12_uart_hardware_read_fault(self, mock_serial_class):
        """TC-12: Handle hardware disconnect during continuous read loop."""
        mock_serial_instance = MagicMock()
        mock_serial_instance.in_waiting = 1
        import serial
        # Simulate USB unplugged while trying to read bytes
        mock_serial_instance.read.side_effect = serial.SerialException("Device disconnected")
        mock_serial_class.return_value = mock_serial_instance

        config = SerialConfig("COM1", 115200, b'\n', 256, 1024)
        driver = SerialDriver(config)
        driver.open()

        with self.assertRaises(LinkReadError):
            driver._handler.receive()
            
        self.assertFalse(driver._handler.is_open)

    def test_13_uart_idempotent_open_close(self):
        """TC-13: Ensure open() and close() are idempotent and don't crash if spammed."""
        config = SerialConfig("COM1", 115200, b'\n', 256, 1024)
        driver = SerialDriver(config)
        
        with patch('uart.serial_handler.SerialHandler.open') as mock_open:
            driver.open()
            driver.open() # Spamming open
            driver.open()
            mock_open.assert_called_once() # Should only actually open once

    def test_14_uart_unhandled_callback_exception(self):
        """TC-14: Ensure app-level callback crashes do not kill the UART driver thread."""
        config = SerialConfig("COM1", 115200, b'\n', 256, 1024)
        driver = SerialDriver(config)
        driver._is_open = True
        
        # Create a callback that violently crashes
        def crashing_callback(payload):
            raise ValueError("Application logic failed!")
            
        driver._on_frame_callback = crashing_callback
        driver._rx_buffer.extend(b"POISON_PILL\n")
        
        try:
            driver._process_buffer()
        except Exception:
            self.fail("Driver crashed due to unhandled callback exception!")
            
        # If we reach here, the driver successfully caught the user's error.

# ---------------------------------------------------------
    # LOG ADVANCED TESTS
    # ---------------------------------------------------------

    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('os.rename')
    @patch('os.path.exists', return_value=False)
    def test_15_log_rotation_permission_denied(self, mock_exists, mock_rename, mock_open):
        """TC-15: Trigger file truncation if log rotation fails (e.g. file locked by OS)."""
        config = LogConfig("./logs", False, max_bytes=100, queue_capacity=10, drain_timeout_s=1)
        handler = LogHandler(config)
        handler._filepath = "test.log"
        handler._current_file = MagicMock()
        
        # Simulate OS denying permission to rename the file
        mock_rename.side_effect = OSError("Permission Denied")
        
        handler._rotate()
        
        # Verify it resorted to opening the file in "w" (truncate/overwrite) mode to save disk space
        mock_open.assert_called_with("test.log", "w", encoding="utf-8")
        self.assertEqual(handler.metrics.rotation_error_count, 1)

    def test_16_log_thread_safety_concurrent_writes(self):
        """TC-16: Verify thread safety by bombarding the log queue from 10 threads."""
        config = LogConfig("./logs", False, max_bytes=1000, queue_capacity=5000, drain_timeout_s=1)
        handler = LogHandler(config)
        handler._is_started = True # Manually allow enqueuing
        
        def worker():
            for i in range(100):
                handler._enqueue(f"Thread Log {i}")
                
        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        
        # 10 threads * 100 logs = 1000 logs. If locks failed, this number would be lower.
        self.assertEqual(len(handler._queue), 1000)

    @patch('time.sleep', return_value=None) # Speed up test
    def test_17_log_zero_byte_write_detection(self, mock_sleep):
        """TC-17: Handle hardware glitch returning 0 bytes written."""
        config = LogConfig("./logs", False, 1000, 10, 1)
        handler = LogHandler(config)
        handler._current_file = MagicMock()
        
        # Simulate hardware returning 0 bytes written (Disk full/ReadOnly glitch)
        handler._current_file.write.return_value = 0
        
        handler._safe_write("TEST LOG")
        
        # Verify write error was counted
        self.assertEqual(handler.metrics.write_error_count, 1)

    def test_18_log_graceful_stop_pending_records(self):
        """TC-18: Verify remaining queue drops are counted if thread is killed."""
        config = LogConfig("./logs", False, 1000, 10, 1)
        handler = LogHandler(config)
        handler._is_started = True
        handler._queue = ["MSG1", "MSG2", "MSG3"]
        
        handler.stop()
        
        # Queue should be cleared, and dropped records should increment by 3
        self.assertEqual(len(handler._queue), 0)
        self.assertEqual(handler.metrics.dropped_record_count, 3)

# ---------------------------------------------------------
    # INTEGRATION ADVANCED TESTS
    # ---------------------------------------------------------

    @patch('uart.serial_handler.serial.Serial')
    def test_19_service_error_propagation(self, mock_serial_class):
        """TC-19: Verify UART background errors trigger the Service error callback."""
        mock_serial_instance = MagicMock()
        import serial
        
        # --- FIX: Provide a valid integer so the thread doesn't crash on max(1, Mock) ---
        mock_serial_instance.in_waiting = 1 
        
        # Force a read error immediately
        mock_serial_instance.read.side_effect = serial.SerialException("Spontaneous failure")
        mock_serial_class.return_value = mock_serial_instance
        
        service = FirmwareService()
        
        # Spy on the error callback
        service._on_uart_error = MagicMock()
        
        with patch('builtins.open', unittest.mock.mock_open()), \
             patch('os.path.getsize', return_value=0), \
             patch('os.makedirs'):
             
            service.start()
            time.sleep(0.1) 
            
            # The Service layer should have been notified of the error
            service._on_uart_error.assert_called_once()
            service.stop()

    def test_20_service_logger_dependency_injection(self):
        """TC-20: Ensure UART driver correctly utilizes the injected Service logger."""
        service = FirmwareService()
        
        # Inject a spy logger
        spy_logger = MagicMock()
        service.uart_driver._logger = spy_logger
        
        # Trigger an action that should log (e.g., config error / buffer overflow)
        service.uart_driver._rx_buffer.extend(b"x" * 2000)
        service.uart_driver._process_buffer()
        
        # Verify the injected logger caught the error, proving DI works
        spy_logger.error.assert_called_once()

if __name__ == '__main__':
    unittest.main(verbosity=2)
