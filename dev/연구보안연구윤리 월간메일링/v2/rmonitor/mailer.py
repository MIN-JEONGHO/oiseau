# -*- coding: utf-8 -*-
"""SMTP 메일 발송 (Gmail / Naver / 기타).

Gmail : 2단계 인증 후 '앱 비밀번호'를 발급받아 smtp.password 에 입력
Naver : 메일 > 환경설정 > POP3/IMAP 설정에서 'SMTP 사용' 활성화 후 계정 비밀번호(또는 앱 비밀번호)
"""
from __future__ import annotations

import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Any, Dict, Iterable, List

log = logging.getLogger("rmonitor")

_TAG_RE = re.compile(r"<[^>]+>")


class MailError(RuntimeError):
    pass


def html_to_text(html: str) -> str:
    """HTML 메일을 지원하지 않는 클라이언트를 위한 대체 본문."""
    text = re.sub(r"(?is)<br\s*/?>", "\n", html)
    text = re.sub(r"(?is)</(tr|div|p|table)>", "\n", text)
    text = _TAG_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize(addrs: Iterable[str] | None) -> List[str]:
    out = []
    for a in (addrs or []):
        a = str(a).strip()
        if a and "@" in a:
            out.append(a)
    return out


def build_message(subject: str, html_body: str, sender: str, sender_name: str,
                  to: Iterable[str], cc: Iterable[str] = (),
                  bcc: Iterable[str] = ()) -> EmailMessage:
    to, cc, bcc = _normalize(to), _normalize(cc), _normalize(bcc)
    if not to:
        raise MailError("수신자가 비어 있습니다. config.json 의 recipients 를 확인하세요.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((sender_name or "", sender))
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()

    msg.set_content(html_to_text(html_body))
    msg.add_alternative(html_body, subtype="html")
    # 실제 전송 대상(To+Cc+Bcc)은 sendmail 인자로 별도 전달
    msg._all_recipients = to + cc + bcc      # type: ignore[attr-defined]
    msg._envelope_from = sender             # type: ignore[attr-defined]
    return msg


def send(msg: EmailMessage, smtp_cfg: Dict[str, Any],
         logger: logging.Logger | None = None) -> None:
    logger = logger or log
    host = smtp_cfg.get("host")
    port = int(smtp_cfg.get("port", 587))
    user = (smtp_cfg.get("user") or "").strip()
    password = smtp_cfg.get("password") or ""
    security = (smtp_cfg.get("security") or "starttls").lower()

    if not host or not user or not password:
        raise MailError("SMTP 호스트/계정/비밀번호가 설정되지 않았습니다.")

    recipients = getattr(msg, "_all_recipients", None) or [msg["To"]]
    envelope_from = getattr(msg, "_envelope_from", None) or user
    logger.info("메일 발송 시도: %s:%s (%s) → %d명", host, port, security, len(recipients))

    context = ssl.create_default_context()
    try:
        if security == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=60, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=60)
        with server:
            server.ehlo()
            if security == "starttls":
                server.starttls(context=context)
                server.ehlo()
            server.login(user, password)
            server.send_message(msg, from_addr=envelope_from, to_addrs=recipients)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(
            "SMTP 인증에 실패했습니다. Gmail 은 '앱 비밀번호', 네이버는 메일 환경설정에서 "
            f"SMTP 사용을 켰는지 확인하세요. ({exc})") from exc
    except Exception as exc:  # noqa: BLE001
        raise MailError(f"메일 발송 실패: {exc}") from exc

    logger.info("메일 발송 완료 (%s)", ", ".join(recipients))
