# Examples

`public_spatial_topology_01.twingraph.json` demonstrates the optional spatial
profile with an observed site frame, entity footprints and spatial ports, a
reserved corridor, and a proposed route. Compile it with a type registry that
includes `SPATIAL_TYPE_PACK`.

Spatial clearance validation is intentionally conservative: entity-placement
axis-aligned bounding boxes are compared only when they share the same frame.
Parent-frame transforms are not composed, and port clearance envelopes are
shape/reference checked but are not included in overlap detection. Frame
distance units currently include metres, kilometres, and feet; angles use
degrees so canonicalization never discards a non-identity angular scale.

This directory contains small illustrative TwinGraph documents for public tests
and documentation.

- `ny_demo_bess_01.twingraph.json`: a draft battery storage decision twin with
  a market node, interconnect, leakage-aware price binding, model reference,
  controls, constraints, objective, validators, and evidence.
- `public_physical_bess_01.twingraph.json`: a synthetic, public physical BESS
  end-to-end decision twin: physical layout, telemetry/market availability
  controls, external health/thermal model, available-power calibration,
  dispatch, advisory gate, shadow evaluation, and operator explanation.
- `public_physical_bess_01.md`: the walkthrough for that showcase, including
  the end-to-end flow and how to render the same TwinGraph as a line diagram.

The examples are synthetic. They do not contain customer data, private market
data, credentials, production model outputs, or as-built plant claims.
