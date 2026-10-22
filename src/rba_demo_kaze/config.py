"""Runtime settings (env / .env)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "rba-demo-kaze"
    deployment: Literal["local", "cloud"] = "local"
    # Forced on in the cloud, where every hop the browser sees is https.
    cookie_secure: bool = False

    # Browser-facing IdP origin (hosted login) and the server-side one.
    idp_public_url: str = "http://localhost:8001"
    idp_internal_url: str = "http://localhost:8001"
    # This portal's public origin (its registered redirect_uri lives here).
    public_url: str = "http://localhost:8003"

    # Kaze Portal's public client id at the IdP (rba_idp.client_ids.SEEDED).
    client_id: str = "rk_Kz3sH8dYc5JfW1qN"
    session_cookie: str = "kaze_session"
    idp_timeout_seconds: float = 2.0

    @model_validator(mode="after")
    def _cloud_is_explicit(self) -> "Settings":
        if self.deployment != "cloud":
            return self
        self.cookie_secure = True
        problems = [
            f"{name.upper()} must be an https:// URL (is {getattr(self, name)!r})"
            for name in ("idp_public_url", "public_url")
            if not getattr(self, name).startswith("https://")
            or (urlparse(getattr(self, name)).hostname or "") in LOCAL_HOSTS
        ]
        if (urlparse(self.idp_internal_url).hostname or "") in LOCAL_HOSTS:
            problems.append("IDP_INTERNAL_URL points at localhost")
        if problems:
            raise ValueError("DEPLOYMENT=cloud refuses to start:\n  - " + "\n  - ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
