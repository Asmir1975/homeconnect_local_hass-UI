"""Tests for config flow."""

from __future__ import annotations

from binascii import Error as BinasciiError
from typing import TYPE_CHECKING
from unittest.mock import ANY, AsyncMock, MagicMock, Mock, call
from uuid import uuid4
from zipfile import BadZipFile

from aiohttp import ClientConnectionError, ClientConnectorSSLError
from custom_components.homeconnect_ws import config_flow
from custom_components.homeconnect_ws.const import (
    CONF_AES_IV,
    CONF_FILE,
    CONF_MANUAL_HOST,
    CONF_PSK,
    DOMAIN,
)
from custom_components.homeconnect_ws.hc_auth import HCAppliance
from homeassistant.config_entries import SOURCE_IGNORE, SOURCE_USER
from homeassistant.const import CONF_DESCRIPTION, CONF_DEVICE, CONF_DEVICE_ID, CONF_HOST, CONF_NAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.selector import SelectOptionDict
from homeconnect_websocket import ParserError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import MockAppliance
from .const import (
    MOCK_AES_DEVICE_DESCRIPTION,
    MOCK_AES_DEVICE_ID,
    MOCK_AES_DEVICE_INFO,
    MOCK_CONFIG_DATA,
    MOCK_TLS_DEVICE_DESCRIPTION,
    MOCK_TLS_DEVICE_ID,
    MOCK_TLS_DEVICE_ID_2,
    MOCK_TLS_DEVICE_INFO,
)

if TYPE_CHECKING:
    import pytest
    from homeassistant.core import HomeAssistant

UPLOADED_FILE = str(uuid4())


