<p align="center">
  <img src="resources/logo.svg" width="608" height="160" alt="IEC 104 Tester">
</p>

<h1 align="center">IEC 60870-5-104 Tester</h1>

<p align="center">
  <a href="README_eng.md">English</a> | <a href="README.md">中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.10.0-blue.svg" alt="Version">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/WebUI-aiohttp%20%2B%20React19-41CD52" alt="Web UI">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/IEC--104-72%20TypeIDs-brightgreen.svg" alt="IEC 104">
  <img src="https://img.shields.io/badge/Tests-1711%20passed-brightgreen.svg" alt="Tests">
</p>

---

Industrial-grade IEC 60870-5-104 testing tool: a **single-page browser workbench** for
master and slave (the browser is the only UI — one process, one port, switch roles from
the side menu), with a complete protocol engine, three switchable UI kits, SCD point-table
import, a transparent bridge with bypass compliance monitoring and chaos injection,
packet capture/replay, YAML scripted tests, load-test orchestration, test-report export,
TLS encryption and a history DB.

> Release baseline **v1.10.0** (2026-11-10) — Excel point-table import with
> design-vs-as-built diff, offline capture diff (before/after upgrade), and a bridge
> injection timeline with automatic verdicts. Per-version details in
> [`CHANGELOG.md`](CHANGELOG.md); delivered scope and the next iteration in
> [`PROJECT.md`](PROJECT.md).

### Screenshots

| Master workbench | Slave workbench |
|---|---|
| ![master](docs/pr-assets/webui-master.png) | ![slave](docs/pr-assets/webui-slave.png) |
| **Capture / pcap export** | **Test center** |
| ![capture](docs/pr-assets/webui-capture.png) | ![tests](docs/pr-assets/webui-tests.png) |

## Features

### Protocol (`core/protocol`)

- **72 defined TypeIDs**: all constructible and decodable (standard types plus CP24,
  protection events, grouped single points, no-quality and bit-pattern variants)
- APCI I/S/U, k-w flow control, t0–t3 timers, STARTDT/STOPDT/TESTFR state machine
- CP24/CP56 time tags; quality descriptors standardized per **IEC 60870-5-101**
  (`IV/NT/SB/BL/OV`, five positions)
- **File transfer** (F_FR/F_SR/F_SC/F_LS/F_AF/F_SG/F_DR and F_*_NB ACKs) with
  byte-level semantics verified against independent reference implementations and
  interoperated against a third-party lib60870-C v2.4.1 slave
- **TLS transport encryption** (CA verification, mutual TLS). ⚠ Transport-layer
  encryption only — **not** full IEC 62351 compliance; see [`docs/tls.md`](docs/tls.md)
- Vendor-private TypeID registration via YAML; unregistered types still reply COT=42

### Web UI (three switchable UI kits, dark/light themes)

- **Three kits on the same URL** — `Carbon` (IBM Carbon Design System, default) /
  `PatternFly 6` / `classic` (antd 6, frozen v1.3.1 snapshot) switch inside `/app/`
  without a reload: page, theme, language, WS and connection are preserved;
  see [`docs/ui_kits.md`](docs/ui_kits.md)
- **Master workbench**: 100k-row virtualized point table, command panel
  (system/control/setpoint/step/bitstring/delay/parameter/file), live frame viewer with
  per-segment HEX hover translation, per-point trend chart, **clock-offset measurement**
  (ms offset derived from the slave clock in its ACK), **design-vs-as-built diff card**
  (importing an xlsx point table snapshots a design baseline; missing / extra / range-or-type
  mismatches are listed — device IOAs that do not match the demo table become obvious)
- **Slave workbench**: point-table editing/manual values, response injection
  (delay/drop/corrupt/no-response/quality/wrong COT), manual/auto simulation with
  independent YX/YC switches, **SCD/CID/ICD import** (IEC 61850-80-1 exact mapping first,
  CDC inference otherwise — preview before apply), **Excel(xlsx) point-table import**
  (English/Chinese headers, Chinese type aliases, row-level error collection, preview)
