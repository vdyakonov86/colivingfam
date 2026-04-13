from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(validation_alias="BOT_TOKEN")
    telegram_admin_ids: str = Field(
        default="",
        validation_alias="TELEGRAM_ADMIN_IDS",
    )
    database_path: str = Field(default="data/app.db", validation_alias="DATABASE_PATH")
    max_residents: int = Field(default=50, ge=1, le=500, validation_alias="MAX_RESIDENTS")

    xui_base_url: str = Field(validation_alias="XUI_BASE_URL")
    xui_username: str = Field(validation_alias="XUI_USERNAME")
    xui_password: str = Field(validation_alias="XUI_PASSWORD")
    xui_inbound_id: int = Field(validation_alias="XUI_INBOUND_ID")
    xui_vless_flow: str = Field(default="", validation_alias="XUI_VLESS_FLOW")
    subscription_base_url: str = Field(default="", validation_alias="SUBSCRIPTION_BASE_URL")
    xui_verify_tls: bool = Field(default=True, validation_alias="XUI_VERIFY_TLS")

    link_code_ttl_minutes: int = Field(default=15, validation_alias="LINK_CODE_TTL_MINUTES")

    @field_validator("xui_base_url")
    @classmethod
    def strip_base_url(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def admin_id_set(self) -> set[int]:
        out: set[int] = set()
        for part in self.telegram_admin_ids.split(","):
            part = part.strip()
            if not part:
                continue
            out.add(int(part))
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