async def async_start_upload_flow(hass: HomeAssistant) -> dict:
    """Start a user flow and select manual profile upload."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert not result["errors"]
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"method": "upload"}
    )


async def test_user_login_selection(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test selecting the built-in profile downloader and a region."""
    managed_session = MagicMock()
    get_session = Mock(return_value=managed_session)
    monkeypatch.setattr(config_flow, "async_get_clientsession", get_session)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["data_schema"].schema.get("method").config["options"] == ["login", "upload"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"method": "login"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "login"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"region": "na"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "authorize"
    assert "api-rna.home-connect.com" in result["description_placeholders"]["url"]
    get_session.assert_called_once_with(hass)

    hass.config_entries.flow.async_abort(result["flow_id"])


async def test_user_login_downloads_profile(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test the complete built-in profile download path."""
    appliance = MockAppliance(MOCK_TLS_DEVICE_INFO)
    monkeypatch.setattr(config_flow, "HomeAppliance", appliance)
    monkeypatch.setattr(
        config_flow,
        "parse_device_description",
        Mock(return_value=MOCK_TLS_DEVICE_DESCRIPTION),
    )
    monkeypatch.setattr(config_flow.random, "randbytes", Mock(return_value=b"\x01\x02\x03\x04"))

    downloaded = HCAppliance(
        ha_id=MOCK_TLS_DEVICE_ID,
        brand=MOCK_TLS_DEVICE_INFO["brand"],
        vib=MOCK_TLS_DEVICE_INFO["vib"],
        mac=MOCK_TLS_DEVICE_INFO["mac"],
        appliance_type=MOCK_TLS_DEVICE_INFO["type"],
        identifier=MOCK_TLS_DEVICE_ID,
        connection_type="TLS",
        key=MOCK_TLS_DEVICE_INFO["key"],
        iv=None,
        feature_mapping_filename="features.xml",
        device_description_filename="description.xml",
        device_description_xml=b"description",
        feature_mapping_xml=b"features",
    )
    downloader = MagicMock()
    downloader.get_authorize_url.return_value = "https://example.test/authorize"
    downloader.extract_code_from_redirect.return_value = "code"
    downloader.async_get_access_token = AsyncMock(return_value="token")
    downloader.async_get_appliances = AsyncMock(return_value=[downloaded])
    downloader_factory = Mock(return_value=downloader)
    monkeypatch.setattr(config_flow, "HCProfileDownloader", downloader_factory)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"method": "login"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"region": "eu"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"redirect_url": "hcauth://auth/prod?code=code"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PSK] == MOCK_TLS_DEVICE_INFO["key"]
    assert result["data"][CONF_HOST] == f"Test_Brand-Test_TLS-{MOCK_TLS_DEVICE_ID}"
    downloader.extract_code_from_redirect.assert_called_once()
    downloader.async_get_access_token.assert_awaited_once_with("code")
    downloader.async_get_appliances.assert_awaited_once_with("token")
    mock_setup_entry.assert_awaited_once()


async def test_user_init(
    hass: HomeAssistant,
    mock_process_profile_file: MagicMock,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test config flow init."""
    appliance = MockAppliance(MOCK_TLS_DEVICE_INFO)
    monkeypatch.setattr(config_flow, "HomeAppliance", appliance)

    result = await async_start_upload_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "upload"
    assert not result["errors"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_FILE: UPLOADED_FILE,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "device_select"
    assert not result["errors"]
    assert result["data_schema"].schema.get("device").config["options"] == [
        SelectOptionDict(
            value=MOCK_TLS_DEVICE_ID,
            label="Test_Brand Test_TLS (Test_vib)",
        ),
        SelectOptionDict(
            value=MOCK_AES_DEVICE_ID,
            label="Test_Brand Test_AES (Test_vib)",
        ),
        SelectOptionDict(
            value=MOCK_TLS_DEVICE_ID_2,
            label="Test_Brand Test_TLS (Test_vib)",
        ),
    ]

    hass.config_entries.flow.async_abort(result["flow_id"])
    mock_setup_entry.assert_not_awaited()


async def test_user_tls(
    hass: HomeAssistant,
    mock_process_profile_file: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test config flow compleate for TLS Appliance."""
    appliance = MockAppliance(MOCK_TLS_DEVICE_INFO)
    monkeypatch.setattr(config_flow, "HomeAppliance", appliance)

    randbytes = Mock()
    randbytes.return_value = bytes.fromhex("01020304")
    monkeypatch.setattr(config_flow.random, "randbytes", randbytes)

    result = await async_start_upload_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "upload"
    assert not result["errors"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_FILE: UPLOADED_FILE,
        },
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_DEVICE: MOCK_TLS_DEVICE_ID,
        },
    )

    assert appliance.description == MOCK_TLS_DEVICE_DESCRIPTION
    assert appliance.host == "Test_Brand-Test_TLS-010203040506070809"
    assert appliance.app_name == "Homeassistant"
    assert appliance.app_id == "01020304"
    assert appliance.psk64 == MOCK_TLS_DEVICE_INFO["key"]
    assert appliance.iv64 is None
    assert appliance.connection_callback == ANY

    appliance._connect.assert_awaited_once()
    appliance._close.assert_awaited_once()

    mock_process_profile_file.assert_called_once_with(UPLOADED_FILE)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test_Brand Test_TLS"
    assert result["data"][CONF_DESCRIPTION] == {
        "info": MOCK_TLS_DEVICE_INFO,
        "MOCK_TLS_DEVICE_DESCRIPTION": None,
    }
    assert result["data"][CONF_HOST] == "Test_Brand-Test_TLS-010203040506070809"
    assert result["data"][CONF_PSK] == MOCK_TLS_DEVICE_INFO["key"]
    assert CONF_AES_IV not in result["data"]
    assert result["data"][CONF_NAME] == "Test_Brand Test_TLS"
    assert result["data"][CONF_DEVICE_ID] == "01020304"

    mock_setup_entry.assert_awaited_once()


async def test_user_aes(
    hass: HomeAssistant,
    mock_process_profile_file: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test config flow compleate for AES Appliance."""
    appliance = MockAppliance(MOCK_AES_DEVICE_INFO)
    monkeypatch.setattr(config_flow, "HomeAppliance", appliance)

    randbytes = Mock()
    randbytes.return_value = bytes.fromhex("01020304")
    monkeypatch.setattr(config_flow.random, "randbytes", randbytes)

    result = await async_start_upload_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "upload"
    assert not result["errors"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_FILE: UPLOADED_FILE,
        },
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_DEVICE: MOCK_AES_DEVICE_ID,
        },
    )

    assert appliance.description == MOCK_AES_DEVICE_DESCRIPTION
    assert appliance.host == MOCK_AES_DEVICE_ID
    assert appliance.app_name == "Homeassistant"
    assert appliance.app_id == "01020304"
    assert appliance.psk64 == MOCK_AES_DEVICE_INFO["key"]
    assert appliance.iv64 == MOCK_AES_DEVICE_INFO["iv"]
    assert appliance.connection_callback == ANY

    appliance._connect.assert_awaited_once()
    appliance._close.assert_awaited_once()

    mock_process_profile_file.assert_called_once_with(UPLOADED_FILE)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test_Brand Test_AES"
    assert result["data"][CONF_DESCRIPTION] == {
        "info": MOCK_AES_DEVICE_INFO,
        "MOCK_AES_DEVICE_DESCRIPTION": None,
    }
    assert result["data"][CONF_HOST] == "101112131415161718"
    assert result["data"][CONF_PSK] == MOCK_AES_DEVICE_INFO["key"]
    assert result["data"][CONF_AES_IV] == MOCK_AES_DEVICE_INFO["iv"]
    assert result["data"][CONF_NAME] == "Test_Brand Test_AES"
    assert result["data"][CONF_DEVICE_ID] == "01020304"

    mock_setup_entry.assert_awaited_once()


async def test_user_select_device(
    hass: HomeAssistant,
    mock_process_profile_file: MagicMock,  # noqa: ARG001
) -> None:
    """Test select device."""
    mock_config = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG_DATA,
        unique_id=MOCK_TLS_DEVICE_ID,
    )
    mock_config.add_to_hass(hass)

    result = await async_start_upload_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "upload"
    assert not result["errors"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_FILE: UPLOADED_FILE,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "device_select"
    assert not result["errors"]
    assert result["data_schema"].schema.get("device").config["options"] == [
        SelectOptionDict(
            value=MOCK_AES_DEVICE_ID,
            label="Test_Brand Test_AES (Test_vib)",
        ),
        SelectOptionDict(
            value=MOCK_TLS_DEVICE_ID_2,
            label="Test_Brand Test_TLS (Test_vib)",
        ),
    ]
    hass.config_entries.flow.async_abort(result["flow_id"])


async def test_user_select_device_one(
    hass: HomeAssistant,
    mock_process_profile_file: MagicMock,  # noqa: ARG001
    mock_setup_entry: AsyncMock,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test select device when only one device left to setup."""
    appliance = MockAppliance(MOCK_AES_DEVICE_INFO)
    monkeypatch.setattr(config_flow, "HomeAppliance", appliance)

    randbytes = Mock()
    randbytes.return_value = bytes.fromhex("01020304")
    monkeypatch.setattr(config_flow.random, "randbytes", randbytes)

    mock_config = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG_DATA,
        unique_id=MOCK_TLS_DEVICE_ID,
    )
    mock_config.add_to_hass(hass)
    mock_config = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG_DATA,
        unique_id=MOCK_TLS_DEVICE_ID_2,
    )
    mock_config.add_to_hass(hass)

    result = await async_start_upload_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "upload"
    assert not result["errors"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_FILE: UPLOADED_FILE,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test_Brand Test_AES"
    assert result["data"][CONF_DESCRIPTION] == {
        "info": MOCK_AES_DEVICE_INFO,
        "MOCK_AES_DEVICE_DESCRIPTION": None,
    }
    assert result["data"][CONF_HOST] == "101112131415161718"
    assert result["data"][CONF_PSK] == MOCK_AES_DEVICE_INFO["key"]
    assert result["data"][CONF_AES_IV] == MOCK_AES_DEVICE_INFO["iv"]
    assert result["data"][CONF_NAME] == "Test_Brand Test_AES"
    assert result["data"][CONF_DEVICE_ID] == "01020304"


async def test_user_select_device_ignore(
    hass: HomeAssistant,
    mock_process_profile_file: MagicMock,  # noqa: ARG001
) -> None:
    """Test select device when one discovered device was ignored."""
    mock_config = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG_DATA,
        unique_id=MOCK_TLS_DEVICE_ID,
        source=SOURCE_IGNORE,
    )
    mock_config.add_to_hass(hass)

    result = await async_start_upload_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "upload"
    assert not result["errors"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_FILE: UPLOADED_FILE,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "device_select"
    assert not result["errors"]
    assert result["data_schema"].schema.get("device").config["options"] == [
        SelectOptionDict(
            value=MOCK_TLS_DEVICE_ID,
            label="Test_Brand Test_TLS (Test_vib)",
        ),
        SelectOptionDict(
            value=MOCK_AES_DEVICE_ID,
            label="Test_Brand Test_AES (Test_vib)",
        ),
        SelectOptionDict(
            value=MOCK_TLS_DEVICE_ID_2,
            label="Test_Brand Test_TLS (Test_vib)",
        ),
    ]
    hass.config_entries.flow.async_abort(result["flow_id"])


async def test_user_set_host(
    hass: HomeAssistant,
    mock_process_profile_file: MagicMock,  # noqa: ARG001
    mock_setup_entry: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test set host."""
    appliance = MockAppliance(MOCK_TLS_DEVICE_INFO)
    monkeypatch.setattr(config_flow, "HomeAppliance", appliance)
    appliance._connect.side_effect = ClientConnectionError()

    result = await async_start_upload_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_FILE: UPLOADED_FILE,
        },
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_DEVICE: MOCK_TLS_DEVICE_ID,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "host"
    assert result["errors"]["base"] == "cannot_connect"

    assert appliance.host == "Test_Brand-Test_TLS-010203040506070809"

    appliance._connect.assert_awaited_once()
    appliance._close.assert_awaited_once()

    appliance._connect.reset_mock()
    appliance._close.reset_mock()

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_HOST: "1.2.3.4",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "host"
    assert result["errors"]["base"] == "cannot_connect"

    assert appliance.host == "1.2.3.4"

    appliance._connect.assert_awaited_once()
    appliance._close.assert_awaited_once()

    appliance._connect.reset_mock(side_effect=True)
    appliance._close.reset_mock()

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_HOST: "5.6.7.8",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == "5.6.7.8"
    assert result["data"][CONF_MANUAL_HOST] is True

    assert appliance.host == "5.6.7.8"

    appliance._connect.assert_awaited_once()
    appliance._close.assert_awaited_once()

    mock_setup_entry.assert_awaited_once()


async def test_user_auth_failed_ssl_error(
    hass: HomeAssistant,
    mock_process_profile_file: MagicMock,  # noqa: ARG001
    mock_setup_entry: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test a config flow with ClientConnectorSSLError."""
    appliance = MockAppliance(MOCK_TLS_DEVICE_INFO)
    monkeypatch.setattr(config_flow, "HomeAppliance", appliance)

    appliance._connect.side_effect = ClientConnectorSSLError(MagicMock(), MagicMock())

    result = await async_start_upload_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_FILE: UPLOADED_FILE,
        },
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_DEVICE: MOCK_TLS_DEVICE_ID,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "host"
    assert result["errors"]["base"] == "cannot_connect"

    appliance._close.assert_awaited_once()
    hass.config_entries.flow.async_abort(result["flow_id"])
    mock_setup_entry.assert_not_awaited()


async def test_user_auth_failed_binascii_error(
    hass: HomeAssistant,
    mock_process_profile_file: MagicMock,  # noqa: ARG001
    mock_setup_entry: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test a config flow with BinasciiError."""
    appliance = MockAppliance(MOCK_TLS_DEVICE_INFO)
    monkeypatch.setattr(config_flow, "HomeAppliance", appliance)
    appliance._connect.side_effect = BinasciiError()

    result = await async_start_upload_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_FILE: UPLOADED_FILE,
        },
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_DEVICE: MOCK_TLS_DEVICE_ID,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "auth_failed"

    appliance._close.assert_awaited_once()
    mock_setup_entry.assert_not_awaited()


async def test_user_connection_failed_timeout(
    hass: HomeAssistant,
    mock_process_profile_file: MagicMock,  # noqa: ARG001
    mock_setup_entry: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test a config flow with TimeoutError."""
    appliance = MockAppliance(MOCK_TLS_DEVICE_INFO)
    monkeypatch.setattr(config_flow, "HomeAppliance", appliance)
    appliance._connect.side_effect = TimeoutError()

    result = await async_start_upload_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_FILE: UPLOADED_FILE,
        },
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_DEVICE: MOCK_TLS_DEVICE_ID,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "host"
    assert result["errors"]["base"] == "cannot_connect"

    appliance._close.assert_awaited_once()
    hass.config_entries.flow.async_abort(result["flow_id"])
    mock_setup_entry.assert_not_awaited()


async def test_user_connection_failed_connection_error(
    hass: HomeAssistant,
    mock_process_profile_file: MagicMock,  # noqa: ARG001
    mock_setup_entry: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test a config flow with ClientConnectionError."""
    appliance = MockAppliance(MOCK_TLS_DEVICE_INFO)
    monkeypatch.setattr(config_flow, "HomeAppliance", appliance)
    appliance._connect.side_effect = ClientConnectionError()

    result = await async_start_upload_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_FILE: UPLOADED_FILE,
        },
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_DEVICE: MOCK_TLS_DEVICE_ID,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "host"
    assert result["errors"]["base"] == "cannot_connect"

    appliance._close.assert_awaited_once()
    hass.config_entries.flow.async_abort(result["flow_id"])
    mock_setup_entry.assert_not_awaited()


async def test_user_invalid_config_parser(
    hass: HomeAssistant,
    mock_process_profile_file: MagicMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test a config flow with error in config parser."""
    mock_process_profile_file.side_effect = ParserError("Test Error")

    result = await async_start_upload_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_FILE: UPLOADED_FILE,
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "profile_file_parser_error"
    assert result["description_placeholders"] == {"error": "Test Error"}
    mock_setup_entry.assert_not_awaited()


async def test_user_invalid_zip(
    hass: HomeAssistant,
    mock_process_profile_file: MagicMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test an invalid ZIP returns a form error instead of crashing the flow."""
    mock_process_profile_file.side_effect = BadZipFile

    result = await async_start_upload_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_FILE: UPLOADED_FILE,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "upload"
    assert result["errors"]["base"] == "invalid_profile_file"
    mock_setup_entry.assert_not_awaited()


async def test_user_invalid_profile_no_info(
    hass: HomeAssistant,
    mock_process_profile_file: MagicMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test a reauthentication flow with no profile info."""
    mock_process_profile_file.return_value[MOCK_AES_DEVICE_ID] = {}

    result = await async_start_upload_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_FILE: UPLOADED_FILE,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_profile_file"
    mock_setup_entry.assert_not_awaited()

    result = await async_start_upload_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_FILE: UPLOADED_FILE,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_profile_file"
    mock_setup_entry.assert_not_awaited()


async def test_user_invalid_profile_no_description(
    hass: HomeAssistant,
    mock_process_profile_file: MagicMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test a config flow with no description."""
    mock_process_profile_file.return_value[MOCK_AES_DEVICE_ID].pop("description")

    result = await async_start_upload_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_FILE: UPLOADED_FILE,
        },
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_DEVICE: MOCK_AES_DEVICE_ID,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_profile_file"
    mock_setup_entry.assert_not_awaited()


async def test_user_invalid_profile_info(
    hass: HomeAssistant,
    mock_process_profile_file: MagicMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test a reauthentication flow with invalid info."""
    mock_process_profile_file.return_value[MOCK_AES_DEVICE_ID]["info"].pop("key")

    result = await async_start_upload_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_FILE: UPLOADED_FILE,
        },
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_DEVICE: MOCK_AES_DEVICE_ID,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_profile_file"
    mock_setup_entry.assert_not_awaited()


async def test_user_select_all_setup(
    hass: HomeAssistant,
    mock_process_profile_file: MagicMock,  # noqa: ARG001
    mock_setup_entry: AsyncMock,
) -> None:
    """Test a config flow with all devices setup."""
    mock_config = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG_DATA,
        unique_id=MOCK_TLS_DEVICE_ID,
    )
    mock_config.add_to_hass(hass)
    mock_config = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG_DATA,
        unique_id=MOCK_TLS_DEVICE_ID_2,
    )
    mock_config.add_to_hass(hass)
    mock_config = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG_DATA,
        unique_id=MOCK_AES_DEVICE_ID,
    )
    mock_config.add_to_hass(hass)

    result = await async_start_upload_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_FILE: UPLOADED_FILE,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "all_setup"
    mock_setup_entry.assert_not_awaited()


async def test_process_profile(
    monkeypatch: pytest.MonkeyPatch,
    hass: HomeAssistant,
    mock_process_uploaded_file: MagicMock,
) -> None:
    """Test processing profile file."""
    mock_parser = MagicMock()
    monkeypatch.setattr(config_flow, "parse_device_description", mock_parser)

    mock_config_flow = AsyncMock()
    mock_config_flow.hass = hass
    result = config_flow.HomeConnectConfigFlow._process_profile_file(
        mock_config_flow, UPLOADED_FILE
    )

    assert result == {
        MOCK_TLS_DEVICE_ID: {
            "info": MOCK_TLS_DEVICE_INFO,
            "description": mock_parser.return_value,
        },
        MOCK_AES_DEVICE_ID: {
            "info": MOCK_AES_DEVICE_INFO,
            "description": mock_parser.return_value,
        },
    }

    mock_parser.assert_has_calls(
        [
            call(b"TLS_DeviceDescription", b"TLS_FeatureMapping"),
            call(b"AES_DeviceDescription", b"AES_FeatureMapping"),
        ],
        any_order=True,
    )
    mock_process_uploaded_file.assert_called_with(ANY, UPLOADED_FILE)
