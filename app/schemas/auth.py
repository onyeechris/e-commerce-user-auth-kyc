import uuid

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models.user import AccountStatus, AuthProvider, UserRole


class SignupRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.confirm_password:
            raise ValueError("password and confirm_password do not match")
        return self


class SignupResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    account_status: AccountStatus
    detail: str


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ResendCodeRequest(BaseModel):
    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class GoogleAuthRequest(BaseModel):
    id_token: str = Field(min_length=20, max_length=4096)


class SessionResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: UserRole
    account_status: AccountStatus
    is_new_user: bool = False
    message: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(min_length=8, max_length=128)
    confirm_password: str

    @model_validator(mode="after")
    def passwords_match(self):
        if self.new_password != self.confirm_password:
            raise ValueError("new_password and confirm_password do not match")
        return self


class MessageResponse(BaseModel):
    detail: str


class CurrentUserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    avatar_url: str | None
    role: UserRole
    auth_provider: AuthProvider
    account_status: AccountStatus

    model_config = {"from_attributes": True}


class PublicUserResponse(BaseModel):
    """Display data only. Never add email, role or status here."""

    id: uuid.UUID
    full_name: str | None
    avatar_url: str | None

    model_config = {"from_attributes": True}
