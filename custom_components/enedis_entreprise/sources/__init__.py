"""Where the files Enedis sent are read from. Blocking, standard library only, read-only."""

from .base import Source, SourceError, SourceFile, looks_like_publication
from .folder import FolderSource
from .ftps import FtpsSource
from .imap import ImapSource
from .sftp import SftpSource

__all__ = [
    "FolderSource",
    "FtpsSource",
    "ImapSource",
    "SftpSource",
    "Source",
    "SourceError",
    "SourceFile",
    "looks_like_publication",
]
