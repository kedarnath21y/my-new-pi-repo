class LogConfig:
    def __init__(self, log_dir: str, console_output: bool, max_bytes: int, queue_capacity: int, drain_timeout_s: float):
        self.log_dir = log_dir
        self.console_output = console_output
        self.max_bytes = max_bytes
        self.queue_capacity = queue_capacity
        self.drain_timeout_s = drain_timeout_s

        if self.max_bytes <= 0 or self.queue_capacity <= 0 or self.drain_timeout_s <= 0:
            raise ValueError("Log configuration parameters must be positive.")
