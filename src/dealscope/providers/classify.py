"""Deterministic job-title classifier plus the shared query vocabularies.

``classify_title`` maps a free-text title to ``(role_group, capability)``. Rules are keyword based and
order-dependent (documented inline); no model call is involved, so results are reproducible and testable.
"""

from __future__ import annotations

import re

from dealscope.domain.models import Capability, RoleGroup

# Exact-phrase title lists used for person search (role_group -> titles).
PERSON_ROLE_GROUP_TITLES: dict[str, list[str]] = {
    "technical_leadership": [
        "CTO",
        "Chief Technology Officer",
        "VP Engineering",
        "Vice President of Engineering",
        "Head of Engineering",
        "Director of Engineering",
        "Chief Architect",
    ],
    "senior_technical_ic": [
        "Principal Engineer",
        "Staff Engineer",
        "Distinguished Engineer",
        "Principal Software Engineer",
        "Staff Software Engineer",
    ],
    "security": ["CISO", "Head of Security", "Security Engineering Manager", "Director of Security"],
    "data_ml": [
        "Head of Data",
        "Director of Data Science",
        "Head of Machine Learning",
        "ML Engineering Manager",
        "Director of Machine Learning",
    ],
}

# Fuzzy title terms used for job search (role_term -> titles).
JOB_ROLE_TERM_TITLES: dict[str, list[str]] = {
    "engineering_leadership": ["engineering manager", "director engineering", "head engineering", "vp engineering"],
    "platform": ["platform engineer", "infrastructure engineer", "backend engineer"],
    "security": ["security engineer", "security"],
    "data_ml": ["machine learning", "data engineer", "data scientist"],
    "reliability": ["site reliability", "sre", "devops"],
}

_STRONG_TECH = re.compile(
    r"\b(cto|ciso|chief technology|chief technical|chief architect|chief information security|chief security)\b"
)
_NON_TECH = re.compile(
    r"\b(sales|marketing|recruit\w*|talent|account (executive|manager)|customer success|finance|financial|"
    r"legal|counsel|human resources|hr|business development|accountant|accounting|payroll|office manager|"
    r"executive assistant|copywriter|supply chain|procurement|product manager|product marketing|"
    r"chief (executive|financial|marketing|revenue|people|operating|product)|ceo|cfo|cmo|coo|cro)\b"
)
_TECH_ANY = re.compile(
    r"\b(engineer\w*|developer|architect\w*|technolog\w*|technical|software|devops|sre|reliability|security|"
    r"infosec|cyber\w*|data|machine learning|ml|ai|mlops|infrastructure|platform|backend|frontend|"
    r"full ?stack|programmer|qa|cloud)\b"
)
_SECURITY = re.compile(r"\b(ciso|security|infosec|appsec|cyber\w*)\b")
_DATA_ML = re.compile(
    r"\b(machine learning|ml|ai|mlops|llm|deep learning|artificial intelligence)\b"
    r"|\bdata (science|scientist|scientists|engineer|engineering|platform|analyst|analytics|infrastructure)\b"
    r"|\b(head|director|vp|vice president|chief|lead|manager)( of)? data\b"
)
_LEADER = re.compile(
    r"\b(vp|svp|evp|vice president|head|director|chief)\b.*\b"
    r"(engineering|technology|technical|architecture|architect|infrastructure|platform|software|devops|sre)\b"
)
_SENIOR_IC = re.compile(r"\b(principal|staff|distinguished|fellow)\b")
_RELIABILITY = re.compile(r"\b(site reliability|sre|devops|reliability|observability)\b")
_PLATFORM = re.compile(r"\b(platform|infrastructure|backend|back end)\b")


def _normalize(title: str | None) -> str:
    return " ".join(re.sub(r"[^a-z0-9+#&/ ]", " ", (title or "").lower()).split())


def classify_title(title: str | None) -> tuple[RoleGroup, Capability]:
    t = _normalize(title)
    if not t:
        return "non_technical", "other"
    strong = bool(_STRONG_TECH.search(t))
    if not strong and (_NON_TECH.search(t) or not _TECH_ANY.search(t)):
        return "non_technical", "other"

    capability: Capability
    role_group: RoleGroup
    if _SECURITY.search(t):
        role_group, capability = "security", "security"
    elif _DATA_ML.search(t):
        role_group, capability = "data_ml", "data_ml"
    else:
        if strong or _LEADER.search(t):
            role_group = "technical_leadership"
        elif _SENIOR_IC.search(t):
            role_group = "senior_technical_ic"
        else:
            role_group = "other_technical"
        if _RELIABILITY.search(t):
            capability = "reliability"
        elif _PLATFORM.search(t):
            capability = "platform_engineering"
        else:
            capability = "general_engineering"
    return role_group, capability
