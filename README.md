<p align="center">
  <img src="resources/icon.svg" width="128" height="128" alt="IEC 104 Tester Logo">
</p>

<h1 align="center">IEC 60870-5-104 Tester</h1>

<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Qt-6-41CD52?logo=qt&logoColor=white" alt="Qt 6">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/IEC--104-Complete-brightgreen.svg" alt="IEC 104">
</p>

---

A full-featured IEC 60870-5-104 protocol testing tool with **Master** and **Slave** dual-mode support, real-time data monitoring, packet capture/replay, network anomaly simulation, automated test scripting, and a modern Qt-based GUI.

## ✨ Features

### Protocol

- **Full IEC 60870-5-104 coverage** — 59 ASDU type identifiers
- **APCI layer** — I/S/U frame encode/decode
- **Flow control** — k-w sliding window
- **Timers** — t0/t1/t2/t3 four-level timeout management
- **State machine** — STARTDT/STOPDT/TESTFR full lifecycle
- **Timestamps** — CP24Time2a / CP56Time2a
- **Quality descriptors** — OV/BL/NT/IV

### Master Station

- Connection management (STARTDT/STOPDT)
- General / group interrogation (1–23 groups)
- Counter interrogation, clock sync, process reset
- Single / double command (select-before-operate)
- Setpoint commands (normalized / scaled / short float)
- Auto-reconnect

### Slave Station

- TCP server (multi-client)
- Responds to all system commands
- Spontaneous data upload, SOE event reporting
- Data simulator (manual / random / scripted)
- Point table management (YAML import/export)

### GUI

- **High-performance tables** — virtual scrolling, 100k+ data points
- **Packet viewer** — HEX + protocol decode, color-coded RX/TX
- **Dark / Light theme** — Catppuccin-inspired

### Advanced

- **📡 Packet Capture/Replay** — Record sessions to `.i104`/`.json`, replay with speed control
- **🔧 Network Anomaly Simulation** — Delay, loss, corruption, duplication, reorder, disconnect
- **🧪 Automated Test Scripts** — YAML-driven test sequences with assertions
- **📊 Analysis** — Frame statistics, anomaly detection, protocol decode

## 🚀 Quick Start

```bash
pip install PySide6 PyYAML

# Terminal 1 — Start slave (server)
python app.py --mode slave --port 2404

# Terminal 2 — Start master (client)
python app.py --mode master --host 127.0.0.1 --port 2404
```

## 📦 Installation

```bash
git clone https://github.com/yourname/iec104-tester.git
cd iec104-tester
pip install PySide6 PyYAML
```

## 💻 Usage

```bash
# Master mode
python app.py --mode master --host 192.168.1.100 --port 2404

# Slave mode with custom point table
python app.py --mode slave --point-table configs/demo_points.yaml

# CLI mode (no GUI)
python app.py --mode slave --no-gui --log-level DEBUG

# Run automated test scripts
python run_tests.py tests/scripts/

# Packet capture
python capture_tool.py record --mode master --host 127.0.0.1 -o session.i104
python capture_tool.py play session.i104 --speed 2.0
python capture_tool.py analyze session.i104

# Network anomaly simulation
python sim_tool.py --preset poor_wifi --mode master --host 127.0.0.1
python sim_tool.py --loss 0.1 --delay 50 --mode master
```

### Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--mode` | `master` or `slave` | `master` |
| `--host` | Remote host address | `127.0.0.1` |
| `--port` | TCP port | `2404` |
| `--config` | YAML config file | — |
| `--point-table` | Point table YAML file | — |
| `--no-gui` | Run without GUI | `false` |
| `--test` | Run test script (YAML file or dir) | — |
| `--log-level` | `DEBUG` / `INFO` / `WARNING` / `ERROR` | `INFO` |

## ⚙️ Configuration

```bash
cp resources/config_template.yaml config.yaml
```

```yaml
mode: master
connection:
  host: "192.168.1.100"
  port: 2404
  common_addr: 1
  reconnect: true
timers:
  t0: 30.0    # Connection timeout
  t1: 15.0    # Send confirmation timeout
  t2: 10.0    # Idle acknowledgment timeout
  t3: 20.0    # Idle test timeout
flow_control:
  k: 12       # Max unacknowledged I-frames
  w: 8        # Acknowledgment trigger threshold
```

