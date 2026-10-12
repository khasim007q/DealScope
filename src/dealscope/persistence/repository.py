"""SQLite persistence for DealScope (stdlib ``sqlite3``, WAL, explicit transactions).

Every public write method commits its own transaction, so state is durable at every tool-result
boundary and a restarted process can resume from the last persisted result. Decimals are stored as
TEXT strings and parsed back with :class:`decimal.Decimal` (never floats).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from dealscope.domain.enums import LedgerStatus, ToolRunStatus
from dealscope.domain.models import CaseState, EvidenceRecord, FindingClaim, new_id

_SCHEMA_PATH = Path(__file__).with_name("sqlite_schema.sql")

_SUCCESS_STATUSES = (ToolRunStatus.SUCCEEDED.value, ToolRunStatus.CACHED.value)
_UNRESOLVED_STATUSES = (ToolRunStatus.STARTED.value, ToolRunStatus.UNKNOWN_OUTCOME.value)


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=True)


def _sha256(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


def idempotency_key(
    case_id: str, provider: str, endpoint: str, body: dict[str, Any], api_version: str, mode: str
) -> str:
    """sha256 over the canonical JSON of (case_id, provider, endpoint, body, api_version, mode)."""
    return _sha256(
        {
            "case_id": case_id,
            "provider": provider,
            "endpoint": endpoint,
            "body": body,
            "api_version": api_version,
            "mode": str(mode),
        }
    )


def cache_key(provider: str, endpoint: str, body: dict[str, Any], api_version: str, time_bucket: str) -> str:
    """Cross-case cache key (no case_id). ``time_bucket`` is a freshness bucket such as ``"2026-10-11"``."""
    return _sha256(
        {
            "provider": provider,
            "endpoint": endpoint,
            "body": body,
            "api_version": api_version,
            "time_bucket": time_bucket,
        }
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _dec_str(value: Decimal | int | str | None) -> str | None:
    return None if value is None else str(Decimal(value))


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class Repository:
    """Thread-safe (single connection + re-entrant lock) SQLite repository."""

    def __init__(self, db_path: Path | str) -> None:
        self._lock = threading.RLock()
        self._depth = 0
        if str(db_path) == ":memory:":
            target = ":memory:"
        else:
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            target = str(path)
        self.db_path = target
        # isolation_level=None => autocommit; transactions are opened explicitly in ``transaction()``.
        self._conn = sqlite3.connect(target, isolation_level=None, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Repository:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Atomic write transaction (BEGIN IMMEDIATE ... COMMIT). Re-entrant: nested use joins the outer one.

        The governor wraps its "check totals, then insert reservation" in this so the pair is atomic."""
        with self._lock:
            if self._depth > 0:
                self._depth += 1
                try:
                    yield self._conn
                finally:
                    self._depth -= 1
                return
            self._conn.execute("BEGIN IMMEDIATE")
            self._depth = 1
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")
            finally:
                self._depth = 0

    def _all(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def _one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    # -- cases & checkpoints ----------------------------------------------

    def create_case(self, state: CaseState) -> None:
        """Insert the case row and write its initial checkpoint (seq 0, label ``created``)."""
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO cases (case_id, mode, stage, run_label, state_json, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    state.case_id,
                    state.mode.value,
                    state.stage.value,
                    state.run_label,
                    "{}",
                    state.created_at.isoformat(),
                    state.updated_at.isoformat(),
                ),
            )
            self._write_checkpoint(conn, state, "created")

    def save_case(self, state: CaseState) -> None:
        """Persist the current state into the case row (no new checkpoint)."""
        with self.transaction() as conn:
            self._update_case_row(conn, state)

    def _update_case_row(self, conn: sqlite3.Connection, state: CaseState) -> None:
        state.updated_at = datetime.now(UTC)
        cur = conn.execute(
            "UPDATE cases SET mode=?, stage=?, run_label=?, state_json=?, updated_at=? WHERE case_id=?",
            (
                state.mode.value,
                state.stage.value,
                state.run_label,
                state.model_dump_json(),
                state.updated_at.isoformat(),
                state.case_id,
            ),
        )
        if cur.rowcount == 0:
            raise KeyError(f"unknown case_id: {state.case_id}")

    def _write_checkpoint(self, conn: sqlite3.Connection, state: CaseState, label: str) -> int:
        seq = conn.execute("SELECT COUNT(*) FROM checkpoints WHERE case_id=?", (state.case_id,)).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO checkpoints (case_id, seq, stage, label, state_json, created_at) VALUES (?,?,?,?,?,?)",
            (state.case_id, seq, state.stage.value, label, "{}", _now()),
        )
        checkpoint_id = int(cur.lastrowid or 0)
        state.latest_checkpoint_id = checkpoint_id
        self._update_case_row(conn, state)
        conn.execute("UPDATE checkpoints SET state_json=? WHERE id=?", (state.model_dump_json(), checkpoint_id))
        return checkpoint_id

    def checkpoint(self, state: CaseState, label: str) -> int:
        """Snapshot ``state``; sets ``state.latest_checkpoint_id``, persists the case row, returns the id."""
        with self.transaction() as conn:
            return self._write_checkpoint(conn, state, label)

    def latest_checkpoint(self, case_id: str) -> CaseState | None:
        row = self._one("SELECT state_json FROM checkpoints WHERE case_id=? ORDER BY id DESC LIMIT 1", (case_id,))
        return None if row is None else CaseState.model_validate_json(row["state_json"])

    def load_case(self, case_id: str) -> CaseState | None:
        row = self._one("SELECT state_json FROM cases WHERE case_id=?", (case_id,))
        return None if row is None else CaseState.model_validate_json(row["state_json"])

    def list_cases(self) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT case_id,"
            " json_extract(state_json, '$.input.target_domain') AS target,"
            " mode, stage, run_label, updated_at,"
            " json_extract(state_json, '$.finish_reason') AS finish_reason"
            " FROM cases ORDER BY updated_at DESC, rowid DESC"
        )
        return [dict(r) for r in rows]

    # -- tool runs ---------------------------------------------------------

    def start_tool_run(
        self,
        case_id: str,
        tool: str,
        idempotency_key: str,
        request_fingerprint: str,
        cost_estimate: Decimal | None,
    ) -> str:
        tool_run_id = new_id("tr")
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO tool_runs (tool_run_id, case_id, tool, idempotency_key, request_fingerprint, status,"
                " attempt_count, started_at, cost_estimate) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    tool_run_id,
                    case_id,
                    str(tool),
                    idempotency_key,
                    request_fingerprint,
                    ToolRunStatus.STARTED.value,
                    1,
                    _now(),
                    _dec_str(cost_estimate),
                ),
            )
        return tool_run_id

    def finish_tool_run(
        self,
        tool_run_id: str,
        status: ToolRunStatus | str,
        result_count: int | None = None,
        cost_actual: Decimal | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        attempt_count: int | None = None,
    ) -> None:
        status_value = ToolRunStatus(status).value
        with self.transaction() as conn:
            cur = conn.execute(
                "UPDATE tool_runs SET status=?, finished_at=?, result_count=COALESCE(?, result_count),"
                " cost_actual=COALESCE(?, cost_actual), error_code=?, error_message=?,"
                " attempt_count=COALESCE(?, attempt_count) WHERE tool_run_id=?",
                (
                    status_value,
                    _now(),
                    result_count,
                    _dec_str(cost_actual),
                    error_code,
                    error_message,
                    attempt_count,
                    tool_run_id,
                ),
            )
            if cur.rowcount == 0:
                raise KeyError(f"unknown tool_run_id: {tool_run_id}")

    @staticmethod
    def _tool_run_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["cost_estimate"] = _dec(d["cost_estimate"])
        d["cost_actual"] = _dec(d["cost_actual"])
        return d

    def find_successful_tool_run(self, case_id: str, idempotency_key: str) -> dict[str, Any] | None:
        """Latest succeeded/cached run for this case + idempotency key (satisfies resume without a re-call)."""
        row = self._one(
            "SELECT * FROM tool_runs WHERE case_id=? AND idempotency_key=? AND status IN (?,?)"
            " ORDER BY started_at DESC, rowid DESC LIMIT 1",
            (case_id, idempotency_key, *_SUCCESS_STATUSES),
        )
        return None if row is None else self._tool_run_dict(row)

    def get_tool_run(self, tool_run_id: str) -> dict[str, Any] | None:
        row = self._one("SELECT * FROM tool_runs WHERE tool_run_id=?", (tool_run_id,))
        return None if row is None else self._tool_run_dict(row)

    def list_tool_runs(self, case_id: str) -> list[dict[str, Any]]:
        rows = self._all("SELECT * FROM tool_runs WHERE case_id=? ORDER BY started_at, rowid", (case_id,))
        return [self._tool_run_dict(r) for r in rows]

    def find_unresolved_tool_runs(self, case_id: str) -> list[dict[str, Any]]:
        """Runs left in ``started`` / ``unknown_outcome``: possibly billed, must not be blindly replayed."""
        rows = self._all(
            "SELECT * FROM tool_runs WHERE case_id=? AND status IN (?,?) ORDER BY started_at, rowid",
            (case_id, *_UNRESOLVED_STATUSES),
        )
        return [self._tool_run_dict(r) for r in rows]

    # -- evidence ----------------------------------------------------------

    def add_evidence(self, records: list[EvidenceRecord]) -> list[str]:
        """Insert records, deduplicating on ``(case_id, dedup_key)``.

        Returns the *effective* evidence ids, one per input record and in input order: the new id for a
        freshly inserted record, or the EXISTING record's id when the dedup key was already stored (including
        duplicates within the same batch). Use :meth:`add_evidence_detailed` to learn which were new."""
        return [eid for eid, _ in self.add_evidence_detailed(records)]

    def add_evidence_detailed(self, records: list[EvidenceRecord]) -> list[tuple[str, bool]]:
        """Like :meth:`add_evidence` but returns ``(effective_evidence_id, inserted)`` pairs."""
        out: list[tuple[str, bool]] = []
        with self.transaction() as conn:
            for rec in records:
                existing = conn.execute(
                    "SELECT evidence_id FROM evidence WHERE case_id=? AND dedup_key=?", (rec.case_id, rec.dedup_key)
                ).fetchone()
                if existing is not None:
                    out.append((existing["evidence_id"], False))
                    continue
                conn.execute(
                    "INSERT INTO evidence (evidence_id, case_id, kind, subject_domain, dedup_key, record_json,"
                    " synthetic) VALUES (?,?,?,?,?,?,?)",
                    (
                        rec.evidence_id,
                        rec.case_id,
                        rec.kind.value,
                        rec.subject_domain,
                        rec.dedup_key,
                        rec.model_dump_json(),
                        1 if rec.synthetic else 0,
                    ),
                )
                out.append((rec.evidence_id, True))
        return out

    def get_evidence(self, case_id: str) -> list[EvidenceRecord]:
        rows = self._all("SELECT record_json FROM evidence WHERE case_id=? ORDER BY rowid", (case_id,))
        return [EvidenceRecord.model_validate_json(r["record_json"]) for r in rows]

    def get_evidence_by_ids(self, ids: list[str]) -> list[EvidenceRecord]:
        """Records for ``ids`` in the order given; unknown ids are skipped."""
        if not ids:
            return []
        unique = list(dict.fromkeys(ids))
        marks = ",".join("?" * len(unique))
        rows = self._all(f"SELECT evidence_id, record_json FROM evidence WHERE evidence_id IN ({marks})", tuple(unique))
        by_id = {r["evidence_id"]: EvidenceRecord.model_validate_json(r["record_json"]) for r in rows}
        return [by_id[i] for i in ids if i in by_id]

    # -- response cache ----------------------------------------------------

    def cache_get(self, key: str) -> Any | None:
        row = self._one("SELECT response_json FROM response_cache WHERE cache_key=?", (key,))
        return None if row is None else json.loads(row["response_json"])

    def cache_put(self, key: str, endpoint: str, response_obj: Any, api_version: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO response_cache (cache_key, endpoint, response_json, created_at, api_version)"
                " VALUES (?,?,?,?,?)",
                (key, endpoint, json.dumps(response_obj, default=str), _now(), api_version),
            )

    # -- reports & claims --------------------------------------------------

    def save_report(self, case_id: str, markdown: str, bundle: dict[str, Any], claims: list[FindingClaim]) -> int:
        """Store a new report version with its claims; returns the report version id."""
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO report_versions (case_id, markdown, bundle_json, created_at) VALUES (?,?,?,?)",
                (case_id, markdown, json.dumps(bundle, default=str), _now()),
            )
            report_id = int(cur.lastrowid or 0)
            for claim in claims:
                conn.execute(
                    "INSERT INTO claims (claim_id, case_id, report_version_id, claim_json) VALUES (?,?,?,?)",
                    (claim.claim_id, case_id, report_id, claim.model_dump_json()),
                )
        return report_id

    def latest_report(self, case_id: str) -> dict[str, Any] | None:
        row = self._one("SELECT * FROM report_versions WHERE case_id=? ORDER BY id DESC LIMIT 1", (case_id,))
        if row is None:
            return None
        claim_rows = self._all("SELECT claim_json FROM claims WHERE report_version_id=? ORDER BY rowid", (row["id"],))
        return {
            "id": row["id"],
            "case_id": row["case_id"],
            "markdown": row["markdown"],
            "bundle": json.loads(row["bundle_json"]),
            "created_at": row["created_at"],
            "claims": [FindingClaim.model_validate_json(r["claim_json"]) for r in claim_rows],
        }

    # -- events ------------------------------------------------------------

    def add_event(
        self,
        case_id: str,
        type: str,
        payload: dict[str, Any],
        created_at: str | None = None,  # noqa: A002
    ) -> int:
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO events (case_id, type, payload_json, created_at) VALUES (?,?,?,?)",
                (case_id, type, json.dumps(payload, default=str), created_at or _now()),
            )
            return int(cur.lastrowid or 0)

    def list_events(self, case_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        """Events in insertion order; ``after_id`` lets the UI poll incrementally."""
        rows = self._all("SELECT * FROM events WHERE case_id=? AND id>? ORDER BY id", (case_id, after_id))
        return [
            {
                "id": r["id"],
                "case_id": r["case_id"],
                "type": r["type"],
                "payload": json.loads(r["payload_json"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # -- recorded traces -------------------------------------------------

    def save_trace(self, trace_id: str, case_id: str, started_at: str, trace_json: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO traces (trace_id, case_id, started_at, trace_json) VALUES (?,?,?,?)",
                (trace_id, case_id, started_at, trace_json),
            )

    def list_traces(self, case_id: str) -> list[dict[str, Any]]:
        rows = self._all("SELECT trace_json FROM traces WHERE case_id=? ORDER BY started_at", (case_id,))
        return [json.loads(r["trace_json"]) for r in rows]

    # -- credit ledger primitives (used by CreditGovernor) -----------------

    def ledger_insert(
        self,
        case_id: str,
        operation: str,
        quantity: int,
        estimate: Decimal,
        status: LedgerStatus | str = LedgerStatus.RESERVED,
        tool_run_id: str | None = None,
        reason: str | None = None,
        pool: str = "live",
    ) -> int:
        now = _now()
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO usage_ledger (case_id, pool, tool_run_id, operation, quantity, estimate, status, reason,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    case_id,
                    pool,
                    tool_run_id,
                    operation,
                    quantity,
                    str(estimate),
                    LedgerStatus(status).value,
                    reason,
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid or 0)

    def ledger_update(
        self,
        ledger_id: int,
        status: LedgerStatus | str,
        actual: Decimal | None = None,
        reason: str | None = None,
    ) -> None:
        with self.transaction() as conn:
            cur = conn.execute(
                "UPDATE usage_ledger SET status=?, actual=COALESCE(?, actual), reason=COALESCE(?, reason),"
                " updated_at=? WHERE id=?",
                (LedgerStatus(status).value, _dec_str(actual), reason, _now(), ledger_id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"unknown ledger id: {ledger_id}")

    def ledger_get(self, ledger_id: int) -> dict[str, Any] | None:
        row = self._one("SELECT * FROM usage_ledger WHERE id=?", (ledger_id,))
        if row is None:
            return None
        d = dict(row)
        d["estimate"] = _dec(d["estimate"])
        d["actual"] = _dec(d["actual"])
        return d

    def ledger_rows(self, case_id: str | None = None) -> list[dict[str, Any]]:
        if case_id is None:
            rows = self._all("SELECT * FROM usage_ledger ORDER BY id")
        else:
            rows = self._all("SELECT * FROM usage_ledger WHERE case_id=? ORDER BY id", (case_id,))
        out = []
        for r in rows:
            d = dict(r)
            d["estimate"] = _dec(d["estimate"])
            d["actual"] = _dec(d["actual"])
            out.append(d)
        return out

    def ledger_totals(self, case_id: str | None, pool: str | None = None) -> dict[str, Any]:
        """Aggregate ledger rows (``case_id=None`` => global across all cases; released rows are ignored).

        * ``reserved``: sum of estimate where status is ``reserved``.
        * ``estimated_used``: sum of estimate for ``settled_estimate`` rows plus
          ``COALESCE(actual, estimate)`` for ``settled_actual`` rows.
        * ``actual_used``: sum of actual for ``settled_actual`` rows.
        * ``unknown_count`` / ``unknown_estimate``: count and summed estimate of ``unknown`` rows.
        """
        clauses: list[str] = []
        params: tuple[Any, ...] = ()
        if case_id is not None:
            clauses.append("case_id=?")
            params += (case_id,)
        if pool is not None:
            clauses.append("pool=?")
            params += (pool,)
        sql = "SELECT status, estimate, actual FROM usage_ledger"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        zero = Decimal("0")
        totals: dict[str, Any] = {
            "reserved": zero,
            "estimated_used": zero,
            "actual_used": zero,
            "unknown_count": 0,
            "unknown_estimate": zero,
        }
        for r in self._all(sql, params):
            estimate = Decimal(r["estimate"])
            actual = _dec(r["actual"])
            status = r["status"]
            if status == LedgerStatus.RESERVED.value:
                totals["reserved"] += estimate
            elif status == LedgerStatus.SETTLED_ESTIMATE.value:
                totals["estimated_used"] += estimate
            elif status == LedgerStatus.SETTLED_ACTUAL.value:
                totals["estimated_used"] += actual if actual is not None else estimate
                totals["actual_used"] += actual if actual is not None else zero
            elif status == LedgerStatus.UNKNOWN.value:
                totals["unknown_count"] += 1
                totals["unknown_estimate"] += estimate
        return totals
