from __future__ import annotations

import ftplib
import imaplib
from collections.abc import Callable
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest

from custom_components.enedis_entreprise.sources import (
    FolderSource,
    FtpsSource,
    ImapSource,
    SourceError,
    base,
)
from custom_components.enedis_entreprise.sources import ftps as ftps_module
from custom_components.enedis_entreprise.sources import imap as imap_module

from . import synthetic as s

PASSWORD = "not-a-real-password"


# --- folder --------------------------------------------------------------------------------------


def test_folder(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / s.R63_ARCHIVE).write_bytes(b"one")
    (tmp_path / "sub" / f"lisible{s.R64_NAME}").write_bytes(b"three")
    (tmp_path / "facture.pdf").write_bytes(b"ignored")
    source = FolderSource(tmp_path)

    files = source.poll(set())
    assert sorted((f.name, f.data) for f in files) == [
        (s.R63_ARCHIVE, b"one"),
        (f"lisible{s.R64_NAME}", b"three"),
    ]
    assert source.poll({f.ident for f in files}) == []
    # Nothing was removed or renamed.
    assert len(list(tmp_path.rglob("*"))) == 4

    # A file rewritten with another size is a new file.
    (tmp_path / s.R63_ARCHIVE).write_bytes(b"longer")
    assert [f.data for f in source.poll({f.ident for f in files})] == [b"longer"]


def test_folder_missing_and_oversized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SourceError):
        FolderSource(tmp_path / "absent").poll(set())
    (tmp_path / s.R63_ARCHIVE).write_bytes(b"12345")
    monkeypatch.setattr("custom_components.enedis_entreprise.sources.folder.MAX_FILE_SIZE", 4)
    assert FolderSource(tmp_path).poll(set()) == []


def test_folder_read_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / s.R63_ARCHIVE).write_bytes(b"x")

    def boom(self: Path) -> bytes:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_bytes", boom)
    with pytest.raises(SourceError, match="PermissionError"):
        FolderSource(tmp_path).poll(set())


def test_names() -> None:
    assert base.looks_like_publication(s.R63_ARCHIVE + ".aes")
    assert base.looks_like_publication(
        "ENEDIS_R64A_Q_INDEX_123456780_000000000_00003_20261121040346.zip"
    )
    assert not base.looks_like_publication("Enedis_facture_2026.pdf")


# --- IMAP ----------------------------------------------------------------------------------------


def mail(attachments: dict[str, bytes]) -> bytes:
    message = EmailMessage()
    message["From"] = "sender@example.invalid"
    message["Subject"] = "Publication"
    message.set_content("Bonjour")
    for name, data in attachments.items():
        message.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
    return message.as_bytes()


class FakeImap:
    """Just enough of imaplib.IMAP4_SSL, recording every command."""

    messages: dict[str, bytes] = {}
    fail_login = False
    select_status = "OK"
    search_status = "OK"

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.commands: list[tuple[Any, ...]] = []
        FakeImap.last = self

    def login(self, user: str, password: str) -> tuple[str, list[bytes]]:
        if self.fail_login:
            raise imaplib.IMAP4.error(f"LOGIN failed for {user} {password}")
        return "OK", [b""]

    def select(self, mailbox: str, readonly: bool = False) -> tuple[str, list[bytes]]:
        self.commands.append(("SELECT", mailbox, readonly))
        return self.select_status, [b"2"]

    def response(self, code: str) -> tuple[str, list[bytes | None]]:
        return "OK", [b"77"]

    def uid(self, command: str, *args: str) -> tuple[str, list[Any]]:
        self.commands.append((command, *args))
        if command == "SEARCH":
            return self.search_status, [" ".join(self.messages).encode()]
        raw = self.messages.get(args[0])
        if raw is None:
            return "NO", [None]
        return "OK", [(b"1 (UID 1 BODY[] {1}", raw), b")"]

    def logout(self) -> None:
        self.commands.append(("LOGOUT",))


