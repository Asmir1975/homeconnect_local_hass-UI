"""
Home Connect profile downloader.

Uses the same Authorization Code + PKCE flow, client ID, and redirect URI as
the bruestel/homeconnect-profile-downloader desktop tool. The user signs in
via their browser and pastes the resulting redirect URL back.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import zipfile
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

_LOGGER = logging.getLogger(__name__)

CLIENT_ID = "9B75AC9EC512F36C84256AC47D813E2C1DD0D6520DF774B020E1E6E2EB29B1F3"
REDIRECT_URI = "hcauth://auth/prod"
SCOPE = (
    "Control DeleteAppliance IdentifyAppliance Images Monitor ReadAccount ReadOrigApi "
    "Settings WriteAppliance WriteOrigApi"
)

REGION_MAP = {
    "EU": ("https://api.home-connect.com", "https://eu.services.home-connect.com"),
    "NA": ("https://api-rna.home-connect.com", "https://na.services.home-connect.com"),
    "CN": ("https://api.home-connect.cn", "https://cn.services.home-connect.cn"),
}

URLENCODED = {"Content-Type": "application/x-www-form-urlencoded"}

# Config-flow dialogs block while these requests run; don't wait for aiohttp's 5 min default.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=60)


class HCAuthError(Exception):
    """Raised on authentication failure."""


@dataclass
class HCAppliance:
    """Appliance profile data."""

    ha_id: str
    brand: str
    vib: str
    mac: str
    appliance_type: str
    identifier: str
    connection_type: str
    key: str
    iv: str | None
    feature_mapping_filename: str
    device_description_filename: str
    device_description_xml: bytes = field(default=b"", repr=False)
    feature_mapping_xml: bytes = field(default=b"", repr=False)

    def to_profile_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "haId": self.ha_id,
            "brand": self.brand,
            "vib": self.vib,
            "mac": self.mac,
            "type": self.appliance_type,
            "identifier": self.identifier,
            "connectionType": self.connection_type,
            "key": self.key,
            "featureMappingFileName": self.feature_mapping_filename,
            "deviceDescriptionFileName": self.device_description_filename,
        }
        if self.iv:
            d["iv"] = self.iv
        return d


def _generate_code_verifier() -> str:
    """Generate a PKCE code verifier."""
    return base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()


def _generate_code_challenge(verifier: str) -> str:
    """Generate PKCE code challenge from verifier."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _generate_nonce(length: int = 16) -> str:
    """Generate a random nonce."""
    return base64.urlsafe_b64encode(os.urandom(length)).rstrip(b"=").decode()


def _extract_account_id(access_token: str) -> str:
    """Extract the Home Connect account ID from a JWT access token."""
    try:
        parts = access_token.split(".")
        if len(parts) != 3:
            msg = "Home Connect returned a malformed access token."
            raise HCAuthError(msg)
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        if not isinstance(payload, dict):
            msg = "Home Connect returned a malformed access token."
            raise HCAuthError(msg)
        account_id = payload.get("sub")
        if not isinstance(account_id, str) or not account_id:
            msg = "Home Connect access token does not contain an account ID."
            raise HCAuthError(msg)
    except HCAuthError:
        raise
    except (ValueError, TypeError, json.JSONDecodeError) as err:
        msg = "Home Connect returned a malformed access token."
        raise HCAuthError(msg) from err
    return account_id


