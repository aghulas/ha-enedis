"""Local folder fed by something else (manual drop, an FTP server elsewhere, a mail rule…)."""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path

from .base import MAX_FILE_SIZE, SourceError, SourceFile, looks_like_publication


class FolderSource:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def check(self) -> None:
        if not self._path.is_dir():
            raise SourceError("the folder does not exist or is not readable")

    def poll(self, known: Collection[str]) -> list[SourceFile]:
        self.check()
        files: list[SourceFile] = []
        try:
            for path in sorted(self._path.rglob("*")):
                if not path.is_file() or not looks_like_publication(path.name):
                    continue
                size = path.stat().st_size
                ident = f"folder:{path.relative_to(self._path).as_posix()}:{size}"
                if ident in known or size > MAX_FILE_SIZE:
                    continue
                files.append(SourceFile(ident, path.name, path.read_bytes()))
        except OSError as err:
            raise SourceError(f"cannot read the folder ({type(err).__name__})") from None
        return files
