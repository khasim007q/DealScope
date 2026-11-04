from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from dealscope.budget.governor import COMPANY_ENRICH, JOB_SEARCH, PERSON_SEARCH, CreditGovernor
from dealscope.config import Settings
from dealscope.providers.base import BadRequestError, DataSource
from dealscope.providers.free_source import FREE_PRICE_OVERRIDES, FreeDataSource
from dealscope.providers.pdl import PdlNotConfiguredError

GH = {"jobs": [{"id": 7, "title": "Platform Engineer", "first_published": "2026-05-01", "absolute_url": "https://x/7"}]}
COMPANY = {"id": "c1", "display_name": "Acme", "website": "acme.com", "size": "11-50", "employee_count": 30}


def settings(tmp_path: Path, key: str | None = None) -> Settings:
    return Settings(
        _env_file=None, pdl_api_key=key, pdl_usage_path=tmp_path / "usage.json", dealscope_db_path=tmp_path / "d.db"
    )


def transports():
    def ats(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=GH) if "boards/acme/" in str(req.url) else httpx.Response(404, json={})

    def pdl(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=COMPANY)

    return httpx.MockTransport(pdl), httpx.MockTransport(ats)


def test_settings_defaults_and_secret_handling(tmp_path):
    s = Settings(_env_file=None, pdl_api_key="  ")
    assert s.data_provider == "free" and s.pdl_api_key is None
    assert s.pdl_monthly_limit == 100 and s.pdl_max_people_results == 10
    assert s.public_status()["pdl_key_present"] is False
    s2 = settings(tmp_path, "k-secret")
    assert s2.public_status()["pdl_key_present"] is True and "k-secret" not in str(s2.public_status())


def test_protocol_and_no_pdl_key_degrades_cleanly(tmp_path):
    _, ats_t = transports()
    src = FreeDataSource.from_settings(settings(tmp_path), ats_transport=ats_t)
    assert isinstance(src, DataSource) and src.provider_name == "free" and not src.pdl_configured
    with pytest.raises(PdlNotConfiguredError) as e1:
        src.enrich_company("acme.com")
    assert e1.value.code == "NOT_CONFIGURED" and isinstance(e1.value, BadRequestError)
    assert "PDL_API_KEY" in str(e1.value)
    with pytest.raises(PdlNotConfiguredError):
        src.search_people("acme.com", "security", "past_target_employment", None, 5)
    with pytest.raises(PdlNotConfiguredError):
        src.identify_company("acme.com")
    jobs = src.search_jobs("acme.com", ["platform"], date(2026, 1, 1), 10)  # jobs still work
    assert jobs.result_count == 1 and jobs.credits_used == Decimal("0") and jobs.provider == "free"


def test_with_pdl_key_everything_is_zero_credit(tmp_path):
    pdl_t, ats_t = transports()
    src = FreeDataSource.from_settings(settings(tmp_path, "k"), pdl_transport=pdl_t, ats_transport=ats_t)
    assert src.pdl_configured
    r = src.enrich_company("acme.com")
    assert r.credits_used == Decimal("0") and r.items[0].payload.name == "Acme" and r.provider == "free"
    ident = src.identify_company("acme.com")
    assert ident.ok and ident.resolved_name == "Acme"
    assert src.pdl.usage.used() == 1  # identify reused the enrich lookup


def test_governor_prices_everything_at_zero(tmp_path):
    from dealscope.persistence.repository import Repository

    s = settings(tmp_path)
    gov = CreditGovernor(Repository(s.dealscope_db_path), s, price_overrides=FREE_PRICE_OVERRIDES)
    for op, qty in ((COMPANY_ENRICH, 1), (PERSON_SEARCH, 10), (JOB_SEARCH, 50)):
        assert gov.estimate(op, qty) == Decimal("0")
