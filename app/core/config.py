from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVICE_NAME: str
    ENVIRONMENT: str
    LOG_LEVEL: str = "INFO"
    # Local convenience only: print OTP codes in the log when mail is not configured.
    LOG_OTP_CODES: bool = False

    POSTGRES_DSN: str
    DB_REQUIRE_SSL: bool = False

    TOKEN_SIGNING_KEY: str
    TOKEN_ALGORITHM: str = "HS256"
    # Written to the "iss" claim of every access token; other services check it to recognise our tokens.
    TOKEN_ISSUER: str = "marketly-auth"
    ACCESS_TTL_MINUTES: int = 15
    REFRESH_TTL_DAYS: int = 7

    GOOGLE_OAUTH_CLIENT_ID: str

    MAIL_API_KEY: str
    MAIL_SENDER_EMAIL: str
    MAIL_SENDER_NAME: str = "Marketly"

    OTP_TTL_MINUTES: int = 10
    OTP_ATTEMPT_LIMIT: int = 5
    OTP_RESEND_WAIT_SECONDS: int = 60

    ALLOWED_ORIGINS: str

    SESSION_COOKIE_DOMAIN: str = ""
    SESSION_COOKIE_SECURE: bool = True

    RATE_LIMIT_ENABLED: bool = True

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")


settings = Settings()
