# Refrigerator AutoSuper and Italian lighting names

Adds a config-category switch for
`Refrigeration.Common.Setting.Appliance.AutoSuper`, only when present in the
device catalog. It enables automatic Super Freeze behavior, not the existing
manual Super Freeze switch. No device-specific UID is hardcoded in the mapping.

The NEFF KB7962FE0 official-app test notified false then true for AutoSuper on
2026-10-07 at 10:29. This verifies state reception, not a live HA-originated write
or an automatic freeze cycle. Boolean write serialization is checked offline.

Italian names added for the existing `light_internal` and
`switch_refrigeration_light_theater_mode` translation keys. Unique IDs and entity
IDs are not explicitly renamed; existing custom names may override translations.
No appliance setting is changed by installing this code.

The new AutoSuper label is translated in all nine available project languages.
Existing entity keys remain unchanged; no new pairing is required.

Checks include standalone fridge/oven wire tests, explicit-start validation,
HA descriptor tests, and translation coverage/duplicate-key validation.