@pytest.fixture
def imap(monkeypatch: pytest.MonkeyPatch) -> type[FakeImap]:
    class Fresh(FakeImap):
        messages = {}

    monkeypatch.setattr(imap_module.imaplib, "IMAP4_SSL", Fresh)
    return Fresh


def test_imap_picks_enedis_attachments_and_stays_read_only(imap: type[FakeImap]) -> None:
    imap.messages = {
        "11": mail({s.R63_ARCHIVE: b"zip-bytes", "logo.png": b"png"}),
        "12": mail({}),
        "13": mail({"rapport.pdf": b"pdf"}),
        "14": b"",
    }
    del imap.messages["14"]
    source = ImapSource("mail.example.invalid", "user", PASSWORD, sender='a"b@example.invalid')

    files = source.poll(set())
    assert [(f.ident, f.name, f.data) for f in files] == [
        (f"imap:77:11:{s.R63_ARCHIVE}", s.R63_ARCHIVE, b"zip-bytes")
    ]
    commands = FakeImap.last.commands
    assert commands[0] == ("SELECT", '"INBOX"', True)
    assert commands[1][:2] == ("SEARCH", "SINCE")
    assert commands[1][3:] == ("FROM", '"a\\"b@example.invalid"')
    assert {c[0] for c in commands} == {"SELECT", "SEARCH", "FETCH", "LOGOUT"}
    assert all(c[2] == "(BODY.PEEK[])" for c in commands if c[0] == "FETCH")

    # Next poll: the processed message and the ones without publication are not fetched again.
    assert source.poll({files[0].ident}) == []
    assert [c for c in FakeImap.last.commands if c[0] == "FETCH"] == []


def test_imap_errors_never_leak_credentials(
    imap: type[FakeImap], monkeypatch: pytest.MonkeyPatch
) -> None:
    source = ImapSource("mail.example.invalid", "user", PASSWORD)
    imap.fail_login = True
    with pytest.raises(SourceError) as err:
        source.poll(set())
    assert PASSWORD not in str(err.value) and "user" not in str(err.value)

    imap.fail_login = False
    imap.select_status = "NO"
    with pytest.raises(SourceError, match="folder"):
        source.poll(set())
    imap.select_status = "OK"
    imap.search_status = "NO"
    with pytest.raises(SourceError, match="search"):
        source.poll(set())

    def lost(self: FakeImap, command: str, *args: str) -> Any:
        raise ConnectionResetError

    monkeypatch.setattr(imap, "uid", lost)
    with pytest.raises(SourceError, match="ConnectionResetError"):
        source.poll(set())

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise TimeoutError

    monkeypatch.setattr(imap_module.imaplib, "IMAP4_SSL", refuse)
    with pytest.raises(SourceError, match="connect"):
        source.poll(set())


def test_imap_failed_fetch_is_retried_later(imap: type[FakeImap]) -> None:
    imap.messages = {"5": mail({s.R63_ARCHIVE: b"data"})}
    source = ImapSource("mail.example.invalid", "user", PASSWORD)
    original: Callable[..., Any] = imap.uid

    def flaky(self: FakeImap, command: str, *args: str) -> Any:
        return ("NO", [None]) if command == "FETCH" else original(self, command, *args)

    imap.uid = flaky  # type: ignore[method-assign]
    assert source.poll(set()) == []
    imap.uid = original  # type: ignore[method-assign]
    assert len(source.poll(set())) == 1


# --- FTPS ----------------------------------------------------------------------------------------


class FakeFtp:
    files: dict[str, bytes] = {}
    error: Exception | None = None
    quit_error: Exception | None = None

    def __init__(self, context: Any = None, timeout: float | None = None) -> None:
        self.commands: list[str] = []
        FakeFtp.last = self

    def connect(self, host: str, port: int) -> None:
        self.commands.append("connect")
        if self.error:
            raise self.error

    def login(self, user: str, password: str) -> None:
        self.commands.append("login")

    def prot_p(self) -> None:
        self.commands.append("prot_p")

    def cwd(self, directory: str) -> None:
        self.commands.append(f"cwd {directory}")

    def nlst(self) -> list[str]:
        return list(self.files)

    def size(self, name: str) -> int:
        return len(self.files[name])

    def retrbinary(self, command: str, callback: Callable[[bytes], Any]) -> None:
        self.commands.append(command)
        callback(self.files[command.removeprefix("RETR ")])

    def quit(self) -> None:
        self.commands.append("quit")
        if self.quit_error:
            raise self.quit_error

    def close(self) -> None:
        self.commands.append("close")


