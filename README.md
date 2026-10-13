# README: Firmware Architecture (UART, Log, Service)

**Dated:** 12-10-2026  
**Core Components:** SerialHandler & LogHandler  
**Type:** Technical Documentation & Architecture Reference

## Overview
The architecture is organized into three strictly decoupled modules. It relies on asynchronous background threading, and strict hardware/memory safeguards.

*   **Log Module:** logging system designed to replace Python's standard library logs
*   **UART Module:** A two-layer serial driver and serial handler
*   **Service Layer:** The core orchestrator that connects the modules and handles overall application execution.

---

## Directory Structure
```text
firmware_project/
├── log/
│   ├── log_exceptions.py
│   ├── log_config.py
│   ├── log_metrics.py
│   └── log_handler.py
├── uart/
│   ├── serial_exceptions.py
│   ├── serial_config.py
│   ├── serial_handler.py
│   └── serial_driver.py
└── service/
    └── service_layer.py