class HCProfileDownloader:
    """Downloads Home Connect appliance profiles using Authorization Code + PKCE flow."""

    def __init__(self, session: aiohttp.ClientSession, region: str = "EU") -> None:
        self._session = session
        self.region = region.upper()
        if self.region not in REGION_MAP:
            raise ValueError(f"Invalid region '{region}'. Use EU, NA, or CN.")
        self.api_base, self.asset_base = REGION_MAP[self.region]
        self._code_verifier = _generate_code_verifier()
        self._state = _generate_nonce()

    def get_authorize_url(self) -> str:
        """Build the authorization URL the user must open in their browser."""
        params = {
            "redirect_url": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "response_type": "code",
            "prompt": "login",
            "code_challenge_method": "S256",
            "code_challenge": _generate_code_challenge(self._code_verifier),
            "state": self._state,
            "nonce": _generate_nonce(),
            "scope": SCOPE,
        }
        return f"{self.api_base}/security/oauth/authorize?{urlencode(params)}"

    def extract_code_from_redirect(self, redirect_url: str) -> str:
        """Extract the authorization code from the redirect URL the user pastes back."""
        try:
            parsed = urlparse(redirect_url)
            params = parse_qs(parsed.query)
            if "code" not in params:
                params = parse_qs(parsed.fragment)
            if "code" not in params:
                msg = (
                    "No authorization code found in the URL. "
                    "Make sure you copied the full redirect URL."
                )
                raise HCAuthError(msg)
            if params.get("state", [None])[0] != self._state:
                raise HCAuthError("State mismatch. Please restart the sign-in process.")
            return params["code"][0]
        except HCAuthError:
            raise
        except Exception as err:
            raise HCAuthError(f"Could not parse redirect URL: {err}") from err

    async def async_get_access_token(self, code: str) -> str:
        """Exchange authorization code for access token."""
        async with self._session.post(
            f"{self.api_base}/security/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code_verifier": self._code_verifier,
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
            headers=URLENCODED,
            timeout=REQUEST_TIMEOUT,
        ) as resp:
            text = await resp.text()
            if not text.strip():
                msg = "Token endpoint returned an empty response."
                raise HCAuthError(msg)
            try:
                data = json.loads(text)
            except json.JSONDecodeError as err:
                msg = "Token endpoint returned an invalid response."
                raise HCAuthError(msg) from err
            if not isinstance(data, dict):
                msg = "Token endpoint returned an invalid response."
                raise HCAuthError(msg)
            if resp.status != 200:
                msg = f"Token request failed with HTTP status {resp.status}."
                raise HCAuthError(msg)
            token = data.get("access_token")
            if not isinstance(token, str) or not token:
                msg = "Token response did not contain an access token."
                raise HCAuthError(msg)
            return token

    async def async_get_appliances(self, access_token: str) -> list[HCAppliance]:
        """Fetch appliance profiles using the access token."""
        account_id = _extract_account_id(access_token)

        auth_headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

        async with self._session.get(
            f"{self.asset_base}/api/account/v2/accounts/{account_id}/paired-appliances",
            headers=auth_headers,
            timeout=REQUEST_TIMEOUT,
        ) as resp:
            if resp.status == 401:
                msg = "Wrong region. Try a different region."
                raise HCAuthError(msg)
            if resp.status != 200:
                msg = f"Appliance list request failed with HTTP status {resp.status}."
                raise HCAuthError(msg)
            data = await resp.json(content_type=None)
            if not isinstance(data, dict) or not isinstance(data.get("appliances", []), list):
                msg = "Appliance list response had an unexpected format."
                raise HCAuthError(msg)
            _LOGGER.debug("HC: paired-appliances: %d found", len(data.get("appliances", [])))

        all_appliances = data.get("appliances", [])
        appliances = [a for a in all_appliances if not a.get("isDemo")]
        if not appliances:
            msg = "No appliances found on this account."
            raise HCAuthError(msg)
        _LOGGER.debug("HC: found %d appliance(s)", len(appliances))

        results: list[HCAppliance] = []
        for appliance in appliances:
            ha_id: str = appliance.get("haId", "")
            if not ha_id:
                _LOGGER.warning("Skipping Home Connect appliance without an ID")
                continue
            _LOGGER.debug("HC: processing %s", ha_id)

            enc_data: dict[str, Any] = {}
            async with self._session.get(
                f"{self.asset_base}/api/appliance/v2/appliances/{ha_id}/encryption-information",
                headers=auth_headers,
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                if resp.status == 200:
                    enc_data = await resp.json(content_type=None)
                    # Do not log key material (TLS PSK / AES key+iv); only structure.
                    _LOGGER.debug("HC: encryption info for %s: %s", ha_id, list(enc_data))
                else:
                    _LOGGER.warning("No encryption data for %s (%s)", ha_id, resp.status)

            mac = appliance.get("mac", ha_id.rsplit("-", maxsplit=1)[-1])
            vib = appliance.get("vib", "")
            brand = (appliance.get("brand") or "").upper()
            appliance_type = appliance.get("haType") or appliance.get("type", "")

            if enc_data.get("tls", {}).get("key"):
                connection_type, key, iv = "TLS", enc_data["tls"]["key"], None
            elif enc_data.get("aes", {}).get("key"):
                connection_type = "AES"
                key = enc_data["aes"]["key"]
                iv = enc_data["aes"].get("iv")
                if not iv:
                    # AES appliances can't connect without an IV; keeping the profile
                    # would only fail later in the flow with a misleading error.
                    _LOGGER.warning("No AES IV for %s, skipping", ha_id)
                    continue
            else:
                _LOGGER.warning("No encryption key for %s, skipping", ha_id)
                continue

            desc_xml = b""
            feat_xml = b""
            async with self._session.get(
                f"{self.asset_base}/api/iddf/v1/iddf/{ha_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                if resp.status == 200:
                    try:
                        with zipfile.ZipFile(io.BytesIO(await resp.read())) as zf:
                            for name in zf.namelist():
                                if name.endswith("_DeviceDescription.xml"):
                                    desc_xml = zf.read(name)
                                elif name.endswith("_FeatureMapping.xml"):
                                    feat_xml = zf.read(name)
                    except zipfile.BadZipFile:
                        _LOGGER.warning("Could not parse IDDF ZIP for %s", ha_id)
                else:
                    _LOGGER.warning("IDDF fetch failed for %s (%s)", ha_id, resp.status)

            results.append(
                HCAppliance(
                    ha_id=ha_id,
                    brand=brand,
                    vib=vib,
                    mac=mac,
                    appliance_type=appliance_type,
                    identifier=ha_id,
                    connection_type=connection_type,
                    key=key,
                    iv=iv,
                    feature_mapping_filename=f"{ha_id}_FeatureMapping.xml",
                    device_description_filename=f"{ha_id}_DeviceDescription.xml",
                    device_description_xml=desc_xml,
                    feature_mapping_xml=feat_xml,
                )
            )

        return results
