# Architecture Refactor — BDT Foundation

**Status:** Planned
**Triggered by:** Code review feedback (2026-03-26)
**Scope:** XML schema redesign + ingestion layer + code decoupling

---

## Overview

This document tracks the architectural changes required to evolve CardioTwin from a single-lamina cardiovascular simulator into a foundation for a full **Biological Digital Twin (BDT)**. No frontend changes are required at this stage — all changes are in the XML schema, new config files, and the Python engine.

---

## Change 1 — Lamina XML Schema Extensions

**File:** `backend/circulatory_lamina.xml`

### 1a. Lamina-level metadata

Add `level`, `upper_lamina`, and `lower_lamina` attributes to the root `<lamina>` element. This builds the hierarchy for future inter-lamina propagation.

**Before:**
```xml
<lamina name="Circulatory" version="1.0">
```

**After:**
```xml
<lamina name="Circulatory" id="lamina_circulatory" version="2.0" level="1">
  <upper_lamina id="none" />
  <lower_lamina id="none" />
  ...
</lamina>
```

- `level` — integer depth in the BDT hierarchy (1 = top)
- `upper_lamina` / `lower_lamina` — IDs of adjacent laminas (set to `none` until inter-lamina propagation is built)

---

### 1b. Segments

Each lamina can contain one or more **segments** — named sub-sections that group related attributes, composites, functions, and behavioural outcomes.

**New section added inside `<lamina>`:**
```xml
<segments>

  <segment name="Arterial" id="seg_arterial">
    <description>Systemic arterial circulation subsystem</description>
    <attributes>SBP, DBP, MAP, R, Q</attributes>
    <composites>pressure_state, vessel_state, flow_state</composites>
    <functions>pressure_regulation, vascular_resistance, hemodynamic_flow</functions>
    <!-- absorption_vector: PENDING coworker definition -->
    <!-- behavioural_outcomes: PENDING coworker definition -->
  </segment>

  <segment name="Cardiac" id="seg_cardiac">
    <description>Cardiac pump subsystem</description>
    <attributes>EDV, HR, SV, CO</attributes>
    <composites>pump_state</composites>
    <functions>cardiac_filling, cardiac_pump</functions>
    <!-- absorption_vector: PENDING coworker definition -->
    <!-- behavioural_outcomes: PENDING coworker definition -->
  </segment>

  <segment name="Conduction" id="seg_conduction">
    <description>Electrical conduction subsystem</description>
    <attributes>r_m, r_i, r_e, lambda</attributes>
    <composites>conduction_state</composites>
    <functions>electrical_conduction</functions>
    <!-- absorption_vector: PENDING coworker definition -->
    <!-- behavioural_outcomes: PENDING coworker definition -->
  </segment>

</segments>
```

**Note:** `absorption_vector` and `behavioural_outcomes` fields are included as comments — awaiting definition from the team before formalising the schema.

---

### 1c. Absorption Vector on Composites

Add an `<absorption_vector>` placeholder to each composite.

**Before:**
```xml
<composite id="pressure_state">
  <name>Pressure State</name>
  <attributes>SBP, DBP, MAP</attributes>
  <description>Represents the lamina's pressure condition</description>
</composite>
```

**After:**
```xml
<composite id="pressure_state">
  <name>Pressure State</name>
  <attributes>SBP, DBP, MAP</attributes>
  <description>Represents the lamina's pressure condition</description>
  <!-- absorption_vector: PENDING coworker definition -->
</composite>
```

---

### 1d. Channel Mapping Reference

Each lamina references which ingestion channels supply its sensor attributes, via `channel_id` links.

**New section added to `<lamina>`:**
```xml
<channel_mappings>
  <mapping attribute_id="SBP"  channel_id="ch_manual_slider" />
  <mapping attribute_id="DBP"  channel_id="ch_manual_slider" />
  <mapping attribute_id="HR"   channel_id="ch_apple_watch_api" />
  <mapping attribute_id="eta"  channel_id="ch_manual_slider" />
  <mapping attribute_id="L"    channel_id="ch_manual_slider" />
  <mapping attribute_id="r"    channel_id="ch_manual_slider" />
  <mapping attribute_id="EDV"  channel_id="ch_manual_slider" />
  <mapping attribute_id="r_m"  channel_id="ch_manual_slider" />
  <mapping attribute_id="r_i"  channel_id="ch_manual_slider" />
  <mapping attribute_id="r_e"  channel_id="ch_manual_slider" />
</channel_mappings>
```

Channel IDs refer to entries in `ingestion_manifold.xml` (see Change 2).

---

## Change 2 — Ingestion Manifold (New File)

**File:** `backend/ingestion_manifold.xml` *(new)*

A separate, BDT-wide file that defines all data channels. Laminas reference channels by ID — they do not embed source configuration. This makes it possible to swap a manual slider for a live API without modifying the lamina XML.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!--
  Ingestion Manifold — BDT-wide channel definitions
  Each channel is a data source. Laminas reference channels by ID.
  This file is shared across all laminas in the BDT.
-->

