from daum_bridge import cli


def test_app_exists():
    assert cli.app is not None


def test_commands_registered():
    # Check that commands are registered
    commands = [cmd.name for cmd in cli.app.registered_commands]
    assert "run" in commands or len(commands) > 0