- **Multi-station page**: station cards and aggregated status
- **Bridge observation page** (`--mode bridge`, 8767): **transparent bridge / bypass
  monitoring** between a real master and a real slave; byte-level pass-through
  (forwarding first, parsing purely on the side), per-direction frame/byte/client/
  resync stats, live frames; **protocol compliance monitor** (transport: sequence/
  ACK/U-sequence/k/t1/t2/t3; application: direction mismatch, unrequested response,
  unterminated GI, data outside interrogation, COT=0, common-address mismatch, repeated
  spontaneous frames, time-tag skew — 28 rules), violations land in the page and the
  test report; **network-condition injection (chaos)**: drop/duplicate/corrupt/delay/
  reorder/disconnect rates on the forwarding path while observation and compliance
  monitoring always see the **pre-injection** frames; injection stats included in the
  report; **injection timeline + automatic verdict**: scripted steps (label/duration/
  loss%/delay/expect) with per-window evidence collection and automatic verdicts
  (e.g. "inject loss → k-window exceed"), results included in the test report;
  **TLS bridge** with independent TLS per side (plaintext↔TLS mixed bridging,
  TLS terminated at the bridge so frames stay visible)
- **Capture page**: start/pause/stop recording, file list/download, one-click pcap/pcapng
  export (Wireshark-ready), offline playback (play/pause/step/speed), **offline capture
  diff** (two recordings compared on normalized frame signatures; sequence numbers,
  timestamps and client IDs are ignored)
- **Test center**: pick `tests/scripts/*.yaml`, run in isolated subprocesses with live logs,
  pass/fail summary and HTML/JSON/TXT report downloads; **load-test orchestration**
  (1–10000 events/s, configurable duration, **1–8 concurrent connections** with per-
  connection frame/byte/error stats)
- **Status page**: one-click **test report** export (self-contained single HTML — print to
  PDF; session info, frame stats, per-frame decoded evidence, event table, load-test
  summary, pass/fail/conditional **conclusion banner** and history chart snapshots);
  one-click diagnostics ZIP; data/frame record export
- **History page**: query data and frames by time/type/IOA/direction, export CSV;
  **"Curves" tab** replays 1–8 history series (YX/YM as steps, YC as lines)
- **Logs page**: structured logs with level/category/source filters, search, pause/clear,
  JSONL export
- Dark/light theme follows the system on first launch and remembers manual choice
- **zh/en UI switching** (header "中 / EN"): fully bilingual; `npm run i18n:inventory`
  reports 0 remaining
- WebSocket live refresh; button availability driven by server state; API responses
  validated against a single-source contract schema on every call
- Security: `--auth-token`, `--web-tls-cert/--web-tls-key` HTTPS, CSP/X-Frame-Options/
  Referrer-Policy headers; WCAG AA text and non-text contrast gates, automated UI audit
  and visual-regression baselines

### Master (`core/engine/master.py`)

- Connect/reconnect, **redundant dual channel** (primary/standby switching + dedup)
- GI / **group interrogation (groups 1–16; 20 = station GI)**, counter interrogation,
  clock sync, reset, test command
- Single/double commands (SBO two-stage/direct), setpoints, read, parameters,
  file directory/select/request/ack
- Point auto-learning, periodic GI, batch enable/group, YAML import/export,
  CSV/session JSON export
- Double-click a point value to send a command (YK/YC/STEP with confirmation; SBO is
  still select-before-execute)

### Slave (`core/engine/slave.py`)

- Multi-client TCP server; system commands; DEACT; SOE/spontaneous reporting
- Editable point table; manual values; YAML point table; STEP position modeling
- **Response injection** (delay, drop, corrupt, no-response, quality, wrong COT)
- **Command feedback** (real-device semantics: control → same-IOA YX change,
  setpoint → same-IOA YC update, step → position update, sent as time-tagged COT=3)
- Manual/auto simulation with **independent YX/YC switches**
- **SCD/CID/ICD point-table import** (IEC 61850-80-1 exact mapping first, DOType `cdc`
  inference otherwise; preview with warnings and editable YAML before applying)

### Data, operations and quality

- **History DB on by default** (SQLite, per-role file), disable with `--no-history`;
  retention/count/size cleanup; **Web "History" page** queries data/frame records
  (time/type/IOA/direction filters) and exports CSV
- **Capture export**: `.i104` / `.json` / **pcap / pcapng** (Wireshark-ready)
- **One-click diagnostics**: status/config (private-key path redacted)/logs/frames/events/
  points/history stats as a ZIP (status-page button or `GET /api/diagnostics/export`)
- **One-command loopback demo**: `python app.py --demo`
- Quality gates: interop corpus replay, Hypothesis fuzz, 20-client concurrency,
  2-hour loopback soak, combined branch coverage **91.3%** (gate 91%, separate webui gate
  85%), 12/12 mutation smoke killed
- Multi-station (`run_multi_station.py`), network fault injection (status-page card /
  `sim_tool.py`), YAML scripted tests (`run_tests.py`)
