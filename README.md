<div align="center">

![Home Connect Local: local control for Bosch, Siemens and Neff dishwasher, hob and oven, no cloud required](https://raw.githubusercontent.com/Asmir1975/homeconnect_local_hass-UI/main/assets/banner.png)

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square)](https://github.com/hacs/integration)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Integration-41BDF5?style=flat-square&logo=home-assistant&logoColor=white)](https://www.home-assistant.io/)
[![Version](https://img.shields.io/github/v/release/Asmir1975/homeconnect_local_hass-UI?style=flat-square&logo=github&color=41BDF5&logoColor=white&cacheSeconds=15600)](https://github.com/Asmir1975/homeconnect_local_hass-UI/releases)

[![GitHub stars](https://img.shields.io/github/stars/Asmir1975/homeconnect_local_hass-UI?style=flat-square&cacheSeconds=15600)](https://github.com/Asmir1975/homeconnect_local_hass-UI/stargazers)
[![GitHub downloads](https://img.shields.io/github/downloads/Asmir1975/homeconnect_local_hass-UI/total?style=flat-square&cacheSeconds=15600)](https://github.com/Asmir1975/homeconnect_local_hass-UI/releases)

The **Home Connect Local** integration lets you control Bosch, Siemens, and Neff home appliances directly over your local network, with no cloud required after setup.

<sub>Independently developed, forked from [chris-mc1/homeconnect_local_hass](https://github.com/chris-mc1/homeconnect_local_hass).</sub>

</div>

- 📥 **Cloud sign-in built into HA setup.** No desktop tool, works on any device including Android and iOS.
- 🔌 **Fully local control after setup.** No cloud round-trip once your appliance profile is downloaded.
- 🔄 **Independently maintained.** Its own ongoing bug fixes and features on top of the upstream codebase.

⭐ If this fork is useful to you, leaving a star helps others find it.

## 🆚 What's different in this fork?

| | Original integration | This fork |
|---|---|---|
| Profile download | Separate desktop app (Windows/macOS/Linux only) | Built into the HA setup flow, works on any device |
| Auth flow | — | Same Authorization Code + PKCE as the bruestel tool, no developer portal registration |

## 🧩 Install via HACS

1. Go to **HACS → Custom Repositories** and add:
   ```
   https://github.com/Asmir1975/homeconnect_local_hass-UI
   ```
   as type **Integration**.
2. Click **Download** to install.
3. Restart Home Assistant.

## ⚙️ Setup

1. Go to **Settings → Devices & Services → Add Integration** and search for **Home Connect Local**.

2. Choose your setup method:
   - **Sign in with Home Connect account** *(recommended)*: no extra tools needed, works on any device
   - **Upload profile ZIP manually**: use the [bruestel desktop tool](https://github.com/bruestel/homeconnect-profile-downloader) and upload the ZIP

3. **If signing in:**
   - Select your region (EU, NA, or CN)
   - Open the link shown, log in with your Home Connect account, and approve access
   - Copy that full URL from the address bar and paste it into the HA form
   - HA will automatically download your appliance profile

   > [!TIP]
   > Your browser will try to open a dead link after approving access. That's expected, it doesn't need to load.

4. Select the appliance to set up.

5. If the connection test fails, enter your appliance's IP address manually.

6. Repeat from step 1 to add more appliances.

## 📝 Notes

> [!NOTE]
> - Your credentials are not stored. Only the downloaded appliance profile (encryption key + device description) is saved in HA.
> - If your appliance is not discovered automatically, find its IP in your router's DHCP table.
> - The `hcauth://` redirect URL step is a known limitation of the authorization flow. A future improvement could automate this step.

## 🐛 Reporting Issues

[Open an issue here](https://github.com/Asmir1975/homeconnect_local_hass-UI/issues) for anything you run into with this fork, whether it's the profile download / sign-in flow or the core integration itself.

## 🙏 Credits

- [chris-mc1](https://github.com/chris-mc1) for the [Home Connect Local](https://github.com/chris-mc1/homeconnect_local_hass) integration and the [homeconnect-websocket](https://github.com/chris-mc1/homeconnect_websocket) library this fork is built on.
- [bruestel](https://github.com/bruestel) for the [homeconnect-profile-downloader](https://github.com/bruestel/homeconnect-profile-downloader) and the Authorization Code + PKCE flow the built-in downloader reuses.
- [SamJongenelen](https://github.com/SamJongenelen) for bringing the profile download into the setup flow (upstream PR 405).

## 🪵 Debug logging

```yaml
logger:
  logs:
    custom_components.homeconnect_ws: debug
    homeconnect_websocket: debug
```
