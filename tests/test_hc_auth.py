"""Tests for the built-in Home Connect profile downloader."""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
from aiohttp import ClientSession
from custom_components.homeconnect_ws import hc_auth


def _access_token(payload: dict[str, object]) -> str:
    """Build an unsigned JWT-shaped token for parser tests."""
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"header.{encoded}.signature"


def test_authorize_url_and_redirect_validation() -> None:
    """Test PKCE URL generation and state validation."""
    session = MagicMock(spec=ClientSession)
    downloader = hc_auth.HCProfileDownloader(session, region="na")

    authorize_url = urlparse(downloader.get_authorize_url())
    query = parse_qs(authorize_url.query)

    assert authorize_url.netloc == "api-rna.home-connect.com"
    assert query["client_id"] == [hc_auth.CLIENT_ID]
    assert query["code_challenge_method"] == ["S256"]
    assert (
        downloader.extract_code_from_redirect(
            f"hcauth://auth/prod?code=test-code&state={query['state'][0]}"
        )
        == "test-code"
    )

    with pytest.raises(hc_auth.HCAuthError, match="State mismatch"):
        downloader.extract_code_from_redirect("hcauth://auth/prod?code=test-code&state=wrong")


@pytest.mark.parametrize(
    ("token", "message"),
    [
        ("not-a-jwt", "malformed"),
        (_access_token({}), "does not contain an account ID"),
    ],
)
def test_extract_account_id_rejects_malformed_tokens(token: str, message: str) -> None:
    """Test malformed access tokens become controlled authentication errors."""
    with pytest.raises(hc_auth.HCAuthError, match=message):
        hc_auth._extract_account_id(token)


def test_extract_account_id() -> None:
    """Test account ID extraction from a valid JWT-shaped access token."""
    assert hc_auth._extract_account_id(_access_token({"sub": "account-id"})) == "account-id"


async def test_access_token_uses_managed_session_and_timeout() -> None:
    """Test token exchange reuses the supplied session with a bounded timeout."""
    response = MagicMock(status=200)
    response.text = AsyncMock(return_value=json.dumps({"access_token": "token"}))
    request = MagicMock()
    request.__aenter__ = AsyncMock(return_value=response)
    request.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock(spec=ClientSession)
    session.post.return_value = request

    downloader = hc_auth.HCProfileDownloader(session, region="eu")

    assert await downloader.async_get_access_token("code") == "token"
    assert session.post.call_args.kwargs["timeout"] is hc_auth.REQUEST_TIMEOUT


async def test_access_token_error_does_not_expose_response_body() -> None:
    """Test a failed token response does not leak its body into UI-facing errors."""
    response = MagicMock(status=400)
    response.text = AsyncMock(return_value='{"secret": "sensitive response"}')
    request = MagicMock()
    request.__aenter__ = AsyncMock(return_value=response)
    request.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock(spec=ClientSession)
    session.post.return_value = request

    downloader = hc_auth.HCProfileDownloader(session)

    with pytest.raises(hc_auth.HCAuthError, match="HTTP status 400") as error:
        await downloader.async_get_access_token("code")
    assert "sensitive response" not in str(error.value)