@pytest.fixture
def ftp(monkeypatch: pytest.MonkeyPatch) -> type[FakeFtp]:
    class Fresh(FakeFtp):
        files = {}

    monkeypatch.setattr(ftps_module.ftplib, "FTP_TLS", Fresh)
    return Fresh


def test_ftps(ftp: type[FakeFtp], monkeypatch: pytest.MonkeyPatch) -> None:
    ftp.files = {f"in/{s.R63_ARCHIVE}": b"abc", "readme.txt": b"no", s.R64_NAME: b"wxyz"}
    source = FtpsSource("ftp.example.invalid", "user", PASSWORD, directory="/enedis")

    files = source.poll(set())
    assert sorted((f.ident, f.data) for f in files) == [
        (f"ftps:{s.R63_ARCHIVE}:3", b"abc"),
        (f"ftps:{s.R64_NAME}:4", b"wxyz"),
    ]
    commands = FakeFtp.last.commands
    # Encrypted data channel before anything is listed; only downloads, never DELE or RNFR.
    assert commands[:4] == ["connect", "login", "prot_p", "cwd /enedis"]
    assert all(c.startswith(("RETR ", "quit")) for c in commands[4:])

    assert source.poll({f.ident for f in files}) == []
    monkeypatch.setattr(ftps_module, "MAX_FILE_SIZE", 2)
    assert source.poll(set()) == []


def test_ftps_errors(ftp: type[FakeFtp]) -> None:
    source = FtpsSource("ftp.example.invalid", "user", PASSWORD)
    ftp.error = ftplib.error_perm(f"530 Login incorrect user {PASSWORD}")
    with pytest.raises(SourceError) as err:
        source.poll(set())
    assert PASSWORD not in str(err.value)

    ftp.error = TimeoutError()
    ftp.quit_error = EOFError()
    with pytest.raises(SourceError, match="TimeoutError"):
        source.poll(set())
    assert FakeFtp.last.commands[-1] == "close"


# --- connection checks (config flow) --------------------------------------------------------------


def test_checks_download_nothing(tmp_path: Path, imap: type[FakeImap], ftp: type[FakeFtp]) -> None:
    FolderSource(tmp_path).check()
    with pytest.raises(SourceError):
        FolderSource(tmp_path / "absent").check()

    imap.messages = {"1": mail({s.R63_ARCHIVE: b"x"})}
    ImapSource("mail.example.invalid", "user", PASSWORD).check()
    assert [c[0] for c in FakeImap.last.commands] == ["SELECT", "LOGOUT"]
    imap.fail_login = True
    with pytest.raises(SourceError):
        ImapSource("mail.example.invalid", "user", PASSWORD).check()

    ftp.files = {s.R63_ARCHIVE: b"abc"}
    FtpsSource("ftp.example.invalid", "user", PASSWORD).check()
    assert FakeFtp.last.commands == ["connect", "login", "prot_p", "cwd /", "quit"]
    ftp.error = TimeoutError()
    with pytest.raises(SourceError):
        FtpsSource("ftp.example.invalid", "user", PASSWORD).check()


# --- SFTP ----------------------------------------------------------------------------------------


class FakeKey:
    def asbytes(self) -> bytes:
        return b"server-host-key"


# What `ssh-keygen -l` would print for FakeKey.
FINGERPRINT = "SHA256:" + __import__("base64").b64encode(
    __import__("hashlib").sha256(b"server-host-key").digest()
).decode().rstrip("=")


class FakeAttr:
    def __init__(self, filename: str, size: int, mode: int = 0o100644) -> None:
        self.filename, self.st_size, self.st_mode = filename, size, mode


