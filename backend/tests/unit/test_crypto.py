import pytest
from cryptography.fernet import Fernet

from app.core.crypto import SecretBox, SecretDecryptionError


def test_round_trip() -> None:
    box = SecretBox(Fernet.generate_key().decode())
    ciphertext = box.encrypt("ghp_supersecret")
    assert "ghp_supersecret" not in ciphertext
    assert box.decrypt(ciphertext) == "ghp_supersecret"


def test_same_plaintext_encrypts_differently() -> None:
    box = SecretBox(Fernet.generate_key().decode())
    assert box.encrypt("x") != box.encrypt("x")


def test_wrong_key_cannot_decrypt() -> None:
    ciphertext = SecretBox(Fernet.generate_key().decode()).encrypt("secret")
    with pytest.raises(SecretDecryptionError):
        SecretBox(Fernet.generate_key().decode()).decrypt(ciphertext)


def test_garbage_cannot_decrypt() -> None:
    with pytest.raises(SecretDecryptionError):
        SecretBox(Fernet.generate_key().decode()).decrypt("not-a-token")
