"""Mailbox that receives the Enedis e-mails. Opened read-only: nothing is deleted, moved or
marked as read."""

from __future__ import annotations

import contextlib
import email
import email.policy
import imaplib
from collections.abc import Callable, Collection
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from .base import MAX_FILE_SIZE, SourceError, SourceFile, looks_like_publication

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
TIMEOUT = 30


class ImapSource:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 993,
        mailbox: str = "INBOX",
        sender: str | None = None,
        lookback_days: int = 10,
    ) -> None:
        self._host, self._port = host, port
        self._username, self._password = username, password
        self._mailbox = mailbox
        self._sender = sender
        self._lookback = timedelta(days=lookback_days)
        # Messages already looked at that carry no publication: not downloaded again.
        self._without_publication: set[str] = set()

    def poll(self, known: Collection[str]) -> list[SourceFile]:
        return self._session(lambda client: self._poll(client, known))

    def check(self) -> None:
        self._session(self._open)

    def _session[T](self, action: Callable[[imaplib.IMAP4], T]) -> T:
        try:
            client = imaplib.IMAP4_SSL(self._host, self._port, timeout=TIMEOUT)
        except (OSError, imaplib.IMAP4.error) as err:
            raise SourceError(f"cannot connect to the mail server ({type(err).__name__})") from None
        try:
            return action(client)
        except imaplib.IMAP4.error:
            # The server's text may repeat the login: never forwarded.
            raise SourceError("the mail server refused the request (login or mailbox?)") from None
        except OSError as err:
            raise SourceError(f"mail server connection lost ({type(err).__name__})") from None
        finally:
            with contextlib.suppress(OSError, imaplib.IMAP4.error):
                client.logout()

    def _open(self, client: imaplib.IMAP4) -> None:
        client.login(self._username, self._password)
        status, _ = client.select(self._quoted(self._mailbox), readonly=True)
        if status != "OK":
            raise SourceError("the mailbox folder cannot be opened")

    def _poll(self, client: imaplib.IMAP4, known: Collection[str]) -> list[SourceFile]:
        self._open(client)
        validity = self._uidvalidity(client)
        since = datetime.now(UTC) - self._lookback
        criteria = ["SINCE", f"{since.day:02d}-{_MONTHS[since.month - 1]}-{since.year}"]
        if self._sender:
            criteria += ["FROM", self._quoted(self._sender)]
        status, data = client.uid("SEARCH", *criteria)
        if status != "OK":
            raise SourceError("the mailbox search failed")
        files: list[SourceFile] = []
        for uid in (data[0] or b"").decode().split():
            prefix = f"imap:{validity}:{uid}:"
            if prefix in self._without_publication or any(k.startswith(prefix) for k in known):
                continue
            # BODY.PEEK does not set the \Seen flag.
            status, parts = client.uid("FETCH", uid, "(BODY.PEEK[])")
            raw = next((p[1] for p in parts or [] if isinstance(p, tuple)), None)
            if status != "OK" or raw is None:
                continue
            found = self._attachments(raw, prefix)
            if found:
                files.extend(found)
            else:
                self._without_publication.add(prefix)
        return files

    @staticmethod
    def _attachments(raw: bytes, prefix: str) -> list[SourceFile]:
        message = email.message_from_bytes(raw, policy=email.policy.default)
        assert isinstance(message, EmailMessage)
        files = []
        for part in message.iter_attachments():
            name = part.get_filename()
            if not name or not looks_like_publication(name):
                continue
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes) and len(payload) <= MAX_FILE_SIZE:
                files.append(SourceFile(prefix + name, name, payload))
        return files

    @staticmethod
    def _uidvalidity(client: imaplib.IMAP4) -> str:
        status, data = client.response("UIDVALIDITY")
        value = data[0] if status == "OK" and data else None
        return value.decode() if isinstance(value, bytes) else "0"

    @staticmethod
    def _quoted(text: str) -> str:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