class FakeSftpClient:
    def __init__(self, files: dict[str, bytes], log: list[str]) -> None:
        self.files, self.log = files, log

    def chdir(self, directory: str) -> None:
        self.log.append(f"chdir {directory}")

    def listdir_attr(self) -> list[FakeAttr]:
        return [FakeAttr(name, len(data)) for name, data in self.files.items()] + [
            FakeAttr(s.R64_NAME + ".d", 0, 0o040755)
        ]

    def getfo(self, name: str, buffer: Any) -> None:
        self.log.append(f"get {name}")
        buffer.write(self.files[name])


class FakeTransport:
    files: dict[str, bytes] = {}
    error: Exception | None = None
    no_session = False
    log: list[str] = []

    def __init__(self, address: tuple[str, int]) -> None:
        self.log.append("connect")

    def start_client(self, timeout: float | None = None) -> None:
        if self.error:
            raise self.error

    def get_remote_server_key(self) -> FakeKey:
        return FakeKey()

    def auth_password(self, username: str, password: str) -> None:
        self.log.append("auth")

    def close(self) -> None:
        self.log.append("close")


@pytest.fixture
def sftp(monkeypatch: pytest.MonkeyPatch) -> type[FakeTransport]:
    from custom_components.enedis_entreprise.sources import sftp as sftp_module

    class Fresh(FakeTransport):
        files = {}
        log = []

    def from_transport(transport: Fresh) -> FakeSftpClient | None:
        return None if transport.no_session else FakeSftpClient(transport.files, transport.log)

    monkeypatch.setattr(sftp_module.paramiko, "Transport", Fresh)
    monkeypatch.setattr(sftp_module.paramiko.SFTPClient, "from_transport", from_transport)
    return Fresh


def test_sftp(sftp: type[FakeTransport]) -> None:
    from custom_components.enedis_entreprise.sources import SftpSource

    sftp.files = {s.R63_ARCHIVE: b"abc", "readme.txt": b"no", s.R64_NAME: b"wxyz"}
    source = SftpSource("sftp.example.invalid", "user", PASSWORD, directory="/in")
    assert source.fingerprint() == FINGERPRINT
    # Reading the fingerprint never sends the password.
    assert sftp.log == ["connect", "close"]

    pinned = SftpSource(
        "sftp.example.invalid", "user", PASSWORD, directory="/in", host_key=FINGERPRINT
    )
    pinned.check()
    files = pinned.poll(set())
    assert sorted((f.ident, f.data) for f in files) == [
        (f"sftp:{s.R63_ARCHIVE}:3", b"abc"),
        (f"sftp:{s.R64_NAME}:4", b"wxyz"),
    ]
    assert pinned.poll({f.ident for f in files}) == []
    # Only downloads: no remove, rename or write.
    assert {entry.split()[0] for entry in sftp.log} == {"connect", "auth", "chdir", "get", "close"}


def test_sftp_refuses_another_host_key_before_sending_the_password(
    sftp: type[FakeTransport],
) -> None:
    from custom_components.enedis_entreprise.sources import SftpSource

    source = SftpSource("sftp.example.invalid", "user", PASSWORD, host_key="SHA256:other")
    with pytest.raises(SourceError, match="host key changed"):
        source.poll(set())
    assert sftp.log == ["connect", "close"]


def test_sftp_errors(sftp: type[FakeTransport]) -> None:
    import paramiko

    from custom_components.enedis_entreprise.sources import SftpSource

    source = SftpSource("sftp.example.invalid", "user", PASSWORD)
    sftp.no_session = True
    with pytest.raises(SourceError, match="session"):
        source.check()
    sftp.error = paramiko.AuthenticationException(f"bad {PASSWORD}")
    with pytest.raises(SourceError) as err:
        source.check()
    assert PASSWORD not in str(err.value)
    sftp.error = TimeoutError()
    with pytest.raises(SourceError, match="TimeoutError"):
        source.check()
    assert sftp.log[-1] == "close"
