"""Small, dependency-free reference implementation for DealScope's credit guard.

This is an example policy module for the application, not a Crustdata billing oracle.
Actual costs must be read from the current Crustdata price table/account usage.
Unknown-price operations are rejected by default.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping


@dataclass(frozen=True)
class BudgetConfig:
    total_credits: Decimal = Decimal("5000")
    global_reserve: Decimal = Decimal("1000")
    per_case_cap: Decimal = Decimal("300")

    @property
    def spendable_global(self) -> Decimal:
        return max(Decimal("0"), self.total_credits - self.global_reserve)


# Public prices should be verified before relying on them; costs here are estimates.
KNOWN_ESTIMATES: Mapping[str, Decimal] = {
    "company_enrich_per_profile": Decimal("2"),
    "company_search_per_result": Decimal("0.03"),
    "person_search_per_result": Decimal("0.03"),
    "person_enrich_cached_per_profile": Decimal("1"),
}


class BudgetDenied(RuntimeError):
    pass


@dataclass
class CreditLedger:
    config: BudgetConfig
    global_estimated_used: Decimal = Decimal("0")
    case_estimated_used: Decimal = Decimal("0")
    reserved: Decimal = Decimal("0")

    def estimate(self, operation: str, quantity: int, configured_unit_cost: Decimal | None = None) -> Decimal:
        if quantity < 0:
            raise ValueError("quantity must be non-negative")
        unit_cost = configured_unit_cost if configured_unit_cost is not None else KNOWN_ESTIMATES.get(operation)
        if unit_cost is None:
            raise BudgetDenied(f"UNKNOWN_PRICE_FAIL_CLOSED: {operation}")
        if unit_cost < 0:
            raise ValueError("unit cost cannot be negative")
        return unit_cost * quantity

    def reserve(self, operation: str, quantity: int, configured_unit_cost: Decimal | None = None) -> Decimal:
        amount = self.estimate(operation, quantity, configured_unit_cost)
        if self.case_estimated_used + self.reserved + amount > self.config.per_case_cap:
            raise BudgetDenied("PER_CASE_BUDGET_EXCEEDED")
        if self.global_estimated_used + self.reserved + amount > self.config.spendable_global:
            raise BudgetDenied("GLOBAL_SPENDABLE_BUDGET_EXCEEDED")
        self.reserved += amount
        return amount

    def settle(self, reserved_amount: Decimal, actual_amount: Decimal | None = None) -> None:
        if reserved_amount < 0 or reserved_amount > self.reserved:
            raise ValueError("invalid reservation settlement")
        self.reserved -= reserved_amount
        # If actual charge is unknown, charge the conservative estimate in the ledger.
        charge = reserved_amount if actual_amount is None else actual_amount
        if charge < 0:
            raise ValueError("actual amount cannot be negative")
        self.case_estimated_used += charge
        self.global_estimated_used += charge
        if self.case_estimated_used > self.config.per_case_cap:
            raise BudgetDenied("SETTLED_COST_EXCEEDED_CASE_CAP_REQUIRES_STOP")
        if self.global_estimated_used > self.config.spendable_global:
            raise BudgetDenied("SETTLED_COST_EXCEEDED_GLOBAL_CAP_REQUIRES_STOP")


def _demo() -> None:
    ledger = CreditLedger(BudgetConfig())
    reservation = ledger.reserve("company_enrich_per_profile", 4)
    ledger.settle(reservation)
    print(f"estimated used={ledger.global_estimated_used}; spendable={ledger.config.spendable_global}")
    try:
        ledger.reserve("jobs_api_unknown_price", 1)
    except BudgetDenied as exc:
        print(f"blocked as expected: {exc}")


if __name__ == "__main__":
    _demo()
