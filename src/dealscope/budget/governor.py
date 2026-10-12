"""CreditGovernor: persisted, fail-closed Crustdata credit accounting (docs/06 section 4).

The governor takes NO model/LLM input: prices come from the module constant (or constructor overrides
set by code/config) and caps come from ``Settings`` plus the case input validated at the boundary.

Lifecycle of a metered action:
    reserve()  -> persisted ``reserved`` ledger row BEFORE the request is sent
    settle()   -> ``settled_actual`` (actual cost known) or ``settled_estimate`` (conservative estimate kept)
    release()  -> ``released``: ONLY when no HTTP request was sent (4xx/5xx responses may still be billed)
    mark_unknown() -> ``unknown``: outcome unknown after a network failure; counts against the budget
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from dealscope.config import Settings
from dealscope.domain.enums import LedgerStatus
from dealscope.persistence.repository import Repository

# Operation names understood by the governor.
COMPANY_ENRICH = "company_enrich"
COMPANY_SEARCH = "company_search"
PERSON_SEARCH = "person_search"
PERSON_ENRICH_CACHED = "person_enrich_cached"
JOB_SEARCH = "job_search"

# PRICES MUST BE RE-VERIFIED against Crustdata's current pricing table / account console before live use.
# Credits per unit (profile or returned result), from Crustdata's published pricing
# (docs.crustdata.com/general/pricing.md, verified 2026-10-11 and against the account's /account/endpoints).
# Override via ``CreditGovernor(price_overrides=...)``.
# ``job_search`` is intentionally absent: its price comes from Settings and is unknown (fail closed) until set.
PRICES: dict[str, Decimal] = {
    COMPANY_ENRICH: Decimal("2"),  # per profile
    COMPANY_SEARCH: Decimal("0.03"),  # per result
    # 0.03 base + 0.1 experience filter + 0.1 experience returned (our searches always do both).
    PERSON_SEARCH: Decimal("0.23"),  # per returned profile
    PERSON_ENRICH_CACHED: Decimal("1"),  # per profile (live/contact retrieval may cost more)
}

UNKNOWN_PRICE = "UNKNOWN_PRICE_FAIL_CLOSED"
PER_CASE_EXCEEDED = "PER_CASE_BUDGET_EXCEEDED"
GLOBAL_EXCEEDED = "GLOBAL_SPENDABLE_BUDGET_EXCEEDED"


class BudgetDenied(RuntimeError):
    """Raised when an action must not be sent. ``reason`` is a stable code string."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


@dataclass(frozen=True)
class Reservation:
    ledger_id: int
    amount: Decimal
    operation: str
    case_id: str = ""
    quantity: int = 0


