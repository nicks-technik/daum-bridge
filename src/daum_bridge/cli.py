from __future__ import annotations

import json
import logging
import urllib.parse
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
    from .serial.daum import DaumProtocol
    from .serial.port import auto_detect_daum_port, open_serial
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


@app.command("strava-auth")
def strava_auth(
    client_id: Optional[str] = typer.Option(None, "--client-id", help="Strava API client id"),
    client_secret: Optional[str] = typer.Option(None, "--client-secret", help="Strava API client secret"),
    code: Optional[str] = typer.Option(None, "--code", help="Authorization code (or full redirect URL)"),
    redirect_uri: str = typer.Option(
        "http://localhost", "--redirect-uri", help="Redirect URI configured in the Strava app"
    ),
    scope: str = typer.Option(
        "activity:write,activity:read", "--scope", help="OAuth scopes to request"
    ),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
    write_config: bool = typer.Option(
        False, "--write-config", help="Store client id/secret/refresh token in config.yaml"
    ),
):
    """Authorize daum-bridge with Strava and cache the refresh token."""
    from .integrations.strava import StravaClient, StravaError

    cfg = get_env_overrides(Config.load(config))
    if client_id:
        cfg.strava.client_id = client_id
    if client_secret:
        cfg.strava.client_secret = client_secret
    if not cfg.strava.client_id or not cfg.strava.client_secret:
        console.print(
            "[red]client_id and client_secret are required. Pass "
            "--client-id/--client-secret or set STRAVA_CLIENT_ID/STRAVA_CLIENT_SECRET.[/red]"
        )
        raise typer.Exit(code=1)

    client = StravaClient.from_config(cfg.strava)
    url = client.authorization_url(redirect_uri=redirect_uri, scope=scope)
    console.print("1. Open this URL in a browser and authorize daum-bridge:")
    console.print(url)
    if not code:
        code = typer.prompt("2. Paste the authorization code (or the full redirect URL)")
    code = code.strip()
    if "code=" in code:
        parsed = urllib.parse.urlparse(code)
        values = urllib.parse.parse_qs(parsed.query).get("code")
        if values:
            code = values[0]

    try:
        client.exchange_code(code, redirect_uri=redirect_uri)
    except StravaError as e:
        console.print(f"[red]Authorization failed: {e}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]Authorized. Tokens cached in {client.token_file}.[/green]")
    console.print(f"Refresh token: {client.refresh_token}")
    if write_config:
        _write_strava_config(config, client)


def _write_strava_config(config: Optional[Path], client) -> None:
    path = Path(config) if config else Path("config.yaml")
    try:
        from .config import dump_yaml_file, load_yaml_file

        data = load_yaml_file(path)
        data.setdefault("strava", {})
        data["strava"].update({
            "client_id": client.client_id,
            "client_secret": client.client_secret,
            "refresh_token": client.refresh_token,
            "token_file": client.token_file,
        })
        dump_yaml_file(path, data)
        console.print(f"[green]Updated {path}[/green]")
    except Exception as e:
        console.print(f"[yellow]Could not update {path}: {e}[/yellow]")


@app.command("strava-upload")
def strava_upload(
    ride: Optional[Path] = typer.Option(
        None, "--ride", "-r", help="Ride JSON file (default: latest recorded ride)"
    ),
    name: Optional[str] = typer.Option(None, "--name", help="Activity name"),
    description: Optional[str] = typer.Option(None, "--description", help="Activity description"),
    private: Optional[bool] = typer.Option(
        None, "--private/--public", help="Override the configured privacy setting"
    ),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
):
    """Upload a recorded ride to Strava as a TCX activity."""
    from . import history
    from .integrations.strava import StravaClient

    cfg = get_env_overrides(Config.load(config))
    if ride:
        try:
            with Path(ride).open("r", encoding="utf-8") as f:
                ride_data = json.load(f)
        except (OSError, ValueError) as e:
            console.print(f"[red]Could not read ride file {ride}: {e}[/red]")
            raise typer.Exit(code=1)
    else:
        ride_data = history.latest_ride(include_samples=True)
    if not ride_data:
        console.print("[red]No recorded ride found in the rides directory.[/red]")
        raise typer.Exit(code=1)

    client = StravaClient.from_config(cfg.strava)
    if not client.is_configured():
        console.print(
            "[red]Strava is not configured. Run 'daum-bridge strava-auth' first.[/red]"
        )
        raise typer.Exit(code=1)

    console.print(f"Uploading ride {ride_data.get('id', '')} to Strava...")
    result = client.upload_ride(
        ride_data,
        name=name,
        description=description,
        private=cfg.strava.private if private is None else private,
    )
    if result.get("ok"):
        activity_id = result.get("activity_id")
        if activity_id:
            console.print(
                f"[green]Uploaded.[/green] https://www.strava.com/activities/{activity_id}"
            )
        else:
            console.print(f"[green]Upload accepted.[/green] {result}")
    else:
        console.print(f"[red]Upload failed: {result.get('error')}[/red]")
        raise typer.Exit(code=1)


