"""Common contract of the file sources.

A source never deletes, moves or flags anything (CLAUDE.md rule 1): what was already handled is
remembered on our side, and given back to `poll()` as `known`.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Protocol

from ..api.r6x import parse_filename

# A daily archive is a few hundred kB; anything far beyond is not an Enedis publication.
MAX_FILE_SIZE = 50 * 1024 * 1024


class SourceError(Exception):
    """The source cannot be read right now (network, credentials, missing folder…)."""


@dataclass(frozen=True, slots=True)
class SourceFile:
    """One file as received. `ident` is stable across polls and unique within the source."""

    ident: str
    name: str
    data: bytes


class Source(Protocol):
    def poll(self, known: Collection[str]) -> list[SourceFile]:
        """Files whose `ident` is not in `known`. Blocking: call it in an executor."""
        ...


def looks_like_publication(name: str) -> bool:
    """`Enedis_R6xx_…` whatever the prefix (`lisible…`) or the extra extension (`.zip.aes`)."""
    return parse_filename(name) is not None
