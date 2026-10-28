# AGENTS.md

## Project Overview
- **Purpose**: Bridge Daum 8008 TRS (RS232 via original cable + RS232→USB) to MyWhoosh via BLE FTMS.
- **Language**: Python
- **Tooling**: Use `uv` for dependency management and running commands (`uv run ...`).
- **Runtime**: Bridge runs on Linux (separate PC/RPi); MyWhoosh runs on Windows. BLE FTMS peripheral on Linux/BlueZ.

## Key Files
- `pyproject.toml` - deps/scripts (`daum-bridge` entrypoint)
- `src/daum_bridge/cli.py` - CLI (Typer)
- `src/daum_bridge/serial/daum.py` - Daum protocol (ported from daumUSB.js)
- `src/daum_bridge/bridge.py` - core bridge logic
- `src/daum_bridge/backends/ble_ftms.py` - BLE FTMS peripheral (skeleton, Linux-focused)
- `src/daum_bridge/web/` - FastAPI web UI for status and gear shifting
- `docs/` - overview, protocol, handling docs
- `tests/` - unit tests

## Development Setup
- Install deps: `uv sync`
- Dev deps: `uv sync --dev` (pytest included)
- Scan ports: `uv run daum-bridge scan`
- Run: `uv run daum-bridge run --config config.yaml` (or `uv run daum-bridge run`)
- Tests: `uv run pytest -v`
- Config: copy `config.example.yaml` to `config.yaml`, or use env vars (`DAUM_SERIAL_PORT`, `DAUM_BLE_NAME`, `DAUM_WEB_PORT`)

## Conventions
- Keep changes minimal and documented.
- Prefer `uv` over `pip`/`poetry`/`conda`.
- Add/maintain docstrings for public interfaces (protocol, bridge, backends).
- Document findings about Daum protocol in `docs/protocol.md`.
- If adding config/env vars, update `config.example.yaml` and `docs/handling.md`.
- Hardware-dependent code should be guarded/mocked in tests.
- Web UI is for status and gear shifting (as requested).

## Notes
- Protocol based on weinzmi/daumUSB2BLE/ergoFACE; may need tuning for specific firmware.
- BLE FTMS peripheral is Linux/BlueZ focused; full D-Bus GATT implementation may need completion.
- Auto-detect serial ports with config override supported.
- Bidirectional control: target power from MyWhoosh -> `set_watt`, gear shifts via web UI/CLI.