- **Test report export** (self-contained HTML with frame evidence, conclusion banner and
  chart snapshots), **load-test orchestration** (throughput acceptance, 1–8 connections),
  **redundant dual channel** (see [`docs/redundancy.md`](docs/redundancy.md))

### Packaging and release

- `python build/build_all.py` produces **one** portable app directory `dist/iec104-tester/`
  (web UI, configs and resources included); `--onefile` produces **one** executable
  (`iec104-tester.exe` on Windows)
- Double-clicking the exe starts **master + slave together** in **one process on one
  HTTP port (8765)**; the sidebar has **two menu entries** (Master Workbench / Slave
  Workbench) that swap the workbench inside the same page. Slave APIs live under
  `/slave/api` + `/slave/ws`; the CLI supports `iec104-tester --mode master|slave|both|bridge`
- Pushing a `v*` tag runs the release pipeline: version check → Windows/Linux onefile
  builds → startup smoke for **the same exe in both roles** → `SHA256SUMS` → GitHub Release

## Quick start

```bash
pip install -r requirements.txt

# default: start both roles and open one single-page workbench
python app.py

# explicit single role (opens the browser)
python app.py --mode master    # http://127.0.0.1:8765/
python app.py --mode slave     # http://127.0.0.1:8766/
python app.py --mode both      # default: one process/port, two role menu entries

# transparent bridge / bypass observation (point the real master at the bridge port)
python app.py --mode bridge --listen-port 2404 --upstream-host 192.168.1.50 \
    --upstream-port 2404

# one-command loopback demo: slave + master + auto connect + GI
python app.py --demo

# headless/server: no browser, just print the URL
python app.py --mode master --no-browser --http-port 8765
```

`--demo` starts both roles in one process/port, enables the slave listener, connects the
master and performs a GI, then opens the workbench. Use `--demo-seconds N` to stop
automatically; `Ctrl+C` stops the process.

Manual interop: start master and slave in two terminals → slave page “Start listening” →
master page “Connect local” → “GI now”.

## Install

```bash
git clone https://github.com/si1entages/iec104-tester.git
cd iec104-tester
python -m venv venv
# Windows:
venv\Scripts\pip install -r requirements.txt
# Linux/macOS:
venv/bin/pip install -r requirements.txt
```

Runtime deps: `PyYAML`, `aiohttp`.

```bash
# development/test (pytest, pytest-asyncio, pytest-cov, hypothesis, psutil, ruff)
pip install -e ".[dev]"

# packaging (pyinstaller)
pip install -e ".[build]"
```

## CLI

```bash
python app.py --mode master
python app.py --mode slave --port 2404
python app.py --demo
python app.py --mode slave --no-gui
python app.py --mode slave --no-history
python run_tests.py tests/scripts/
python tests/conformance/test_conformance.py
python capture_tool.py record|play|analyze ...
python capture_tool.py convert session.i104 -o session.pcap
python sim_tool.py --preset poor_wifi
python run_multi_station.py --stations 3
```

## Tests

```bash
python -m pytest tests/ -q              # unit + integration (1667; perf excluded)
python -m pytest tests/ -q --cov=core --cov-branch --cov-report=term-missing --cov-fail-under=91
python -m pytest tests/ -m perf -q      # decode / 100k snapshot / 20 clients / soak
IEC104_SOAK_SECONDS=7200 python -m pytest tests/perf/test_soak_loopback.py -m perf -q
python run_tests.py tests/scripts/
python tests/e2e/qa_full_flow.py
python tests/e2e/qa_webui_e2e.py --spawn
python tests/e2e/qa_real_device.py
python tools/mutation_smoke.py
```

- Baseline: **1711 passed, 4 deselected** (v1.10.0) + frontend unit tests
  **133 passed** + Playwright e2e **61 passed** (page-level gates — audit / contrast /
  non-text contrast — run on **both Carbon and PatternFly**; the bridge page is swept via
  the dedicated 8769 server; tunable via `E2E_KITS=pf,carbon`); combined branch coverage
  **91.11%** (CI scope `--cov=core --cov=webui --cov-branch --cov-fail-under=91`;
  separate webui gate 85%)
- 20-client concurrency: about **2.9k frames/s**; 2-hour soak: **7200s / 34,765 GI /
  +0.64 MB memory**
- Interop corpus: `tests/fixtures/frames/` (synthetic baseline + `real/` for user-provided
  device captures); golden decode and master replay in `tests/test_frame_corpus_replay.py`
