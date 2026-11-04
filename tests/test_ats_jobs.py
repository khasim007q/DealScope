from datetime import date

import httpx
import pytest

from dealscope.providers.ats_jobs import AtsJobSource, derive_slugs
from dealscope.providers.base import BadRequestError, ProviderError

SINCE = date(2026, 1, 1)
TERMS = ["platform", "security", "engineering_leadership"]

GH = {
    "jobs": [
        {
            "id": 1,
            "title": "Platform Engineer",
            "first_published": "2026-03-04T10:00:00-05:00",
            "updated_at": "2026-03-10T10:00:00-05:00",
            "absolute_url": "https://x/1",
            "departments": [{"name": "Engineering"}],
        },
        {
            "id": 2,
            "title": "Account Executive",
            "first_published": "2026-03-04T10:00:00-05:00",
            "departments": [{"name": "Sales"}],
            "absolute_url": "https://x/2",
        },
        {
            "id": 3,
            "title": "Security Engineer",
            "first_published": "2025-06-01T10:00:00-05:00",
            "departments": [],
            "absolute_url": "https://x/3",
        },
    ],
    "meta": {"total": 3},
}
LEVER = [
    {
        "id": "abc",
        "text": "Director, Engineering",
        "createdAt": 1772000000000,
        "categories": {"department": "Engineering", "location": "Remote"},
        "hostedUrl": "https://l/abc",
    },
    {
        "id": "abc",
        "text": "Director, Engineering",
        "createdAt": 1772000000000,
        "categories": {},
        "hostedUrl": "https://l/abc",
    },
]
ASHBY = {
    "jobs": [
        {
            "id": "u1",
            "title": "Staff Security Engineer",
            "department": "Product",
            "publishedAt": "2026-10-15T12:00:00.000+00:00",
            "jobUrl": "https://a/u1",
            "isListed": True,
        },
        {
            "id": "u2",
            "title": "Backend Engineer",
            "department": "Eng",
            "publishedAt": "2026-10-15T12:00:00.000+00:00",
            "jobUrl": "https://a/u2",
            "isListed": False,
        },
    ]
}


def source(routes: dict[str, object]):
    """routes: substring of URL -> JSON body; anything else 404."""
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        calls.append(url)
        for key, body in routes.items():
            if key in url:
                if isinstance(body, int):
                    return httpx.Response(body, json={"error": "x"})
                return httpx.Response(200, json=body)
        return httpx.Response(404, json={"error": "not found"})

    return AtsJobSource(transport=httpx.MockTransport(handler), sleep=lambda s: None), calls


def test_slug_derivation():
    assert derive_slugs("linear.app")[:2] == ["linear", "linearapp"]
    assert derive_slugs("https://www.foo-bar.com/")[:3] == ["foo-bar", "foobar", "foobarcom"]
    assert derive_slugs("acme.co.uk")[0] == "acme"
    assert "acme-labs" in derive_slugs("acme.io", "Acme Labs") and "acmelabs" in derive_slugs("acme.io", "Acme Labs")
    assert len(derive_slugs("a-b.c.d.example.com", "Some Long Name Inc")) <= 5


def test_greenhouse_normalization_and_filters():
    src, _ = source({"greenhouse.io/v1/boards/acme/": GH})
    r = src.search_jobs("acme.com", TERMS, SINCE, 10)
    assert r.endpoint == "ats:greenhouse:acme"
    assert [i.payload.title for i in r.items] == ["Platform Engineer"]  # sales dropped, 2025 posting too old
    p = r.items[0].payload
    assert (p.date_added, p.date_updated, p.category, p.url) == (
        "2026-03-04",
        "2026-03-10",
        "Engineering",
        "https://x/1",
    )
    assert p.role_group != "non_technical"
    assert r.items[0].independence_group == "ats:greenhouse:acme:job"
    assert "greenhouse board 'acme'" in r.notes[0]


def test_lever_epoch_dates_and_dedup():
    src, _ = source({"api.lever.co/v0/postings/acme": LEVER})
    r = src.search_jobs("acme.com", TERMS, SINCE, 10)
    assert r.endpoint == "ats:lever:acme" and r.result_count == 1
    assert r.items[0].payload.date_added == "2026-02-25"
    assert r.items[0].payload.role_group == "technical_leadership"


def test_ashby_unlisted_skipped():
    src, _ = source({"job-board/acme": ASHBY})
    r = src.search_jobs("acme.com", ["security", "platform"], SINCE, 10)
    assert r.endpoint == "ats:ashby:acme"
    assert [i.payload.title for i in r.items] == ["Staff Security Engineer"]
    assert r.items[0].payload.role_group == "security"


