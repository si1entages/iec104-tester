<p align="center">
  <img src="resources/icon.svg" width="128" height="128" alt="IEC 104 Tester Logo">
</p>

<h1 align="center">IEC 60870-5-104 Tester</h1>

<p align="center">
  <a href="README_eng.md">English</a> | <a href="README.md">中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/WebUI-aiohttp-41CD52" alt="Web UI">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/IEC--104-Complete-brightgreen.svg" alt="IEC 104">
  <img src="https://img.shields.io/badge/Tests-235+-brightgreen.svg" alt="Tests">
</p>

---

Industrial IEC 60870-5-104 testing tool: dual-window **Web UI** (master + slave), full protocol engine, multi-station, packet capture/replay, network fault injection, and YAML scripted tests.

## Features

### Protocol (`core/protocol`)

- 59 ASDU types, APCI I/S/U, k-w flow control, t0–t3 timers
- STARTDT/STOPDT/TESTFR state machine, CP24/CP56 time tags, quality bits
- File transfer, parameter commands

### Master (Web UI)

- Connect/reconnect, GI / **group interrogation (QOI 0–23)**, CI, clock sync, reset, test
- Single/double commands, setpoints, read, parameters, file directory/select/request
- Typed definition table, batch enable/group, YAML import/export, CSV/session export
- Live frames (U/S/I + TypeID summary) and event log

### Slave (Web UI)

- Multi-client TCP server, system commands, DEACT, SOE/spontaneous
- Editable point table (toggle YX, set YC with spontaneous send)
- **Response injection** (delay, drop, corrupt, no-response, quality)
- Manual/auto simulation, YAML point table

### CLI tools

- `run_multi_station.py`, `capture_tool.py`, `sim_tool.py`, `run_tests.py`

### Tests

- `pytest tests/` (**235+** including Web API), conformance suite (42), YAML scripts

## Quick start

```bash
pip install -r requirements.txt
python apps/web_slave.py --http-port 8766
python apps/web_master.py --http-port 8765
# or both:
python apps/web_lab.py
```

Open `http://127.0.0.1:8765/` (master) and `http://127.0.0.1:8766/` (slave), or use pywebview windows.

## Install

```bash
pip install -r requirements.txt
# deps: PyYAML, aiohttp, pywebview (optional shell); dev: pytest, pytest-asyncio
```

## CLI

```bash
python app.py --mode master
python app.py --mode slave --port 2404
python app.py --mode slave --no-gui
python run_tests.py tests/scripts/
python tests/conformance/test_conformance.py
python capture_tool.py record|play|analyze ...
python sim_tool.py --preset poor_wifi
python run_multi_station.py --stations 3
```

## Project layout

```
apps/ webui/ core/{protocol,engine,transport,data,capture,simulation,testing}
run_tests.py run_multi_station.py capture_tool.py sim_tool.py
configs/ resources/ tests/ build/ requirements.txt
```

## License

MIT — see [LICENSE](LICENSE).
