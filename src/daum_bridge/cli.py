from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from . import __version__
from .bridge import DaumBridge
from .config import Config, get_env_overrides
from .serial.port import list_serial_ports
from .web.app import create_app

app = typer.Typer(name="daum-bridge", help="Bridge Daum 8008 TRS to MyWhoosh via BLE FTMS")
console = Console()


def setup_logging(level: str = "INFO", log_file: str = None):
    handlers = [logging.StreamHandler()]
    if log_file:
        try:
            handlers.append(logging.FileHandler(log_file))
        except Exception:
            pass
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


@app.command()
def version():
    """Show version."""
    console.print(f"daum-bridge {__version__}")


@app.command()
def calibrate(
    port: Optional[str] = typer.Option(None, "--port", "-p", help="Serial port"),
    seconds: int = typer.Option(15, "--seconds", "-s", help="Capture duration"),
    write_config: bool = typer.Option(False, "--write-config", help="Show config suggestions"),
):
    """Calibrate serial protocol offsets by capturing raw frames."""
    from .serial.port import auto_detect_daum_port, open_serial, list_serial_ports
    from .config import Config, get_env_overrides
    import time
    
    cfg = Config.load()
    cfg = get_env_overrides(cfg)
    if port:
        cfg.serial.port = port
    p = cfg.serial.port or auto_detect_daum_port()
    if not p:
        console.print("[red]No serial port found[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]Capturing on {p} for {seconds}s...[/green]")
    try:
        ser = open_serial(p, cfg.serial.baudrate, cfg.serial.timeout, cfg.serial.bytesize, cfg.serial.parity, cfg.serial.stopbits)
        proto = DaumProtocol(ser, log_raw=True)
        proto.request_address()
        time.sleep(1)
        frames = []
        start = time.time()
        while time.time() - start < seconds:
            data = ser.read(ser.in_waiting) if hasattr(ser, 'in_waiting') and ser.in_waiting else b''
            if data:
                frames.append(data.hex())
                proto.parse(data)
            time.sleep(0.01)
        console.print(f"[green]Captured {len(frames)} frame chunks[/green]")
        if proto._raw_log:
            console.print(f"Total raw chunks: {len(proto._raw_log)}")
        console.print("Suggested offsets (from daumUSB.js compatible):")
        console.print("  power: offset +5 (raw * 5)")
        console.print("  cadence/rpm: offset +6")
        console.print("  gear: offset +16")
        console.print("  hr: scan offsets 4-10 in person data (0xA2)")
        console.print("\nSet logging.log_raw_frames: true and save frames for tuning.")
        ser.close()
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)


@app.command()
def scan():
    """Scan for serial ports."""
    ports = list_serial_ports()
    if not ports:
        console.print("[yellow]No serial ports found[/yellow]")
        raise typer.Exit()
    table = Table(title="Serial Ports")
    table.add_column("Device")
    table.add_column("Description")
    table.add_column("HWID")
    for p in ports:
        table.add_row(p["device"], p["description"] or "", p["hwid"] or "")
    console.print(table)


@app.command()
def run(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
    port: Optional[str] = typer.Option(None, "--port", "-p", help="Serial port (overrides config)"),
    no_web: bool = typer.Option(False, "--no-web", help="Disable web UI"),
    no_ble: bool = typer.Option(False, "--no-ble", help="Disable BLE FTMS backend"),
    log_file: Optional[str] = typer.Option(None, "--log-file", help="Log to file"),
):
    """Run the bridge."""
    cfg = Config.load(config)
    cfg = get_env_overrides(cfg)
    if port:
        cfg.serial.port = port
    if no_web:
        cfg.web.enabled = False
    if no_ble:
        cfg.ble.enabled = False
    
    setup_logging(getattr(cfg.logging, 'level', 'INFO'), log_file)
    log = logging.getLogger("daum_bridge")
    log.info("Starting daum-bridge %s", __version__)
    errs = cfg.validate()
    for e in errs:
        log.warning("Config: %s", e)
    
    bridge = DaumBridge(cfg)
    try:
        bridge.connect()
        bridge.start()
        log.info("Bridge connected and running")
    except Exception as e:
        log.error("Failed to start bridge: %s", e)
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)
    
    if cfg.web.enabled:
        log.info("Starting web UI on http://%s:%d", cfg.web.host, cfg.web.port)
        app_fastapi = create_app(bridge)
        uvicorn.run(app_fastapi, host=cfg.web.host, port=cfg.web.port, log_level="warning")
    else:
        log.info("Web UI disabled, running in headless mode. Press Ctrl+C to stop.")
        try:
            while True:
                pass
        except KeyboardInterrupt:
            bridge.stop()


if __name__ == "__main__":
    app()
