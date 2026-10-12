"""Environment-driven settings. Secrets are held as SecretStr and never logged."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from dealscope.domain.enums import RunMode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Crustdata
    crustdata_api_key: SecretStr | None = None
    crustdata_api_version: str = "2025-11-01"
    crustdata_base_url: str = "https://api.crustdata.com"
    crustdata_total_credits: Decimal = Decimal("5000")
    crustdata_global_reserve_credits: Decimal = Decimal("1000")
    crustdata_max_case_credits: Decimal = Decimal("300")
    crustdata_max_enriched_people: int = 20
    crustdata_max_people_search_results: int = 100
    # Empty until confirmed from official pricing; absent => live Jobs API disabled (fail closed).
    crustdata_job_cost_per_result: Decimal | None = None
    crustdata_job_call_reserve: Decimal | None = None

    # Runtime LLM (a coding-agent subscription is NOT a runtime key)
    llm_provider: str = "gemini"
    llm_api_key: SecretStr | None = None
    llm_model: str = "gemini-3.8-flash"
    # Optional stronger model used only for report synthesis escalation.
    llm_escalation_model: str | None = None
    # Comma-separated models tried in order when the primary is out of quota or overloaded (free-tier resilience).
    llm_fallback_models: str = ""

    @property
    def llm_fallback_list(self) -> list[str]:
        return [m.strip() for m in self.llm_fallback_models.split(",") if m.strip() and m.strip() != self.llm_model]

    # Business-plan assumptions per audit, from the cfo.ai model (evidence/cfo-ai/). Editable; used only to compare a
    # case's real cost with the plan. Dollars per credit is an assumption (Crustdata does not publish it).
    plan_dollars_per_credit: Decimal = Decimal("0.10")
    plan_credits_per_audit: Decimal = Decimal("26")
    plan_llm_cost_per_audit: Decimal = Decimal("0.05")
    plan_review_cost_per_audit: Decimal = Decimal("90")
    plan_tooling_cost_per_audit: Decimal = Decimal("2")
    plan_price_per_audit: Decimal = Decimal("1500")

    neatlogs_api_key: SecretStr | None = None

    dealscope_mode: RunMode = RunMode.SYNTHETIC
    dealscope_db_path: Path = Path("./data/dealscope.sqlite3")
    dealscope_max_iterations: int = Field(default=8, ge=1, le=8)
    dealscope_max_tool_calls: int = Field(default=12, ge=1, le=12)
    dealscope_max_runtime_seconds: int = Field(default=240, ge=10, le=900)
    dealscope_http_timeout_seconds: float = 25.0
    dealscope_max_retries: int = Field(default=2, ge=0, le=2)

    @field_validator("crustdata_job_cost_per_result", "crustdata_job_call_reserve", mode="before")
    @classmethod
    def _blank_is_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("crustdata_api_key", "llm_api_key", "neatlogs_api_key", mode="before")
    @classmethod
    def _blank_secret_is_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @property
    def spendable_global_credits(self) -> Decimal:
        return max(Decimal("0"), self.crustdata_total_credits - self.crustdata_global_reserve_credits)

    @property
    def jobs_price_configured(self) -> bool:
        return self.crustdata_job_cost_per_result is not None

    def public_status(self) -> dict[str, object]:
        """Safe-to-display status; never includes secret values."""
        return {
            "mode": self.dealscope_mode.value,
            "crustdata_key_present": self.crustdata_api_key is not None,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "llm_key_present": self.llm_api_key is not None,
            "neatlogs_key_present": self.neatlogs_api_key is not None,
            "jobs_price_configured": self.jobs_price_configured,
            "max_case_credits": str(self.crustdata_max_case_credits),
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
