# Starting a program with explicit options

The existing `homeconnect_ws.start_program` action remains unchanged. The proposed
`homeconnect_ws.start_program_with_options` action sends a single local
`POST /ro/activeProgram` with a named program and explicitly supplied options.
It does not select the program first, write individual `/ro/values`, append cached
option values, change power settings, or retry a start after an error/timeout.

## Motivation and observed behavior

On a NEFF B5AVM7AG7 oven, separate option writes returned `WriteRequest Busy`.
A capture of the official app showed a successful local AirFry start with one
activeProgram request containing duration, start delay, cavity and temperature.
Reproducing that request through the pinned websocket library succeeded, with
Run and Finished notifications for both 60-second and 30-second cycles.
This establishes a working request format, not the internal cause of Busy.

The library already supports `Program.start(options, override_options=True)`;
the integration currently does not expose this explicit-options path.

## Example action

Use full program/option keys from **your appliance's description**. Identifiers,
capabilities, bounds and option types can differ across appliances. The following
is the observed oven request, not a universal appliance configuration:

```yaml
action: homeconnect_ws.start_program_with_options
data:
  device_id: YOUR_HOME_CONNECT_LOCAL_DEVICE_ID
  program: Cooking.Oven.Program.HeatingMode.AirFry
  options:
    BSH.Common.Option.Duration: 30
    BSH.Common.Option.StartInRelative: 0
    Cooking.Oven.Option.CavitySelector: Main
    Cooking.Oven.Option.SetpointTemperature: 180
```

Durations are seconds and temperature units follow the appliance option's
description. Enum labels are converted to raw protocol values; valid raw integer
enum values are also accepted. Boolean options require actual booleans, not
strings or integers. Numeric values must satisfy declared bounds and steps.

Options must belong to the requested program and be declared available/writable
for that program. Values are not derived from the previously selected program's
shadow state. No program defaults are appended: supply the complete option set
your appliance requires. Additional runtime restrictions remain enforced by the
appliance; cached/static metadata is not proof that a request will be accepted.

## Safety and validation scope

- No heating request is sent just by rendering a dashboard or validating options.
- A dashboard should check connection, door, remote-start permission and operation
  state, require an explicit user confirmation, and call the action once.
- Never automatically retry a heating request after a timeout: it may have run.
- Existing service behavior is preserved, including existing selected-program
  workflows. No Home Connect cloud fallback is introduced.
- Program-specific steam and fast-preheat options must only be supplied when
  present in the target program's catalog; do not send unsupported options even
  with a false/off value.
- Power-off `Busy` responses are a separate issue. In an observed test, standby
  followed the power-off request despite Busy. This proposal does not suppress
  such errors or claim to fix power-off behavior.

The standalone tests exercise validation and the pinned library's generated
message with a mocked transport. They do not connect to an appliance. Run them
with the project's websocket dependency installed:

```sh
python tests/test_atomic_start_validation.py
```

Live verification of the deployed HA action succeeded with a 30-second AirFry
cycle on the oven and an Auto cycle on a NEFF S177ECX14E dishwasher.
The dishwasher request used StartInRelative=0 and explicitly disabled ExtraDry,
HygienePlus, IntensivZone and VarioSpeedPlus. A previous request containing
SilenceOnDemand and SmartStartEnabled was rejected with code 400; removing both
made the request succeed, but does not identify which option caused rejection.
Do not infer that every option in a catalog can be sent at every lifecycle stage.

No packet capture, encryption keys, tokens, serial numbers or household traces
are included in the proposal.