- Fuzz: `tests/test_protocol_fuzz.py` (Hypothesis; APCI/ASDU/file-transfer inputs may only
  raise `ValueError`); conformance suite (50 cases) wired into pytest via
  `tests/test_conformance_suite.py`
- Playwright e2e: API-contract cross-check, UI audit (8 pages × 3 viewports × zh/en/dark),
  WCAG AA contrast, visual-regression baselines — locally run with
  `NODE_PATH=webui/frontend/node_modules` (same as CI)
- Diagnostics: status-page “Export diagnostics” or `GET /api/diagnostics/export`

## Project layout

```
iec104-tester/
├── app.py                 # CLI/Web entry (--demo, --mode both|bridge)
├── apps/                  # source thin entries web_master / web_slave (packaging uses app.py)
├── webui/                 # aiohttp REST+WS + React SPA (built into webui/static/app/)
│   ├── bridge.py          # engine bridge (master/slave/both/bridge roles)
│   ├── diagnostics.py     # one-click diagnostics ZIP
│   ├── report.py          # test report HTML generator
│   ├── server.py
│   ├── frontend/src/      # shared data layer + three UI kits (carbon/ default, pf/, classic/)
│   └── static/app/        # Vite build output
├── core/
│   ├── protocol/          # APCI/ASDU/types/flow control/file transfer/custom types
│   ├── engine/            # master / slave / multi_station / tcp_bridge / compliance_monitor / condition_injector
│   ├── transport/         # TCP / TLS
│   ├── data/              # point table, realtime DB, history DB, SCD import
│   ├── capture/           # recording/playback (.i104/.json/pcap/pcapng)
│   ├── simulation/        # network fault injection
│   └── testing/           # YAML script engine
├── build/build_all.py     # PyInstaller (onedir / --onefile)
├── tools/mutation_smoke.py
├── tests/
│   ├── fixtures/frames/   # interop corpus (synthetic + real/)
│   ├── perf/              # performance/soak benchmarks (-m perf)
│   └── e2e/               # real-socket acceptance scripts + Playwright specs
├── .github/workflows/     # CI + tag-based release
├── run_tests.py / run_multi_station.py / capture_tool.py / sim_tool.py
├── configs/ resources/ docs/
└── requirements.txt
```

## Docs

- Changelog: [`CHANGELOG.md`](CHANGELOG.md) (v1.0.0 → v1.8.0)
- Progress and roadmap: [`PROJECT.md`](PROJECT.md), [`docs/architecture_plan.md`](docs/architecture_plan.md)
- User guide: [`docs/user_guide.md`](docs/user_guide.md)
- UI design guidelines: [`docs/design_guidelines.md`](docs/design_guidelines.md)
- Three UI kits: [`docs/ui_kits.md`](docs/ui_kits.md)
- TLS boundaries: [`docs/tls.md`](docs/tls.md)
- File-transfer byte semantics: [`docs/file_transfer_fls.md`](docs/file_transfer_fls.md)
- File-transfer device-verification checklist/probe: [`docs/file_transfer_open_items.md`](docs/file_transfer_open_items.md)
- pcap export: [`docs/pcap_export.md`](docs/pcap_export.md)
- History DB measurements: [`docs/history.md`](docs/history.md)
- Redundant dual channel: [`docs/redundancy.md`](docs/redundancy.md)
- Interop corpus: [`tests/fixtures/frames/README.md`](tests/fixtures/frames/README.md)
- Performance/soak: [`tests/perf/README.md`](tests/perf/README.md)

## Known limitations (deferred pending external input)

Two items need input from outside this repo (a real device window / real vendor samples), so
only the verified part is implemented — unverified semantics are marked "to be verified" in
code and docs and are **never guessed**:

- **File transfer device re-test**: the five open semantics (NOF / SCQ / WITH_DEACT /
  multi-section / FRQ-SRQ) were filled in with a third-party **lib60870-C v2.4.1** slave and
  three interop fixes followed (file command as `F_SC_NA_1(122)+COT=13`, auto `SCQ=6` section
  request after `F_SR`, dropping the non-standard `F_FR_NB(128)/F_SR_NB(129)`); a **real
  device re-test is still pending**. Checklist and read-only probe:
  [`docs/file_transfer_open_items.md`](docs/file_transfer_open_items.md).
- **Vendor-private SCD mapping**: the IEC 61850-80-1 standard mapping
  (`Private/Address(casdu,ioa,ti)`, `ti` first) is supported; vendor-specific 104 mapping
  extensions need ≥2 real SCD samples to generalize, so DOType `cdc` inference is the fallback.

## License

MIT — see [LICENSE](LICENSE).