@app.command("email-ride")
def email_ride(
    ride: Optional[Path] = typer.Option(
        None, "--ride", "-r", help="Ride JSON file (default: latest recorded ride)"
    ),
    to: Optional[str] = typer.Option(
        None, "--to", help="Recipient (default: email.to_addr from config)"
    ),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config.yaml"),
):
    """Email a recorded ride as a TCX attachment."""
    from . import history
    from .integrations.emailer import send_ride_email

    cfg = get_env_overrides(Config.load(config))
    if ride:
        try:
            with Path(ride).open("r", encoding="utf-8") as f:
                ride_data = json.load(f)
        except (OSError, ValueError) as e:
            console.print(f"[red]Could not read ride file {ride}: {e}[/red]")
            raise typer.Exit(code=1)
    else:
        ride_data = history.latest_ride(include_samples=True)
    if not ride_data:
        console.print("[red]No recorded ride found in the rides directory.[/red]")
        raise typer.Exit(code=1)

    if not cfg.email.is_configured():
        console.print(
            "[red]Email is not configured. Set email.host/from_addr/to_addr in "
            "config.yaml or DAUM_EMAIL_HOST/DAUM_EMAIL_FROM/DAUM_EMAIL_TO.[/red]"
        )
        raise typer.Exit(code=1)

    result = send_ride_email(ride_data, cfg.email, to=to)
    if result.get("ok"):
        console.print(f"[green]Emailed {ride_data.get('id', 'ride')} to {result.get('to')}[/green]")
    else:
        console.print(f"[red]Email failed: {result.get('error')}[/red]")
        raise typer.Exit(code=1)


@app.command("export-tcx")
def export_tcx(
    ride: Optional[Path] = typer.Option(
        None, "--ride", "-r", help="Ride JSON file (default: latest recorded ride)"
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output file (default: rides/<ride-id>.tcx)"
    ),
):
    """Export a recorded ride as TCX (for manual upload, no Strava API needed)."""
    from . import history
    from .integrations.tcx import build_tcx

    if ride:
        try:
            with Path(ride).open("r", encoding="utf-8") as f:
                ride_data = json.load(f)
        except (OSError, ValueError) as e:
            console.print(f"[red]Could not read ride file {ride}: {e}[/red]")
            raise typer.Exit(code=1)
    else:
        ride_data = history.latest_ride(include_samples=True)
    if not ride_data:
        console.print("[red]No recorded ride found in the rides directory.[/red]")
        raise typer.Exit(code=1)

    try:
        tcx = build_tcx(ride_data)
    except Exception as e:
        console.print(f"[red]Could not build TCX: {e}[/red]")
        raise typer.Exit(code=1)

    target = Path(output) if output else history.rides_dir() / f"{ride_data.get('id') or 'ride'}.tcx"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(tcx, encoding="utf-8")
    except OSError as e:
        console.print(f"[red]Could not write {target}: {e}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]Exported {target}[/green]")
    console.print("Upload it manually at https://www.strava.com/upload/select")


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
        try:
            uvicorn.run(app_fastapi, host=cfg.web.host, port=cfg.web.port, log_level="warning")
        finally:
            bridge.stop()
    else:
        log.info("Web UI disabled, running in headless mode. Press Ctrl+C to stop.")
        try:
            while True:
                pass
        except KeyboardInterrupt:
            bridge.stop()


if __name__ == "__main__":
    app()
