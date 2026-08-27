import httpx

from backend.routers.chat import _is_transient_provider_error


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://provider.example")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("provider error", request=request, response=response)


def test_transient_provider_errors_can_fall_back():
    assert _is_transient_provider_error(httpx.TimeoutException("slow"))
    assert _is_transient_provider_error(_status_error(429))
    assert _is_transient_provider_error(_status_error(503))


def test_client_and_authentication_errors_do_not_retry():
    assert not _is_transient_provider_error(_status_error(400))
    assert not _is_transient_provider_error(_status_error(401))
