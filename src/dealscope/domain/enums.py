from enum import StrEnum


class RunMode(StrEnum):
    LIVE = "live"
    SYNTHETIC = "synthetic"


class CaseStage(StrEnum):
    CREATED = "created"
    BASELINE = "baseline"
    INVESTIGATING = "investigating"
    VERIFYING = "verifying"
    REPORTING = "reporting"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class EvidenceKind(StrEnum):
    COMPANY_PROFILE = "company_profile"  # target/peer enrichment snapshot (headcount, growth, departments)
    PERSON_HISTORY = "person_history"  # one person's relevant professional history
    JOB_POSTING = "job_posting"


class SignalId(StrEnum):
    S1 = "S1"  # Technical-function trajectory divergence
    S2 = "S2"  # Critical-role continuity risk
    S3 = "S3"  # Critical capability coverage / senior bench proxy
    S4 = "S4"  # Critical-role hiring pressure
    S5 = "S5"  # Competitor talent movement


class SignalState(StrEnum):
    SCORABLE = "scorable"
    NOT_SCORED = "not_scored"
    LOW_COVERAGE = "low_coverage"
    CONFLICTING = "conflicting"


class ToolName(StrEnum):
    ENRICH_COMPANY = "enrich_company"
    SEARCH_PEOPLE = "search_people"
    SEARCH_JOBS = "search_jobs"
    STOP = "stop"


class ToolRunStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CACHED = "cached"
    BLOCKED = "blocked"
    UNKNOWN_OUTCOME = "unknown_outcome"


class ClaimType(StrEnum):
    OBSERVATION = "observation"
    INTERPRETATION = "interpretation"
    HYPOTHESIS = "hypothesis"
    QUESTION = "question"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    QUALIFIED = "qualified"
    REJECTED = "rejected"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LedgerStatus(StrEnum):
    RESERVED = "reserved"
    SETTLED_ACTUAL = "settled_actual"
    SETTLED_ESTIMATE = "settled_estimate"  # actual unknown; conservative estimate retained
    RELEASED = "released"  # request not sent / definitively not billed
    UNKNOWN = "unknown"  # outcome unknown after network failure
