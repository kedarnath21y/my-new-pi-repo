# README: Firmware Architecture (UART, Log, Service)

**Dated:** 12-10-2026  
**Core Components:** SerialHandler & LogHandler  
**Type:** Technical Documentation & Architecture Reference

## Overview
The architecture is organized into three strictly decoupled modules. It relies on dependency injection, asynchronous background threading, and strict hardware/memory safeguards.

*   **Log Module:** An asynchronous logging system designed to replace Python's standard library logger. It ensures the system never crashes because the disk is full or locked.
*   **UART Module:** A two-layer serial driver that converts raw, unstable hardware signals into clean, safe software events.
*   **Service Layer:** The core orchestrator that connects the modules using dependency injection and handles overall application execution.

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
