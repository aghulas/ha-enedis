"""Decryption of files Enedis sends on a business customer's digital channel (e-mail / FTP).

Method "AES256 IV dyn" (note Enedis-MOP-CF_080E, formerly NOI-CF_107E): AES-256 in CBC mode,
PKCS5/PKCS7 padding, a random 16-byte IV stored at the start of the file, one 64-hex-character key
per contact channel. See docs/api.md.

Never log the key or the decrypted content: error messages here contain neither.
"""

from __future__ import annotations

import io
import os
import zipfile
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BLOCK = 16
KEY_HEX_LENGTH = 64
ZIP_MAGIC = b"PK\x03\x04"
CSV_START = b"Identifiant PRM"
BOM = b"\xef\xbb\xbf"
DATA_EXTENSIONS = (".json", ".csv")
# Guards against a hostile or corrupt archive (a daily R63 for one PRM is a few hundred kB).
MAX_MEMBERS = 200
MAX_UNCOMPRESSED = 200 * 1024 * 1024


class DecryptError(Exception):
    """The file cannot be turned into readable R6X content."""


class InvalidKeyError(DecryptError):
    """The key is not 64 hexadecimal characters."""


class WrongKeyError(DecryptError):
    """Decryption gave garbage: wrong key (or the file is not an Enedis encrypted file)."""


@dataclass(frozen=True, slots=True)
class PublishedFile:
    """One JSON or CSV file of a publication, in clear."""

    name: str
    content: bytes


def parse_key(text: str) -> bytes:
    """64 hexadecimal characters, as copied from the business account → 32 bytes."""
    cleaned = "".join(text.split())
    if len(cleaned) != KEY_HEX_LENGTH:
        raise InvalidKeyError(f"the key must be {KEY_HEX_LENGTH} hexadecimal characters")
    try:
        return bytes.fromhex(cleaned)
    except ValueError:
        raise InvalidKeyError("the key must only contain hexadecimal characters") from None


def looks_clear(data: bytes) -> bool:
    """True if `data` is already readable: a zip, a JSON object or an R6X CSV."""
    if data.startswith(ZIP_MAGIC):
        return True
    text = data.removeprefix(BOM).lstrip()
    return text.startswith((b"{", CSV_START))


def _unpad(data: bytes) -> bytes | None:
    if not data:
        return None
    n = data[-1]
    if not 1 <= n <= BLOCK or data[-n:] != bytes([n]) * n:
        return None
    return data[:-n]


def decrypt(data: bytes, key: bytes) -> bytes:
    """IV = first 16 bytes, then AES-256-CBC. Raises WrongKeyError if the result is garbage."""
    if len(key) != 32:
        raise InvalidKeyError("the key must be 32 bytes")
    if len(data) < 2 * BLOCK or len(data) % BLOCK:
        raise DecryptError("not an Enedis encrypted file (length is not a multiple of 16 bytes)")
    decryptor = Cipher(algorithms.AES(key), modes.CBC(data[:BLOCK])).decryptor()
    raw = decryptor.update(data[BLOCK:]) + decryptor.finalize()
    clear = _unpad(raw)
    if clear is None:
        # Footnote of the Enedis note: files may come without padding.
        clear = raw
    if not looks_clear(clear):
        raise WrongKeyError("decryption did not produce a zip, JSON or CSV file (wrong key?)")
    return clear


def encrypt(data: bytes, key: bytes, iv: bytes | None = None) -> bytes:
    """Same method as Enedis — used to build synthetic fixtures and by tests."""
    if len(key) != 32:
        raise InvalidKeyError("the key must be 32 bytes")
    iv = iv or os.urandom(BLOCK)
    n = BLOCK - len(data) % BLOCK
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return iv + encryptor.update(data + bytes([n]) * n) + encryptor.finalize()


def _unzip(data: bytes) -> list[PublishedFile]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = [
                m
                for m in archive.infolist()
                if not m.is_dir() and m.filename.lower().endswith(DATA_EXTENSIONS)
            ]
            if len(members) > MAX_MEMBERS:
                raise DecryptError("archive refused: too many files")
            if sum(m.file_size for m in members) > MAX_UNCOMPRESSED:
                raise DecryptError("archive refused: too large once uncompressed")
            return [PublishedFile(os.path.basename(m.filename), archive.read(m)) for m in members]
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as err:
        raise DecryptError(f"unreadable zip archive ({type(err).__name__})") from None


def open_publication(
    data: bytes, key: bytes | None = None, name: str | None = None
) -> list[PublishedFile]:
    """Encrypted file, clear zip or bare JSON/CSV → the JSON/CSV files it contains.

    `name` is the file name as received; it names the result when `data` is not an archive.
    """
    if not looks_clear(data):
        if key is None:
            raise DecryptError("the file is encrypted and no key was given")
        data = decrypt(data, key)
    if data.startswith(ZIP_MAGIC):
        return _unzip(data)
    extension = ".json" if data.removeprefix(BOM).lstrip().startswith(b"{") else ".csv"
    base = os.path.basename(name or "publication")
    for suffix in (".aes", ".enc", ".zip", ".json", ".csv"):
        base = base.removesuffix(suffix)
    return [PublishedFile(base + extension, data)]
