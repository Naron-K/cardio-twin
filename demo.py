"""
Cardiac Digital Twin - Demo
============================
Demonstrates the full architecture:
  1. XML defines attributes and mappings
  2. UniversalTwin (parent) reads XML and resolves dependencies
  3. CirculatoryLamina (child) provides actual computations
  4. Domain expert interacts via set_sensor() and get()

Run: python demo.py
"""

import sys
from pathlib import Path

# Add backend to path so we can import modules
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from circulatory_lamina import CirculatoryLamina


def main():
    # ── Create the twin from XML definition ──────────────────────────
    print("\n" + "="*60)
    print("  CARDIAC DIGITAL TWIN - DEMO")
    print("="*60)

    twin = CirculatoryLamina("backend/circulatory_lamina.xml")

    # ── Show what the XML defines ────────────────────────────────────
    print("\n📋 Functions defined in XML:")
    for f in twin.list_functions():
        print(f"  {f}")

    print("\n📋 Sensor attributes (inputs from devices):")
    for attr_id in twin.list_attributes("SENSOR"):
        print(f"  {attr_id}: {twin.attributes[attr_id].name}")

    print("\n📋 Preliminary attributes (computed internally):")
    for attr_id in twin.list_attributes("PRELIMINARY"):
        attr = twin.attributes[attr_id]
        print(f"  {attr_id}: {attr.name} (depends on: {', '.join(attr.depends_on)})")

    # ── Scenario 1: Normal patient ───────────────────────────────────
    print("\n" + "="*60)
    print("  SCENARIO 1: Normal Patient at Rest")
    print("="*60 + "\n")

    twin.set_sensor("SBP", 120)
    twin.set_sensor("DBP", 80)
    twin.set_sensor("HR", 72)
    twin.set_sensor("eta", 3.5)     # normal viscosity mPa·s
    twin.set_sensor("L", 50)        # effective total vessel length cm
    twin.set_sensor("r", 0.15)      # effective average radius cm
    twin.set_sensor("EDV", 120)     # normal filling volume
    twin.set_sensor("r_m", 5000)    # membrane resistance
    twin.set_sensor("r_i", 200)     # intracellular resistance
    twin.set_sensor("r_e", 300)     # extracellular resistance

    print("\n⚙️  Computing all steps...")
    twin.compute_all()

    print(twin.summary())

    # ── Show attribute resolution ────────────────────────────────────
    print("\n🔍 Resolving Q (Blood Flow) - trace:")
    print(twin.describe_attribute("Q"))

    # ── Show composite vectors ───────────────────────────────────────
    print("\n📊 Composite Vectors (normalised [0,1]):")
    for comp_id, vector in twin.get_all_vectors().items():
        comp = twin.composites[comp_id]
        print(f"\n  {comp.name}:")
        for attr_id, val in vector.items():
            if val is not None:
                bar = "█" * int(val * 20) + "░" * (20 - int(val * 20))
                print(f"    {attr_id:>8}: {bar} {val:.3f}")

    # ── Scenario 2: Hypertension + vasoconstriction ──────────────────
    print("\n" + "="*60)
    print("  SCENARIO 2: Hypertension + Vasoconstriction")
    print("="*60 + "\n")

    twin2 = CirculatoryLamina("backend/circulatory_lamina.xml")
    twin2.set_sensor("SBP", 160)     # high
    twin2.set_sensor("DBP", 100)     # high
    twin2.set_sensor("HR", 85)       # elevated
    twin2.set_sensor("eta", 3.8)     # slightly thicker
    twin2.set_sensor("L", 20)
    twin2.set_sensor("r", 0.3)       # narrowed (vasoconstriction)
    twin2.set_sensor("EDV", 130)
    twin2.set_sensor("r_m", 5000)
    twin2.set_sensor("r_i", 200)
    twin2.set_sensor("r_e", 300)

    print("⚙️  Computing...")
    twin2.compute_all()
    print(twin2.summary())

    # ── Scenario 3: Heart failure patient ────────────────────────────
    print("\n" + "="*60)
    print("  SCENARIO 3: Heart Failure Patient")
    print("="*60 + "\n")

    twin3 = CirculatoryLamina("backend/circulatory_lamina.xml")
    twin3.set_patient_profile("heart_failure")  # Adjust Starling parameters

    twin3.set_sensor("SBP", 100)     # low
    twin3.set_sensor("DBP", 65)      # low
    twin3.set_sensor("HR", 95)       # compensatory tachycardia
    twin3.set_sensor("eta", 3.5)
    twin3.set_sensor("L", 20)
    twin3.set_sensor("r", 0.35)
    twin3.set_sensor("EDV", 180)     # high filling but weak pump
    twin3.set_sensor("r_m", 3000)    # lower membrane resistance
    twin3.set_sensor("r_i", 250)
    twin3.set_sensor("r_e", 350)

    print("⚙️  Computing...")
    twin3.compute_all()
    print(twin3.summary())

    # ── Show domain expert customisation ─────────────────────────────
    print("\n" + "="*60)
    print("  DOMAIN EXPERT CUSTOMISATION")
    print("="*60)

    print("""
  How domain experts can modify the model:

  1. ADJUST GATE THRESHOLDS (in XML or via code):
     twin.modify_gate_threshold("MAP", new_min=65, new_max=105)

  2. ADD NEW ATTRIBUTES (extends XML automatically):
     twin.add_attribute_to_xml(
         attr_id="PP",
         name="Pulse Pressure",
         unit="mmHg",
         source="PRELIMINARY",
         physio_min=20, physio_max=100,
         computed_by="pulse_pressure",
         depends_on="SBP, DBP"
     )
     → Then developer adds _calc_pulse_pressure() to child class

  3. CHANGE PATIENT PROFILE:
     twin.set_patient_profile("heart_failure")
     twin.set_patient_profile("athletic")

  4. EDIT XML DIRECTLY:
     → Add/remove attributes in <attributes> section
     → Add/remove functions in <functions> section
     → Adjust gates in <gates> section
     → No Python code changes needed for data model changes

  5. INTER-LAMINA (future):
     → Another lamina (e.g. MetabolicLamina) can read this lamina's
       Behaviour Outcome (Q) and Composite Vectors through gates
     → Communication only via normalised vector space
    """)


if __name__ == "__main__":
    main()