def test_priority_greenhouse_wins_and_name_slug_used():
    src, calls = source({"boards/acme/": GH, "postings/acme": LEVER})
    assert src.search_jobs("acme.com", TERMS, SINCE, 5).endpoint == "ats:greenhouse:acme"
    src2, _ = source({"boards/acmelabs/": GH})
    src2.set_company_name("acme.com", "Acme Labs")
    assert src2.search_jobs("acme.com", TERMS, SINCE, 5).endpoint == "ats:greenhouse:acmelabs"


def test_404_everywhere_is_empty_not_error():
    src, calls = source({})
    r = src.search_jobs("nothing.example", TERMS, SINCE, 5)
    assert r.items == [] and r.endpoint == "ats:none" and "no match" in r.notes[0]
    assert len(calls) == 3 * len(derive_slugs("nothing.example"))
    src.search_jobs("nothing.example", TERMS, SINCE, 5)  # cached negative result
    assert len(calls) == 3 * len(derive_slugs("nothing.example"))


def test_empty_board_skipped_and_limit_applies():
    big = {"jobs": [{"id": i, "title": f"Platform Engineer {i}", "first_published": "2026-05-01"} for i in range(20)]}
    src, _ = source({"boards/acme/": {"jobs": []}, "postings/acme": [], "job-board/acme": big})
    r = src.search_jobs("acme.com", ["platform"], SINCE, 5)
    assert r.endpoint == "ats:ashby:acme" and r.result_count == 5 and any("truncated" in n for n in r.notes)


def test_all_errors_raise_but_partial_errors_do_not():
    src, _ = source({"boards/": 500, "postings/": 500, "job-board/": 500})
    with pytest.raises(ProviderError):
        src.search_jobs("acme.com", TERMS, SINCE, 5)
    src, _ = source({"boards/": 500, "job-board/acme": ASHBY})
    assert src.search_jobs("acme.com", ["security"], SINCE, 5).endpoint == "ats:ashby:acme"


def test_invalid_role_terms():
    src, _ = source({})
    with pytest.raises(BadRequestError):
        src.search_jobs("acme.com", ["nope"], SINCE, 5)


# ---------------------------------------------------------------------------
# Board ownership, transient errors, size / time limits
# ---------------------------------------------------------------------------


def _gh(url: str) -> dict:
    return {"jobs": [{"id": 1, "title": "Platform Engineer", "first_published": "2026-05-01", "absolute_url": url}]}


def test_board_with_links_to_another_company_is_rejected():
    """ramp.xyz must not silently adopt the 'ramp' board that belongs to ramp.com."""
    src, _ = source({"boards/ramp/jobs": _gh("https://ramp.com/careers/1")})
    r = src.search_jobs("ramp.xyz", ["platform"], SINCE, 5)
    assert r.items == [] and r.endpoint == "ats:none"
    assert "belongs to ramp.com, not ramp.xyz" in r.notes[0]


def test_board_confirmed_by_links_to_own_domain():
    src, _ = source({"boards/ramp/jobs": _gh("https://www.ramp.com/careers/1")})
    r = src.search_jobs("ramp.com", ["platform"], SINCE, 5)
    assert r.items[0].payload.board_match == "confirmed" and "job links point to ramp.com" in r.notes[0]


def test_board_with_only_vendor_links_is_marked_name_only():
    src, calls = source(
        {"boards/ramp/jobs": _gh("https://boards.greenhouse.io/ramp/jobs/1"), "v1/boards/ramp": {"name": "Ramp"}}
    )
    r = src.search_jobs("ramp.xyz", ["platform"], SINCE, 5)
    assert r.items and all(i.payload.board_match == "name_only" for i in r.items)
    assert "matched by name only" in r.notes[0] and "board is named 'Ramp'" in r.notes[0]
    assert any(c.endswith("/v1/boards/ramp") for c in calls)  # board metadata was consulted


def test_board_name_equal_to_resolved_company_name_confirms():
    src, _ = source(
        {"boards/ramp/jobs": _gh("https://boards.greenhouse.io/ramp/jobs/1"), "v1/boards/ramp": {"name": "Ramp, Inc."}}
    )
    src.set_company_name("ramp.com", "Ramp")
    r = src.search_jobs("ramp.com", ["platform"], SINCE, 5)
    assert r.items[0].payload.board_match == "confirmed"


