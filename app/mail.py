import os
import smtplib
from email.message import EmailMessage

from app import i18n


def _is_dev_mode() -> bool:
    if os.environ.get("ENVIRONMENT", "").strip().lower() == "development":
        return True
    return not os.environ.get("SMTP_HOST", "").strip()


def send_mail(to: str, subject: str, body: str) -> None:
    if _is_dev_mode():
        # Kein echter Mailversand in der lokalen Entwicklung - der Link
        # landet stattdessen in der Server-Konsole, derselbe Code-Pfad
        # (Token-Erzeugung/-Prüfung, Cookie) läuft ansonsten identisch.
        print(f"\n--- E-Mail (Dev-Modus, nicht wirklich verschickt) ---\nAn: {to}\nBetreff: {subject}\n\n{body}\n---\n")
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = os.environ.get("SMTP_FROM", "")
    message["To"] = to
    message.set_content(body)

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USERNAME", "")
    password = os.environ.get("SMTP_PASSWORD", "")

    # Port 465 ist implizites SSL/TLS (Verbindung ist von Anfang an
    # verschlüsselt) - STARTTLS (für 587/25) auf dieser Verbindung anzuwenden
    # schlägt fehl, da der Server keinen Klartext-Handshake erwartet.
    if port == 465:
        with smtplib.SMTP_SSL(host, port) as smtp:
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port) as smtp:
            smtp.starttls()
            if username:
                smtp.login(username, password)
            smtp.send_message(message)


def send_login_link_email(to: str, link_url: str, lang: str = i18n.DEFAULT_LANG) -> None:
    subject = i18n.get_message("mail_login_subject", lang)
    body = i18n.get_message("mail_login_body", lang, link=link_url)
    send_mail(to, subject, body)


def send_invite_email(to: str, link_url: str, role: str, lang: str = i18n.DEFAULT_LANG) -> None:
    subject = i18n.get_message("mail_invite_subject", lang)
    body = i18n.get_message("mail_invite_body", lang, role=role, link=link_url)
    send_mail(to, subject, body)
