from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All host-specific network settings come from the environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_secret_key: str = "CHANGE_ME"
    database_path: str = "./database/imao.sqlite3"

    upstream_interface: str = "REPLACE_WITH_ETHERNET_INTERFACE"
    hotspot_interface: str = "REPLACE_WITH_WIFI_INTERFACE"
    hotspot_cidr: str = "REPLACE_WITH_HOTSPOT_CIDR"
    hotspot_gateway: str = "REPLACE_WITH_GATEWAY_ADDRESS"

    portal_host: str = "0.0.0.0"
    portal_port: int = 8000
    cookie_secure: bool = False

    default_quota_mb: int = 500
    session_poll_seconds: int = 2
    session_stale_minutes: int = 5
    session_max_hours: int = 12

    firewall_backend: str = "none"
    firewall_enabled: bool = False
    netctl_path: str = "/usr/local/sbin/imao-netctl"
    netctl_sudo: str = "/usr/bin/sudo"

    @property
    def database_file(self) -> Path:
        return Path(self.database_path).expanduser()


@lru_cache
def get_settings() -> Settings:
    return Settings()
