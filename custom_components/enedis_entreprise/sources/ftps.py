"""Pull from an external FTPS host (e.g. a web-hosting FTP account), so that no port is ever
opened on the site's network. Explicit TLS only: plain FTP is refused."""

from __future__ import annotations

import ftplib
import io
import ssl
from collections.abc import Collection

from .base import MAX_FILE_SIZE, SourceError, SourceFile, looks_like_publication

TIMEOUT = 30


class FtpsSource:
    def __init__(
        self, host: str, username: str, password: str, *, port: int = 21, directory: str = "/"
    ) -> None:
        self._host, self._port = host, port
        self._username, self._password = username, password
        self._directory = directory

    def poll(self, known: Collection[str]) -> list[SourceFile]:
        client = ftplib.FTP_TLS(context=ssl.create_default_context(), timeout=TIMEOUT)
        try:
            client.connect(self._host, self._port)
            client.login(self._username, self._password)
            client.prot_p()
            client.cwd(self._directory)
            files: list[SourceFile] = []
            for name in sorted(client.nlst()):
                base = name.rsplit("/", 1)[-1]
                if not looks_like_publication(base):
                    continue
                size = client.size(name) or 0
                ident = f"ftps:{base}:{size}"
                if ident in known or size > MAX_FILE_SIZE:
                    continue
                buffer = io.BytesIO()
                client.retrbinary(f"RETR {name}", buffer.write)
                files.append(SourceFile(ident, base, buffer.getvalue()))
            return files
        except ftplib.error_perm:
            # The server's text may repeat the login: never forwarded.
            raise SourceError("the FTPS server refused the request (login or folder?)") from None
        except (OSError, EOFError, ftplib.Error) as err:
            raise SourceError(f"cannot read the FTPS server ({type(err).__name__})") from None
        finally:
            try:
                client.quit()
            except (OSError, EOFError, ftplib.Error):
                client.close()
