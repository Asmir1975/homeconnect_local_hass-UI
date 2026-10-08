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

Deployment: copy `entity_descriptions/refrigeration.py`, `translations/en.json`
and `translations/it.json` into the existing HA component and restart HA.
These edits have not been deployed to HA by the agent. Check the new switch and
lighting labels after restart, without needing new pairing.

Remaining release work: add/review all new translation keys in every language
present in the project after the integration work is complete.

Checks: standalone fridge/oven mapping suites, explicit-start validation, Ruff.
The full Home Assistant fixture-based suite requires separate dependencies and
has not been executed in this local validation environment.