class CreditGovernor:
    def __init__(
        self,
        repo: Repository,
        settings: Settings,
        price_overrides: dict[str, Decimal] | None = None,
        safety_multiplier: Decimal = Decimal("1.0"),
        pool: str = "live",
    ) -> None:
        if pool not in ("live", "synthetic"):
            raise ValueError("pool must be 'live' or 'synthetic'")
        self.pool = pool
        if safety_multiplier < 1:
            raise ValueError("safety_multiplier must be >= 1")
        self.repo = repo
        self.settings = settings
        self.prices: dict[str, Decimal] = {**PRICES, **(price_overrides or {})}
        for op, price in self.prices.items():
            if price < 0:
                raise ValueError(f"negative price for {op}")
        self.safety_multiplier = safety_multiplier

    # -- pricing -----------------------------------------------------------

    def estimate(self, operation: str, quantity: int) -> Decimal:
        """Worst-case credits for ``quantity`` units (profiles/results). Fail closed on unknown prices."""
        if quantity < 0:
            raise ValueError("quantity must be non-negative")
        if operation == JOB_SEARCH:
            unit = self.prices.get(JOB_SEARCH, self.settings.crustdata_job_cost_per_result)
            if unit is None:
                raise BudgetDenied(UNKNOWN_PRICE, JOB_SEARCH)
            flat = self.settings.crustdata_job_call_reserve or Decimal("0")
            raw = unit * quantity + flat
        else:
            unit = self.prices.get(operation)
            if unit is None:
                raise BudgetDenied(UNKNOWN_PRICE, operation)
            raw = unit * quantity
        return raw * self.safety_multiplier

    # -- caps --------------------------------------------------------------

    def _case_limit(self, case_cap: Decimal) -> Decimal:
        return min(Decimal(case_cap), self.settings.crustdata_max_case_credits)

    # -- ledger lifecycle --------------------------------------------------

    def reserve(
        self,
        case_id: str,
        case_cap: Decimal,
        operation: str,
        quantity: int,
        tool_run_id: str | None = None,
    ) -> Reservation:
        """Check per-case and global caps, then persist a ``reserved`` row (atomically) before returning.

        Both checks conservatively include ``unknown`` rows (outcome unknown => possibly billed)."""
        amount = self.estimate(operation, quantity)
        limit = self._case_limit(case_cap)
        with self.repo.transaction():
            case = self.repo.ledger_totals(case_id)
            if case["reserved"] + case["estimated_used"] + case["unknown_estimate"] + amount > limit:
                raise BudgetDenied(PER_CASE_EXCEEDED, f"{operation} x{quantity} needs {amount}, case limit {limit}")
            # The account-wide allowance/reserve applies to real (live) credits only. Synthetic runs keep simulated
            # per-case accounting but must not be throttled by the sum of all past demo runs.
            if self.pool == "live":
                glob = self.repo.ledger_totals(None, self.pool)
                spendable = self.settings.spendable_global_credits
                if glob["reserved"] + glob["estimated_used"] + glob["unknown_estimate"] + amount > spendable:
                    raise BudgetDenied(
                        GLOBAL_EXCEEDED, f"{operation} x{quantity} needs {amount}, spendable {spendable}"
                    )
            ledger_id = self.repo.ledger_insert(
                case_id, operation, quantity, amount, LedgerStatus.RESERVED, tool_run_id=tool_run_id, pool=self.pool
            )
        return Reservation(ledger_id=ledger_id, amount=amount, operation=operation, case_id=case_id, quantity=quantity)

    def _status_of(self, reservation: Reservation) -> str:
        row = self.repo.ledger_get(reservation.ledger_id)
        if row is None:
            raise KeyError(f"unknown ledger id: {reservation.ledger_id}")
        return str(row["status"])

    def settle(self, reservation: Reservation, actual: Decimal | None) -> None:
        """Close a reservation (or resolve an ``unknown`` one). ``actual`` given => ``settled_actual``;
        otherwise ``settled_estimate`` (the conservative estimate stays charged)."""
        if actual is not None and actual < 0:
            raise ValueError("actual cost cannot be negative")
        status = self._status_of(reservation)
        if status not in (LedgerStatus.RESERVED.value, LedgerStatus.UNKNOWN.value):
            raise ValueError(f"cannot settle a ledger row in status {status}")
        if actual is None:
            self.repo.ledger_update(reservation.ledger_id, LedgerStatus.SETTLED_ESTIMATE)
        else:
            self.repo.ledger_update(reservation.ledger_id, LedgerStatus.SETTLED_ACTUAL, actual=Decimal(actual))

    def release(self, reservation: Reservation, reason: str) -> None:
        """Free a reservation. Use ONLY when no HTTP request was sent; any response (even 4xx) may be billed."""
        status = self._status_of(reservation)
        if status != LedgerStatus.RESERVED.value:
            raise ValueError(f"cannot release a ledger row in status {status}")
        self.repo.ledger_update(reservation.ledger_id, LedgerStatus.RELEASED, reason=reason)

    def mark_unknown(self, reservation: Reservation, reason: str) -> None:
        """Network failure with unknown billing outcome: keep the estimate counted against the budget."""
        status = self._status_of(reservation)
        if status != LedgerStatus.RESERVED.value:
            raise ValueError(f"cannot mark unknown a ledger row in status {status}")
        self.repo.ledger_update(reservation.ledger_id, LedgerStatus.UNKNOWN, reason=reason)

    # -- reporting ---------------------------------------------------------

    def case_summary(self, case_id: str, case_cap: Decimal) -> dict[str, object]:
        """Figures for the UI. Distinguishes reserved / estimated / confirmed-actual / unknown."""
        totals = self.repo.ledger_totals(case_id)
        budget = self._case_limit(case_cap)
        committed = totals["reserved"] + totals["estimated_used"] + totals["unknown_estimate"]
        return {
            "budget": budget,
            "reserved": totals["reserved"],
            "estimated_used": totals["estimated_used"],
            "actual_used": totals["actual_used"],
            "unknown_count": totals["unknown_count"],
            "unknown_estimate": totals["unknown_estimate"],
            "remaining": max(Decimal("0"), budget - committed),
        }

    def global_summary(self) -> dict[str, object]:
        totals = self.repo.ledger_totals(None, self.pool)
        spendable = self.settings.spendable_global_credits
        committed = totals["reserved"] + totals["estimated_used"] + totals["unknown_estimate"]
        return {
            "spendable": spendable,
            "reserved": totals["reserved"],
            "estimated_used": totals["estimated_used"],
            "actual_used": totals["actual_used"],
            "unknown_count": totals["unknown_count"],
            "unknown_estimate": totals["unknown_estimate"],
            "remaining": max(Decimal("0"), spendable - committed),
        }