<ingestion_manifold version="1.0">

  <!-- ============================================================ -->
  <!-- MANUAL INPUT CHANNELS                                        -->
  <!-- ============================================================ -->
  <channel id="ch_manual_slider" type="manual">
    <name>Manual Slider UI</name>
    <description>Values entered by the user via browser sliders</description>
  </channel>

  <!-- ============================================================ -->
  <!-- REST API CHANNELS                                            -->
  <!-- ============================================================ -->
  <channel id="ch_apple_watch_api" type="rest_api">
    <name>Apple Watch HealthKit API</name>
    <description>Heart rate and activity data from Apple HealthKit</description>
    <url>https://api.health.apple.com/v1/metrics</url>
    <!-- API key stored in environment variable — never hardcoded -->
    <api_key_env>APPLE_HEALTH_API_KEY</api_key_env>
    <polling_interval_seconds>30</polling_interval_seconds>
    <response_mapping>
      <field json_path="$.heartRate" maps_to="HR" />
    </response_mapping>
  </channel>

  <!-- ============================================================ -->
  <!-- SDK CHANNELS                                                 -->
  <!-- ============================================================ -->
  <channel id="ch_wearable_sdk" type="sdk">
    <name>Generic Wearable SDK</name>
    <description>Placeholder for wearable device SDK integration</description>
    <sdk_module>wearable_sdk</sdk_module>
    <sdk_class>WearableClient</sdk_class>
    <!-- PENDING: SDK-specific configuration to be added when SDK is selected -->
  </channel>

</ingestion_manifold>
```

**Key design decisions:**
- API keys are **never hardcoded** — stored in environment variables referenced by name
- Each channel is self-describing (type, source, polling config)
- Adding a new data source = adding a new `<channel>` block, zero lamina changes required

---

## Change 3 — Code Decoupling

**Files:** `backend/universal_twin.py`, `backend/circulatory_lamina.py`

### Problem

Currently `circulatory_lamina.py` functions reference hardcoded attribute names:

```python
# CURRENT — tightly coupled to cardiovascular domain
def pressure_regulation(self):
    sbp = self.attributes['SBP'].value
    dbp = self.attributes['DBP'].value
    return (1/3) * sbp + (2/3) * dbp
```

If the lamina schema changes, or a new lamina is built, every function must be manually updated.

### Solution

The base class (`universal_twin.py`) reads the `<inputs>` list from each `<function>` definition in the XML, resolves the current attribute values, and passes them as a **generic ordered dictionary** to each function. Functions reference inputs by position or key — not by hardcoded attribute name.

**New function signature convention:**
```python
# NEW — decoupled, generic
def pressure_regulation(self, inputs: dict):
    # inputs keys come from XML <inputs> definition: ["SBP", "DBP"]
    # Access by XML-defined key, not hardcoded string in logic
    sbp = inputs[0]   # positional: order matches XML <inputs> list
    dbp = inputs[1]
    return (1/3) * sbp + (2/3) * dbp
```

**Base class resolver (universal_twin.py):**
```python
def _resolve_inputs(self, function_id: str) -> list:
    """Read <inputs> from XML for a given function, resolve current values."""
    input_ids = self.schema['functions'][function_id]['inputs']  # from XML
    return [self.attributes[attr_id].value for attr_id in input_ids]

def _dispatch_function(self, function_id: str):
    inputs = self._resolve_inputs(function_id)
    method = getattr(self, function_id)
    return method(inputs)
```

**Benefits:**
- `circulatory_lamina.py` functions contain only physics — no attribute name coupling
- A new lamina (e.g. `respiratory_lamina.py`) follows the same contract without changes to the base class
- Renaming an attribute in the XML is the only change required — no Python edits

---

## Implementation Order

| Step | Task | File(s) | Status |
|------|------|---------|--------|
| 1 | Add `level`, `upper_lamina`, `lower_lamina` to lamina root | `circulatory_lamina.xml` | DONE |
| 2 | Add `<segments>` section with 3 segments | `circulatory_lamina.xml` | DONE |
| 3 | Add absorption vector placeholders to composites | `circulatory_lamina.xml` | DONE |
| 4 | Add `<channel_mappings>` section to lamina | `circulatory_lamina.xml` | DONE |
| 5 | Create ingestion manifold file | `ingestion_manifold.xml` (new) | DONE |
| 6 | Refactor base class to generic input resolver | `universal_twin.py` | DONE |
| 7 | Refactor child class functions to use generic inputs | `circulatory_lamina.py` | DONE |
| 8 | Update `xml_converter.py` to parse new schema sections | `xml_converter.py` | DONE |
| 9 | Update `main.py` `/api/schema` to expose segments + channels | `main.py` | DONE |

---

## Open Questions (Pending Coworker Clarification)

| # | Question | Blocking |
|---|----------|---------|
| 1 | **Absorption vector** — what does it contain and what does it point to? | Steps 2, 3 |
| 2 | **Behavioural outcomes** — what structure? Risk flags, thresholds, clinical classifications? | Step 2 |

These are implemented as XML comments (placeholders) until answered.

---

## What Is NOT Changing

- Frontend components — no changes required at this stage
- Gate definitions — revision deferred per coworker note (inter-lamina propagation phase)
- API endpoint contracts — `/api/compute`, `/api/schema`, `/api/upload` signatures unchanged
- Preset XML files — will be updated in a separate pass after schema is finalised
