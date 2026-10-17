import httpx
import pytest
import respx

from app.integrations.trackers.azure import AUTH_ERROR_MESSAGE, AzureBoardsClient
from app.integrations.trackers.base import TrackerAuthError, TrackerError, TrackerNotFoundError

ORG = "https://dev.azure.com/acme"
PROJECT_URL = f"{ORG}/_apis/projects/My%20Project"


def client() -> AzureBoardsClient:
    return AzureBoardsClient(ORG, "My Project", "the-pat", timeout=5)


@respx.mock
def test_test_connection_returns_project_name() -> None:
    route = respx.get(PROJECT_URL, params={"api-version": "7.1"}).mock(
        return_value=httpx.Response(200, json={"id": "p1", "name": "My Project"})
    )
    with client() as azure:
        assert azure.test_connection() == "My Project"
    request = route.calls.last.request
    # Basic base64(":" + PAT)
    assert request.headers["Authorization"] == "Basic OnRoZS1wYXQ="


@pytest.mark.parametrize("status", [401, 403])
@respx.mock
def test_unauthorised(status: int) -> None:
    respx.get(PROJECT_URL).mock(return_value=httpx.Response(status))
    with client() as azure, pytest.raises(TrackerAuthError, match="PAT invalid"):
        azure.test_connection()


@respx.mock
def test_sign_in_page_counts_as_auth_failure() -> None:
    respx.get(PROJECT_URL).mock(
        return_value=httpx.Response(
            203, text="<html>Sign in</html>", headers={"content-type": "text/html"}
        )
    )
    with client() as azure, pytest.raises(TrackerAuthError):
        azure.test_connection()


@respx.mock
def test_redirect_counts_as_auth_failure() -> None:
    respx.get(PROJECT_URL).mock(
        return_value=httpx.Response(302, headers={"location": "https://login.example/"})
    )
    with client() as azure, pytest.raises(TrackerAuthError):
        azure.test_connection()


@respx.mock
def test_html_with_200_counts_as_auth_failure() -> None:
    respx.get(PROJECT_URL).mock(
        return_value=httpx.Response(200, text="<html/>", headers={"content-type": "text/html"})
    )
    with client() as azure, pytest.raises(TrackerAuthError):
        azure.test_connection()


@respx.mock
def test_project_not_found() -> None:
    respx.get(PROJECT_URL).mock(return_value=httpx.Response(404, json={"message": "nope"}))
    with client() as azure, pytest.raises(TrackerNotFoundError, match="My Project"):
        azure.test_connection()


@respx.mock
def test_server_error() -> None:
    respx.get(PROJECT_URL).mock(return_value=httpx.Response(500))
    with client() as azure, pytest.raises(TrackerError, match="HTTP 500"):
        azure.test_connection()


@respx.mock
def test_timeout() -> None:
    respx.get(PROJECT_URL).mock(side_effect=httpx.ConnectTimeout("slow"))
    with client() as azure, pytest.raises(TrackerError, match="in time"):
        azure.test_connection()


def test_auth_message_names_the_scope() -> None:
    assert "Work Items" in AUTH_ERROR_MESSAGE
