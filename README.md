<div align="center">

# Home Connect Local with built-in Profile Downloader

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square)](https://github.com/hacs/integration)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Integration-41BDF5?style=flat-square&logo=home-assistant&logoColor=white)](https://www.home-assistant.io/)
[![Version](https://img.shields.io/github/v/release/Asmir1975/homeconnect_local_hass-UI?style=flat-square&logo=github&color=41BDF5&logoColor=white&cacheSeconds=15600)](https://github.com/Asmir1975/homeconnect_local_hass-UI/releases)

[![GitHub stars](https://img.shields.io/github/stars/Asmir1975/homeconnect_local_hass-UI?style=flat-square&cacheSeconds=15600)](https://github.com/Asmir1975/homeconnect_local_hass-UI/stargazers)

</div>

> **Fork of [chris-mc1/homeconnect_local_hass](https://github.com/chris-mc1/homeconnect_local_hass)**
>
> This fork adds a built-in profile downloader to the HA setup flow, so you no longer need the separate [bruestel/homeconnect-profile-downloader](https://github.com/bruestel/homeconnect-profile-downloader) desktop tool on Windows, macOS, or Linux.

The **Home Connect Local** integration lets you control Bosch and Siemens home appliances directly over your local network. No cloud required after setup.

## What's different in this fork?

The original integration requires you to download your appliance profile using a separate desktop application (Windows/macOS/Linux only). This fork adds a **Sign in with Home Connect** option directly in the HA setup flow. The profile is downloaded automatically, so setup works from any device, including Android and iOS.

The authentication uses the same Authorization Code + PKCE flow as the bruestel desktop tool, with no developer portal registration required.

## Install via HACS

1. Go to **HACS → Custom Repositories** and add:
   ```
   https://github.com/Asmir1975/homeconnect_local_hass-UI
   ```
   as type **Integration**.
2. Click **Download** to install.
3. Restart Home Assistant.

## Setup

1. Go to **Settings → Devices & Services → Add Integration** and search for **Home Connect Local**.

2. Choose your setup method:
   - **Sign in with Home Connect account** *(recommended)*: no extra tools needed, works on any device
   - **Upload profile ZIP manually**: use the [bruestel desktop tool](https://github.com/bruestel/homeconnect-profile-downloader) and upload the ZIP

3. **If signing in:**
   - Select your region (EU, NA, or CN)
   - Open the link shown, log in with your Home Connect account, and approve access
   - Your browser will then try to open a dead link. This is expected, it doesn't need to load
   - Copy that full URL from the address bar and paste it into the HA form
   - HA will automatically download your appliance profile

4. Select the appliance to set up.

5. If the connection test fails, enter your appliance's IP address manually.

6. Repeat from step 1 to add more appliances.

## Notes

- Your credentials are not stored. Only the downloaded appliance profile (encryption key + device description) is saved in HA.
- If your appliance is not discovered automatically, find its IP in your router's DHCP table.
- The `hcauth://` redirect URL step is a known limitation of the authorization flow. A future improvement could automate this step.

## Reporting Issues

For issues specific to this fork (profile download / sign-in flow), [open an issue here](https://github.com/Asmir1975/homeconnect_local_hass-UI/issues).

For issues with the core integration (entities, local connection, protocols), please check the upstream repo: [chris-mc1/homeconnect_local_hass](https://github.com/chris-mc1/homeconnect_local_hass).

## Credits

- [chris-mc1](https://github.com/chris-mc1) for the [Home Connect Local](https://github.com/chris-mc1/homeconnect_local_hass) integration and the [homeconnect-websocket](https://github.com/chris-mc1/homeconnect_websocket) library this fork is built on.
- [bruestel](https://github.com/bruestel) for the [homeconnect-profile-downloader](https://github.com/bruestel/homeconnect-profile-downloader) and the Authorization Code + PKCE flow the built-in downloader reuses.
- [SamJongenelen](https://github.com/SamJongenelen) for bringing the profile download into the setup flow (upstream PR 405).

## Debug logging

```yaml
logger:
  logs:
    custom_components.homeconnect_ws: debug
    homeconnect_websocket: debug
```
