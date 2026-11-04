"""Composite free data source: company + people from People Data Labs, jobs from public ATS job boards.

Implements the ``DataSource`` protocol. Everything costs 0 Crustdata credits, so ``credits_used`` is always
``Decimal("0")`` and the governor must be given ``FREE_PRICE_OVERRIDES`` (see below) so reservations are 0.

Without a PDL key, ``enrich_company`` / ``search_people`` / ``identify_company`` raise
``PdlNotConfiguredError`` (a BadRequestError with code ``NOT_CONFIGURED``): the executor records a failed,
non-fatal tool run and disables only that tool, so the affected signals come out "not scored" while job
postings keep working.

Wiring (see also the hand-off notes): ::

    source = FreeDataSource.from_settings(settings)
    governor = CreditGovernor(repo, settings, price_overrides=FREE_PRICE_OVERRIDES, pool="live")
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx

from dealscope.budget.governor import COMPANY_ENRICH, COMPANY_SEARCH, JOB_SEARCH, PERSON_ENRICH_CACHED, PERSON_SEARCH
from dealscope.config import Settings
from dealscope.providers.ats_jobs import AtsJobSource
from dealscope.providers.base import ProviderResult
from dealscope.providers.crustdata import IdentityCheck
from dealscope.providers.pdl import PdlClient, PdlCompanyCache, PdlNotConfiguredError, shared_usage_counter

PROVIDER = "free"
ZERO = Decimal("0")

# Pass as ``CreditGovernor(..., price_overrides=FREE_PRICE_OVERRIDES)``. ``job_search`` needs an explicit 0
# (otherwise the governor fails closed with UNKNOWN_PRICE because no Crustdata job price is configured).
# Leave CRUSTDATA_JOB_CALL_RESERVE empty, otherwise the governor still adds that flat reserve per job search.
FREE_PRICE_OVERRIDES: dict[str, Decimal] = {
    COMPANY_ENRICH: ZERO,
    COMPANY_SEARCH: ZERO,
    PERSON_SEARCH: ZERO,
    PERSON_ENRICH_CACHED: ZERO,
    JOB_SEARCH: ZERO,
}

_NOT_CONFIGURED = (
    "People Data Labs is not configured (set PDL_API_KEY; free signup at peopledatalabs.com). "
    "Company and people signals cannot be scored without it."
)


class FreeDataSource:
    provider_name = PROVIDER

    def __init__(self, pdl: PdlClient | None, ats: AtsJobSource) -> None:
        self.pdl = pdl
        self.ats = ats

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        pdl_transport: httpx.BaseTransport | None = None,
        ats_transport: httpx.BaseTransport | None = None,
    ) -> FreeDataSource:
        pdl: PdlClient | None = None
        if settings.pdl_api_key is not None:
            pdl = PdlClient(
                settings.pdl_api_key.get_secret_value(),
                base_url=settings.pdl_base_url,
                timeout_s=settings.dealscope_http_timeout_seconds,
                max_retries=settings.dealscope_max_retries,
                max_people_results=settings.pdl_max_people_results,
                usage=shared_usage_counter(settings.pdl_usage_path, settings.pdl_monthly_limit),
                cache=PdlCompanyCache(settings.pdl_cache_file),
                max_records_per_case=settings.pdl_max_records_per_case,
                transport=pdl_transport,
            )
        ats = AtsJobSource(
            timeout_s=settings.ats_timeout_seconds,
            max_retries=min(1, settings.dealscope_max_retries),
            transport=ats_transport,
        )
        return cls(pdl, ats)

    def close(self) -> None:
        if self.pdl is not None:
            self.pdl.close()
        self.ats.close()

    def set_case_id(self, case_id: str | None) -> None:
        """Attribute subsequent PDL usage to this case (enforces the per-case record cap)."""
        if self.pdl is not None:
            self.pdl.case_id = case_id

    def set_cancel_event(self, event) -> None:
        self.ats.set_cancel_event(event)

    def unconfigured_tools(self) -> dict[str, str]:
        """Tools that cannot work with the current configuration: ``{tool_name: reason_code}``."""
        if self.pdl is not None:
            return {}
        return {"enrich_company": "NOT_CONFIGURED", "search_people": "NOT_CONFIGURED"}

    unconfigured_message = (
        "Company and people data skipped: no People Data Labs key set (free mode uses public job boards only)"
    )

    @property
    def pdl_configured(self) -> bool:
        return self.pdl is not None

    def _need_pdl(self) -> PdlClient:
        if self.pdl is None:
            raise PdlNotConfiguredError(_NOT_CONFIGURED)
        return self.pdl

    @staticmethod
    def _free(result: ProviderResult) -> ProviderResult:
        result.credits_used = ZERO
        return result

    # -- DataSource --------------------------------------------------------

    def enrich_company(self, domain: str) -> ProviderResult:
        result = self._free(self._need_pdl().enrich_company(domain))
        for item in result.items:
            name = getattr(item.payload, "name", None)
            if name:
                self.ats.set_company_name(domain, name)  # extra slug hint for later job lookups
        return result

    def search_people(
        self,
        target_domain: str,
        role_group: str,
        relationship: str,
        competitor_domain: str | None,
        limit: int,
    ) -> ProviderResult:
        return self._free(
            self._need_pdl().search_people(target_domain, role_group, relationship, competitor_domain, limit)
        )

    def search_jobs(self, domain: str, role_terms: list[str], since_date: date, limit: int) -> ProviderResult:
        return self._free(self.ats.search_jobs(domain, role_terms, since_date, limit))

    # -- identity (same shape as CrustdataClient.identify_company) ------------

    def identify_company(self, domain: str) -> IdentityCheck:
        return self._need_pdl().identify_company(domain)


__all__ = ["FREE_PRICE_OVERRIDES", "FreeDataSource"]
