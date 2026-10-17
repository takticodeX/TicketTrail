import pytest
from pydantic import ValidationError

from app.api.v1.schemas import LoginRequest, RegisterRequest, UserUpdateRequest


def test_register_normalises_email() -> None:
    body = RegisterRequest(email="  Alice@Example.COM ", password="long-enough-pw")
    assert body.email == "alice@example.com"


@pytest.mark.parametrize("password", ["short", "123456789"])
def test_register_requires_ten_character_password(password: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="a@example.com", password=password)


def test_register_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="not-an-email", password="long-enough-pw")


def test_register_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest.model_validate(
            {"email": "a@example.com", "password": "long-enough-pw", "role": "admin"}
        )


def test_login_accepts_short_password() -> None:
    # Short passwords must reach the credential check and fail there, not as 422.
    assert LoginRequest(email="a@example.com", password="x").password == "x"


@pytest.mark.parametrize("tz", ["UTC", "Europe/Rome", "America/New_York"])
def test_update_accepts_iana_time_zones(tz: str) -> None:
    assert UserUpdateRequest(timezone=tz).timezone == tz


@pytest.mark.parametrize("tz", ["Mars/Olympus", "CEST", "", "+02:00"])
def test_update_rejects_unknown_time_zones(tz: str) -> None:
    with pytest.raises(ValidationError):
        UserUpdateRequest(timezone=tz)


def test_new_password_requires_current_password() -> None:
    with pytest.raises(ValidationError, match="current_password"):
        UserUpdateRequest(new_password="a-brand-new-password")


def test_display_name_is_stripped_and_not_blank() -> None:
    assert UserUpdateRequest(display_name="  Alice  ").display_name == "Alice"
    with pytest.raises(ValidationError):
        UserUpdateRequest(display_name="   ")
