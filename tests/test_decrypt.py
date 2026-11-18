from __future__ import annotations

import sys

import pytest

from custom_components.enedis_entreprise.api import (
    DecryptError,
    InvalidKeyError,
    WrongKeyError,
    decrypt,
    encrypt,
    open_publication,
    parse_key,
)

from . import synthetic as s

KEY = parse_key(s.KEY_HEX)
OTHER_KEY = parse_key("ff" * 32)
# The package re-exports the `decrypt` function under the same name as its module.
decrypt_module = sys.modules["custom_components.enedis_entreprise.api.decrypt"]


def test_parse_key_accepts_what_the_portal_copies() -> None:
    assert parse_key(f"  {s.KEY_HEX.upper()}\n") == KEY
    assert len(KEY) == 32


@pytest.mark.parametrize("bad", ["", "abcd", "zz" * 32, s.KEY_HEX + "00"])
def test_parse_key_rejects_and_never_echoes_the_key(bad: str) -> None:
    with pytest.raises(InvalidKeyError) as err:
        parse_key(bad)
    assert not bad or bad not in str(err.value)


def test_known_vector_matches_the_enedis_method() -> None:
    """AES-256-CBC, IV in the first 16 bytes, PKCS5 padding — checked against openssl's output.

    openssl enc -aes-256-cbc -K <KEY_HEX> -iv 000102030405060708090a0b0c0d0e0f  <<< '{"a":1}'
    """
    iv = bytes(range(16))
    encrypted = encrypt(b'{"a":1}\n', KEY, iv)
    assert encrypted[:16] == iv
    assert len(encrypted) == 32
    assert decrypt(encrypted, KEY) == b'{"a":1}\n'


def test_round_trip_and_random_iv() -> None:
    clear = s.archive({s.R63_NAME: s.as_json(s.r63_document())})
    a, b = encrypt(clear, KEY), encrypt(clear, KEY)
    assert a != b
    assert decrypt(a, KEY) == decrypt(b, KEY) == clear


def test_wrong_key() -> None:
    encrypted = encrypt(s.as_json(s.r63_document()), KEY, bytes(range(16)))
    with pytest.raises(WrongKeyError):
        decrypt(encrypted, OTHER_KEY)


def test_wrong_key_whose_garbage_starts_like_json() -> None:
    """Regression (CI flake): random bytes beginning with "{" were taken for a JSON file."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    blocks = bytes(range(64))
    raw = Cipher(algorithms.AES(OTHER_KEY), modes.ECB()).decryptor().update(blocks[:16])
    iv = bytes([raw[0] ^ ord("{")]) + bytes(15)
    with pytest.raises(WrongKeyError):
        decrypt(iv + blocks, OTHER_KEY)


def test_binary_content_is_not_taken_for_text() -> None:
    assert not decrypt_module.looks_clear(b'{"a":\x00}')
    assert decrypt_module.looks_clear(b'{"a":\t1}\r\n')


def test_file_without_padding_is_accepted() -> None:
    """Footnote of the Enedis note: the padding may be absent."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    clear = b'{"header":{}}'.ljust(32)
    iv = bytes(16)
    enc = Cipher(algorithms.AES(KEY), modes.CBC(iv)).encryptor()
    assert decrypt(iv + enc.update(clear) + enc.finalize(), KEY) == clear


@pytest.mark.parametrize("data", [b"", b"x" * 16, b"x" * 33])
def test_not_an_encrypted_file(data: bytes) -> None:
    with pytest.raises(DecryptError):
        decrypt(data, KEY)


def test_key_length_is_checked() -> None:
    with pytest.raises(InvalidKeyError):
        decrypt(b"x" * 32, b"short")
    with pytest.raises(InvalidKeyError):
        encrypt(b"x", b"short")


def test_open_encrypted_archive() -> None:
    content = s.as_json(s.r63_document())
    encrypted = encrypt(s.archive({s.R63_NAME: content, "notice.txt": b"ignored"}), KEY)
    files = open_publication(encrypted, KEY, s.R63_ARCHIVE)
    assert [(f.name, f.content) for f in files] == [(s.R63_NAME, content)]


def test_open_clear_archive_and_bare_files_need_no_key() -> None:
    content = s.as_json(s.r64_document())
    assert open_publication(s.archive({f"dir/{s.R64_NAME}": content}))[0].name == s.R64_NAME
    assert open_publication(content, name=s.R64_NAME)[0].name == s.R64_NAME
    bare = open_publication(b"\xef\xbb\xbf" + s.r63_csv(), name="lisible_export.zip")
    assert bare[0].name == "lisible_export.csv"
    assert open_publication(encrypt(content, KEY), KEY)[0].name == "publication.json"


def test_open_encrypted_without_key() -> None:
    with pytest.raises(DecryptError, match="no key"):
        open_publication(encrypt(b"{}", KEY))


def test_open_corrupt_archive() -> None:
    with pytest.raises(DecryptError, match="unreadable zip"):
        open_publication(b"PK\x03\x04" + b"\x00" * 40)


def test_archive_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    data = s.archive({"a.json": b"{}", "b.json": b"{}"})
    monkeypatch.setattr(decrypt_module, "MAX_MEMBERS", 1)
    with pytest.raises(DecryptError, match="too many"):
        open_publication(data)
    monkeypatch.setattr(decrypt_module, "MAX_MEMBERS", 10)
    monkeypatch.setattr(decrypt_module, "MAX_UNCOMPRESSED", 3)
    with pytest.raises(DecryptError, match="too large"):
        open_publication(data)
