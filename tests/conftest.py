import pytest


@pytest.fixture(autouse=True)
def _reset_api_rate_limiter():
    """The identity-check limiter is process-wide state; start every test with an empty window."""
    from dealscope.api import server

    server._identity_hits.clear()
    yield
    server._identity_hits.clear()
