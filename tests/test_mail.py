from unittest.mock import MagicMock, patch

from app import mail


def test_send_mail_dev_mode_prints_instead_of_sending(monkeypatch, capsys):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("SMTP_HOST", raising=False)

    with patch("app.mail.smtplib.SMTP") as smtp_mock:
        mail.send_mail("to@test.local", "Betreff", "Inhalt der Mail")

    smtp_mock.assert_not_called()
    captured = capsys.readouterr()
    assert "to@test.local" in captured.out
    assert "Betreff" in captured.out
    assert "Inhalt der Mail" in captured.out


def test_send_mail_dev_mode_when_smtp_host_unset(monkeypatch, capsys):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)

    with patch("app.mail.smtplib.SMTP") as smtp_mock:
        mail.send_mail("to@test.local", "Betreff", "Inhalt")

    smtp_mock.assert_not_called()
    assert "to@test.local" in capsys.readouterr().out


def test_send_mail_uses_smtp_when_configured(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.org")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")
    monkeypatch.setenv("SMTP_FROM", "noreply@example.org")

    smtp_instance = MagicMock()
    smtp_instance.__enter__.return_value = smtp_instance
    with patch("app.mail.smtplib.SMTP", return_value=smtp_instance) as smtp_mock:
        mail.send_mail("to@test.local", "Betreff", "Inhalt")

    smtp_mock.assert_called_once_with("smtp.example.org", 587)
    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with("user", "pass")
    smtp_instance.send_message.assert_called_once()
    sent_message = smtp_instance.send_message.call_args[0][0]
    assert sent_message["To"] == "to@test.local"
    assert sent_message["Subject"] == "Betreff"
    assert sent_message["From"] == "noreply@example.org"
    assert sent_message.get_content().strip() == "Inhalt"


def test_send_mail_uses_ssl_for_port_465(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.org")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USERNAME", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")
    monkeypatch.setenv("SMTP_FROM", "noreply@example.org")

    smtp_instance = MagicMock()
    smtp_instance.__enter__.return_value = smtp_instance
    with (
        patch("app.mail.smtplib.SMTP_SSL", return_value=smtp_instance) as smtp_ssl_mock,
        patch("app.mail.smtplib.SMTP") as smtp_mock,
    ):
        mail.send_mail("to@test.local", "Betreff", "Inhalt")

    smtp_ssl_mock.assert_called_once_with("smtp.example.org", 465)
    smtp_mock.assert_not_called()
    smtp_instance.starttls.assert_not_called()
    smtp_instance.login.assert_called_once_with("user", "pass")
    smtp_instance.send_message.assert_called_once()


def test_send_login_link_email_builds_subject_and_body(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    with patch("app.mail.send_mail") as send_mail_mock:
        mail.send_login_link_email("to@test.local", "https://example.org/verify?token=abc", "de")

    send_mail_mock.assert_called_once()
    to, subject, body = send_mail_mock.call_args[0]
    assert to == "to@test.local"
    assert "Login-Link" in subject
    assert "https://example.org/verify?token=abc" in body


def test_send_invite_email_builds_subject_and_body(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    with patch("app.mail.send_mail") as send_mail_mock:
        mail.send_invite_email(
            "to@test.local", "https://example.org/verify?token=abc", "quellen_pfleger", "de"
        )

    send_mail_mock.assert_called_once()
    to, subject, body = send_mail_mock.call_args[0]
    assert to == "to@test.local"
    assert "Einladung" in subject
    assert "quellen_pfleger" in body
    assert "https://example.org/verify?token=abc" in body