## 🧪 Automated Test Scripts

```bash
# Run single script
python run_tests.py tests/scripts/basic_connection_gi.yaml

# Run all scripts
python run_tests.py tests/scripts/ -v

# Script format (YAML)
```

```yaml
name: basic_test
description: "Basic connection and GI test"
config:
  role: master
  timeout: 30
  connection: { host: "127.0.0.1", port: 2404 }

steps:
  - action: connect
    assert:
      - type: state
        params: { expected: "connected" }

  - action: wait_state
    params: { state: running, timeout: 10 }

  - action: general_interrogation
    assert:
      - type: frame_count
        params: { direction: tx, frame_type: I, min: 1 }

  - action: disconnect
```

## 📡 Packet Capture & Replay

```bash
# Record
python capture_tool.py record --mode master --host 127.0.0.1 -o session.i104

# Replay (original speed)
python capture_tool.py play session.i104

# Replay (2x speed)
python capture_tool.py play session.i104 --speed 2.0

# Step mode
python capture_tool.py play session.i104 --step

# Analyze
python capture_tool.py analyze session.i104

# Show frames
python capture_tool.py show session.i104 --limit 100 --filter "frame_type=I"

# Convert format
python capture_tool.py convert session.i104 -o session.json
```

## 🔧 Network Anomaly Simulation

```bash
# Presets
python sim_tool.py --preset poor_wifi      # WiFi with packet loss
python sim_tool.py --preset congested      # Network congestion
python sim_tool.py --preset satellite      # High-latency satellite link
python sim_tool.py --preset unreliable     # High packet loss
python sim_tool.py --preset stress         # Combined stress test

# Custom conditions
python sim_tool.py --loss 0.1 --delay 50 --corrupt 0.05 --mode master
```

| Preset | Description |
|--------|-------------|
| `clean` | Normal network |
| `poor_wifi` | Delay 30ms±20ms, 5% loss |
| `congested` | Delay 100ms±50ms, 10% loss |
| `satellite` | Delay 500ms±100ms, 2% loss |
| `unreliable` | 30% loss, 5% corruption |
| `intermittent` | 5% disconnect chance (5s) |
| `slow_link` | 1KB/s bandwidth limit |
| `stress` | All anomalies combined |

## 🏗 Architecture

```
iec104-tester/
├── app.py                          # Entry point
├── run_tests.py                    # Test script runner CLI
├── capture_tool.py                 # Packet capture/replay CLI
├── sim_tool.py                     # Network simulation CLI
├── core/                           # Protocol core (no GUI dependency)
│   ├── protocol/                   # IEC 60870-5-104 implementation
│   ├── transport/                  # TCP async transport
│   ├── engine/                     # Master / Slave engines
│   ├── data/                       # Data models (point table, realtime DB)
│   ├── testing/                    # Automated test script engine
│   ├── capture/                    # Packet capture/replay engine
│   ├── simulation/                 # Network anomaly simulation
│   └── config.py                   # Configuration management
├── gui/                            # PySide6 GUI layer
│   ├── main_window.py              # Main window
│   ├── themes.py                   # Dark / Light themes
│   ├── widgets/                    # Reusable widgets
│   ├── master/                     # Master UI
│   └── slave/                      # Slave UI
├── configs/                        # Preset configurations
├── resources/                      # Icons, styles, templates
├── tests/                          # Protocol tests + test scripts
└── build/                          # Build scripts (Windows/Linux)
```

## 📊 Performance

| Metric | Value |
|--------|-------|
| Table rendering | 100k rows, virtual scroll |
| Refresh cycle | 500ms (configurable) |
| Packet processing | asyncio non-blocking I/O |
| Memory | Ring buffer, auto-cleanup |
| Connections | Up to 16 concurrent |

## 🤝 Contributing

1. Fork this repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [IEC 60870-5-104](https://webstore.iec.ch/en/publication/6270) — International standard for telecontrol protocols
- [PySide6](https://wiki.qt.io/Qt_for_Python) — Qt for Python
- [Catppuccin](https://github.com/catppuccin/catppuccin) — Color palette inspiration

---

<p align="center">
  Made with ⚡ for the power systems community
</p>
