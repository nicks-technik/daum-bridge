from daum_bridge.config import EmailConfig
from daum_bridge.integrations import emailer

RIDE = {
    "id": "2026-10-29T18-00-00",
    "start": 1761732000.0,
    "duration": 3900.0,
    "distance": 20.1,
    "avg_power": 210.0,
    "max_power": 410.0,
    "work_kj": 140.0,
    "samples": [
        {"t": 0, "power": 150, "cadence": 80, "speed": 25, "distance": 0},
        {"t": 60, "power": 220, "cadence": 90, "speed": 32, "distance": 0.5},
    ],
}


def _configured(**overrides) -> EmailConfig:
    cfg = EmailConfig(
        host="smtp.example.com",
        port=587,
        username="user@example.com",
        password="secret",
        from_addr="user@example.com",
        to_addr="me@example.com",
        use_tls=True,
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


class _FakeSMTP:
    def __init__(self, host, port, timeout=None, context=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.calls = []
        self.message = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append("close")

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, username, password):
        self.calls.append(("login", username, password))

    def send_message(self, message):
        self.message = message
        self.calls.append("send")


def test_email_config_not_configured():
    cfg = EmailConfig()
    assert cfg.is_configured() is False
    assert cfg.auto_send is False
    assert cfg.port == 587

    result = emailer.send_ride_email(RIDE, cfg)
    assert result["ok"] is False
    assert "not configured" in result["error"]


def test_build_ride_message_attaches_tcx():
    msg = emailer.build_ride_message(RIDE, "<TrainingCenterDatabase/>", _configured())

    assert msg["To"] == "me@example.com"
    assert msg["From"] == "user@example.com"
    assert "Daum training:" in msg["Subject"]
    assert "20.1 km" in msg["Subject"]

    attachments = list(msg.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == f"{RIDE['id']}.tcx"
    assert attachments[0].get_content_type() == "application/vnd.garmin.tcx+xml"
    assert b"<TrainingCenterDatabase/>" in attachments[0].get_payload(decode=True)


def test_build_ride_message_multiple_recipients():
    msg = emailer.build_ride_message(
        RIDE, "<xml/>", _configured(to_addr="a@example.com, b@example.com")
    )
    assert msg["To"] == "a@example.com, b@example.com"


def test_send_ride_email_starttls(monkeypatch):
    sent = {}

    class FakeSMTP(_FakeSMTP):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            sent["client"] = self

    monkeypatch.setattr(emailer.smtplib, "SMTP", FakeSMTP)

    result = emailer.send_ride_email(RIDE, _configured())

    assert result["ok"] is True, result
    assert result["to"] == "me@example.com"
    client = sent["client"]
    assert client.host == "smtp.example.com"
    assert client.port == 587
    assert "starttls" in client.calls
    assert ("login", "user@example.com", "secret") in client.calls
    assert isinstance(client.message, emailer.EmailMessage)
    assert client.message.get_filename() is None  # body message, not the attachment


def test_send_ride_email_ssl_without_starttls(monkeypatch):
    sent = {}

    class FakeSMTPSSL(_FakeSMTP):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            sent["client"] = self

    monkeypatch.setattr(emailer.smtplib, "SMTP_SSL", FakeSMTPSSL)

    result = emailer.send_ride_email(
        RIDE, _configured(port=465, use_tls=False, use_ssl=True)
    )

    assert result["ok"] is True, result
    assert sent["client"].port == 465
    assert "starttls" not in sent["client"].calls


def test_send_ride_email_smtp_error(monkeypatch):
    class BrokenSMTP(_FakeSMTP):
        def send_message(self, message):
            raise OSError("connection refused")

    monkeypatch.setattr(emailer.smtplib, "SMTP", BrokenSMTP)

    result = emailer.send_ride_email(RIDE, _configured())

    assert result["ok"] is False
    assert "connection refused" in result["error"]


def test_send_ride_email_override_recipient(monkeypatch):
    sent = {}

    class FakeSMTP(_FakeSMTP):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            sent["client"] = self

    monkeypatch.setattr(emailer.smtplib, "SMTP", FakeSMTP)

    result = emailer.send_ride_email(RIDE, _configured(), to="other@example.com")

    assert result["ok"] is True
    assert sent["client"].message["To"] == "other@example.com"
