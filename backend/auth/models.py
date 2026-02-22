from typing import Any

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6)
    display_name: str = Field(min_length=1, max_length=100)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    force_password_change: bool

    model_config = {"from_attributes": True}


class PasskeyStatusResponse(BaseModel):
    enabled: bool
    rp_id: str
    rp_name: str


class PasskeyRegisterOptionsRequest(BaseModel):
    current_password: str


class PasskeyBeginRequest(BaseModel):
    username: str | None = None


class PasskeyBeginResponse(BaseModel):
    request_id: int
    public_key: dict[str, Any]


class PasskeyVerifyRegistrationRequest(BaseModel):
    request_id: int
    credential: dict[str, Any]
    label: str | None = None


class PasskeyVerifyAuthenticationRequest(BaseModel):
    request_id: int
    credential: dict[str, Any]


class PasskeyCredentialResponse(BaseModel):
    id: int
    label: str
    credential_id: str
    device_type: str | None = None
    backed_up: bool
    transports: list[str]
    created_at: str | None = None
    last_used_at: str | None = None
