"""Pull from an external SFTP host, so that no port is ever opened on the site's network.

The server's host key is pinned: its fingerprint is recorded when the source is configured and
any later connection to a server showing another key is refused.
"""

from __future__ import annotations

import base64
import hashlib
import io
import stat
from collections.abc import Callable, Collection

import paramiko

from .base import MAX_FILE_SIZE, SourceError, SourceFile, looks_like_publication

TIMEOUT = 30


class SftpSource:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 22,
        directory: str = "/",
        host_key: str | None = None,
    ) -> None:
        self._host, self._port = host, port
        self._username, self._password = username, password
        self._directory = directory
        self._host_key = host_key or None

    def fingerprint(self) -> str:
        """Fingerprint of the server's host key (`SHA256:…`, as `ssh-keygen -l` shows it)."""
        return self._session(lambda transport, seen: seen)

    def check(self) -> None:
        self._session(lambda transport, seen: self._open(transport, seen))

    def poll(self, known: Collection[str]) -> list[SourceFile]:
        return self._session(
            lambda transport, seen: self._download(self._open(transport, seen), known)
        )

    def _session[T](self, action: Callable[[paramiko.Transport, str], T]) -> T:
        """Connect, read the server's key fingerprint, run `action`, always close."""
        transport = None
        try:
            transport = paramiko.Transport((self._host, self._port))
            transport.start_client(timeout=TIMEOUT)
            digest = hashlib.sha256(transport.get_remote_server_key().asbytes()).digest()
            return action(transport, "SHA256:" + base64.b64encode(digest).decode().rstrip("="))
        except paramiko.AuthenticationException:
            raise SourceError("the SFTP server refused the login") from None
        except (paramiko.SSHException, OSError, EOFError) as err:
            raise SourceError(f"cannot read the SFTP server ({type(err).__name__})") from None
        finally:
            if transport is not None:
                transport.close()

    def _open(self, transport: paramiko.Transport, seen: str) -> paramiko.SFTPClient:
        """Log in — only on a server that shows the pinned key."""
        if self._host_key and seen != self._host_key:
            raise SourceError("the SFTP server's host key changed: connection refused")
        transport.auth_password(self._username, self._password)
        client = paramiko.SFTPClient.from_transport(transport)
        if client is None:
            raise SourceError("the SFTP session could not be opened")
        client.chdir(self._directory)
        return client

    @staticmethod
    def _download(client: paramiko.SFTPClient, known: Collection[str]) -> list[SourceFile]:
        files: list[SourceFile] = []
        for entry in sorted(client.listdir_attr(), key=lambda e: e.filename):
            name, size = entry.filename, entry.st_size or 0
            if not stat.S_ISREG(entry.st_mode or 0) or not looks_like_publication(name):
                continue
            ident = f"sftp:{name}:{size}"
            if ident in known or size > MAX_FILE_SIZE:
                continue
            buffer = io.BytesIO()
            client.getfo(name, buffer)
            files.append(SourceFile(ident, name, buffer.getvalue()))
        return files
