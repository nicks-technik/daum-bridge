from daum_bridge import cli

import json

from typer.testing import CliRunner


def test_app_exists():
    assert cli.app is not None


def test_commands_registered():
    # Check that commands are registered
    commands = [cmd.name for cmd in cli.app.registered_commands]
    assert "run" in commands or len(commands) > 0


def test_export_tcx_command(tmp_path):
    ride_file = tmp_path / "ride.json"
    ride_file.write_text(json.dumps({
        "id": "test-ride",
        "start": 1761732000.0,
        "duration": 10.0,
        "distance": 0.1,
        "avg_power": 150.0,
        "samples": [
            {"t": 0, "power": 100, "cadence": 80, "speed": 30, "distance": 0.0},
            {"t": 10, "power": 200, "cadence": 85, "speed": 32, "distance": 0.1},
        ],
    }))
    output = tmp_path / "out.tcx"

    result = CliRunner().invoke(
        cli.app, ["export-tcx", "--ride", str(ride_file), "--output", str(output)]
    )
    assert result.exit_code == 0, result.output
    text = output.read_text(encoding="utf-8")
    assert "TrainingCenterDatabase" in text
    assert "garmin:Watts" in text


def test_export_tcx_missing_ride(tmp_path):
    result = CliRunner().invoke(
        cli.app, ["export-tcx", "--ride", str(tmp_path / "missing.json")]
    )
    assert result.exit_code == 1
