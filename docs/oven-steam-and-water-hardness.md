# Oven steam assistance and water hardness

Two optional LAN select entities use the appliance's own catalog:

- `Cooking.Oven.Option.SteamAssistLevel`: program option, not a persistent setting.
- `Cooking.Oven.Setting.WaterHardness`: configuration setting; separate from dishwasher hardness.

They are created only when the corresponding entity exists. Options and numeric
codes are derived from the appliance enumeration; no fixed UID or fabricated
intermediate steam level is used by the integration. Labels are included in all
nine available languages. Existing access/availability checks continue to apply.

On NEFF B5AVM7AG7, the observed enum codes are steam Off=0, Low=1, High=3 and
hardness Softened=0, Soft=1, Medium=2, Hard=3, VeryHard=4. Captured official-app
writes confirm steam at program start and a water-hardness write of Soft.
Other hardness writes have offline wire tests, not physical-device trials.

Selecting a steam option does not itself start the oven. For explicit program
starts, include `Cooking.Oven.Option.SteamAssistLevel` in the existing
`homeconnect_ws.start_program_with_options` options only when supported by that
program. Do not assume a prior select write is included: that service deliberately
uses only its explicit options. On this oven the app excludes simultaneous steam
and rapid heating; the future oven UI should mirror that constraint. Do not infer
a universal rule for every model from this single capture.

The B5AVM7AG7 manual limits steam assistance to compatible heating modes and
80–240 °C with a full tank. Model-specific cooking constraints are not hardcoded
into the generic select entity. Water hardness must match the actual water used.

## Validation

Standalone validation:

```sh
python tests/test_oven_selects_standalone.py
python tests/test_atomic_start_validation.py
```

The standalone suite checks descriptors, translations and actual enum-to-wire
mapping with a mocked session. `tests/test_entity_descriptions.py` additionally
contains an HA-stack descriptor test; it requires the project's HA test dependencies.
