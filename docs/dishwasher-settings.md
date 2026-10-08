# Dishwasher settings and local start verification

Observed on a NEFF S177ECX14E:

- `Dishcare.Dishwasher.Setting.GapIllumination` controls the status light,
  independently of the existing InfoLight and interior light settings.
- `Dishcare.Dishwasher.Setting.InteriorLightMode` uses appliance-provided enum
  values: `ApplianceOnDoorOpen` and `AlwaysOnDoorOpen`.
- OpenDry is already mapped by `DryingAssistantAllPrograms`: no duplicate entity
  is added. Off, AllPrograms and EcoAsDefault correspond to off, all programs and
  Eco 50 on the observed appliance.

The new configuration entities are disabled by default and only created when
the appliance exposes the relevant settings. Availability/access changes remain
handled by the existing entity implementation.

Auto start through `start_program_with_options` was verified locally. Use only
options supported by the selected program; SilenceOnDemand was not selectable
before starting this appliance's cycle. RemoteStartAllowed must be checked;
remote-start policy and physical-button arming are separate concepts.

OpenDry opened the door about 15 minutes before program completion during a real
Auto cycle. Door opening must not be used as a completion signal. Use operation
state, ProgramFinished or the existing latest-session summary sensors. Energy
and water forecast percentages are relative indices, not measured kWh or litres.