def test_ashby_organization_name_is_cross_checked():
    board = {"organization": {"name": "Acme Labs"}, "jobs": ASHBY["jobs"]}
    src, _ = source({"job-board/acme": board})
    src.set_company_name("acme.com", "Acme Labs")
    assert src.search_jobs("acme.com", ["security"], SINCE, 5).items[0].payload.board_match == "confirmed"


def test_greenhouse_request_does_not_ask_for_job_content():
    src, calls = source({"boards/acme/jobs": GH})
    src.search_jobs("acme.com", TERMS, SINCE, 5)
    assert not any("content=true" in c for c in calls)


def test_transient_error_is_not_cached_as_no_jobs():
    state = {"down": True}
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if state["down"] and "lever.co" in str(req.url):
            return httpx.Response(503, json={})
        if "boards/acme/jobs" in str(req.url) and not state["down"]:
            return httpx.Response(200, json=GH)
        return httpx.Response(404, json={})

    src = AtsJobSource(transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(ProviderError) as exc:
        src.search_jobs("acme.com", TERMS, SINCE, 5)  # one probe failed, nothing found
    assert exc.value.retryable and exc.value.code == "RETRY_EXHAUSTED"
    state["down"] = False
    r = src.search_jobs("acme.com", TERMS, SINCE, 5)  # the failure was not remembered
    assert r.endpoint == "ats:greenhouse:acme" and r.items


def test_transient_failure_is_not_written_to_the_response_cache(tmp_path):
    from dealscope.agent.tools import ToolExecutor
    from dealscope.budget.governor import CreditGovernor
    from dealscope.config import Settings
    from dealscope.domain.enums import RunMode, ToolName, ToolRunStatus
    from dealscope.domain.models import CaseInput, CaseState, PlannerAction
    from dealscope.persistence.repository import Repository
    from dealscope.providers.free_source import FREE_PRICE_OVERRIDES, FreeDataSource

    def always_503(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={})

    s = Settings(_env_file=None, dealscope_db_path=tmp_path / "d.sqlite3", pdl_usage_path=tmp_path / "u.json")
    repo = Repository(s.dealscope_db_path)
    gov = CreditGovernor(repo, s, pool="live", price_overrides=FREE_PRICE_OVERRIDES)
    ats = AtsJobSource(transport=httpx.MockTransport(always_503), sleep=lambda x: None)
    ex = ToolExecutor(repo, gov, FreeDataSource(None, ats), api_version="v", as_of=date(2026, 11, 4))
    state = CaseState(input=CaseInput(target_domain="acme.com", mode=RunMode.LIVE), mode=RunMode.LIVE, credit_budget=10)
    repo.create_case(state)
    action = PlannerAction(
        action=ToolName.SEARCH_JOBS,
        arguments={"domain": "acme.com", "role_terms": ["platform"], "lookback_days": 90, "limit": 25},
        question="q",
        why_this_action="w",
        expected_information_gain="low",
        decided_by="baseline",
    )
    out = ex.execute(state, action)
    assert out.status == ToolRunStatus.FAILED and out.reason == "RETRY_EXHAUSTED" and not out.disable_tool
    n = repo._one("SELECT COUNT(*) AS n FROM response_cache", ())["n"]
    assert n == 0


def test_oversized_board_is_skipped_not_parsed():
    big = {"jobs": [{"id": i, "title": f"Platform Engineer {i}"} for i in range(200)]}
    handler = lambda req: httpx.Response(200, json=big) if "boards/acme/jobs" in str(req.url) else httpx.Response(404)  # noqa: E731
    src = AtsJobSource(transport=httpx.MockTransport(handler), sleep=lambda s: None, max_response_bytes=500)
    r = src.search_jobs("acme.com", ["platform"], SINCE, 5)
    assert r.items == [] and r.endpoint == "ats:none"


def test_overall_deadline_and_cancel_stop_probing():
    import threading

    from dealscope.providers.base import RetryExhaustedError

    src, calls = source({"boards/acme/jobs": GH})
    src._find_deadline_s = 0.0
    with pytest.raises(RetryExhaustedError):
        src.search_jobs("acme.com", TERMS, SINCE, 5)
    assert calls == []  # nothing was sent once the deadline had passed
    src2, calls2 = source({"boards/acme/jobs": GH})
    ev = threading.Event()
    ev.set()
    src2.set_cancel_event(ev)
    with pytest.raises(RetryExhaustedError):
        src2.search_jobs("acme.com", TERMS, SINCE, 5)
    assert calls2 == []
