"""
Acceptance test — the universal-first claim.

The Adaptive Feedback Loop spec states:

    "A brand-new lamina must inherit the adaptive feedback loop with NO
     additional adaptation code — only math + config.  If implementing the
     loop requires touching domain math, the mechanism has leaked into the
     wrong layer."

So this test builds a lamina from a *different domain* (thermal regulation
of a tank — nothing cardiovascular about it).  Its child class registers
exactly one thing: the domain physics.  It contains ZERO adaptation code.
We then run the standard FeedbackController and assert the slow loop
learns — gain adapts, the operating point consolidates, performance stays
finite, nothing diverges.

If this passes, the adaptive mechanism genuinely lives in the universal
layer: a new lamina gets it for free from math + XML config alone.
"""

import math

import pytest

from universal_twin import UniversalTwin
from feedback_controller import FeedbackController


# ── A toy lamina from an unrelated domain ────────────────────────────
#
# Physics: tank temperature = ambient + heater_power / loss_coeff.
# With heater=300, loss_coeff=10 → temp = 20 + 30 = 50 °C, which sits
# below the 60 °C operating target, so there is a real deviation for the
# loop to work on.  The feedback corrects the PRELIMINARY `temp`; the two
# sensors are sacred (D12).

THERMAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<lamina name="Thermal" id="lamina_thermal" level="1">

  <coupling type="additive" />
  <behaviour_solver type="algebraic_chain" dt="1.0" unit="second" />

  <!-- Config only — no algorithm.  A new lamina opts into the loop by
       copying a block like this. -->
  <adaptation kernel="model_free" cadence="5">
    <param name="gain_rate"   value="0.03" />
    <param name="gain_min"    value="0.20" />
    <param name="gain_max"    value="1.50" />
    <param name="op_rate"     value="0.15" />
    <param name="op_min"      value="-0.40" />
    <param name="op_max"      value="0.40" />
    <param name="settle_band" value="0.60" />
  </adaptation>

  <attributes>
    <attribute id="heater">
      <n>Heater Power</n><unit>W</unit><source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>2000</physio_max>
    </attribute>
    <attribute id="loss_coeff">
      <n>Loss Coefficient</n><unit>W/K</unit><source>SENSOR</source>
      <physio_min>1</physio_min><physio_max>50</physio_max>
    </attribute>
    <attribute id="temp">
      <n>Tank Temperature</n><unit>degC</unit><source>PRELIMINARY</source>
      <physio_min>0</physio_min><physio_max>100</physio_max>
      <computed_by>thermal_balance</computed_by>
      <depends_on>heater, loss_coeff</depends_on>
    </attribute>
  </attributes>

  <functions>
    <function id="thermal_balance" step="1">
      <n>Thermal Balance</n>
      <formula>temp = 20 + heater / loss_coeff</formula>
      <inputs>heater, loss_coeff</inputs>
      <o>temp</o>
    </function>
  </functions>

  <composites>
    <composite id="thermal_state">
      <n>Thermal State</n>
      <attributes>temp</attributes>
    </composite>
  </composites>

  <segments>
    <segment id="seg_thermal" name="Thermal">
      <attributes>heater, loss_coeff, temp</attributes>
      <composites>thermal_state</composites>
      <functions>thermal_balance</functions>
      <behavioural_outcomes>
        <outcome id="target_temp" name="Target Temperature"
                 attribute="temp" target="60" tolerance="5" unit="degC"/>
      </behavioural_outcomes>
    </segment>
  </segments>

  <tags>
    <tag id="TEMP_DEVIATION" outcome="target_temp"
         gate_kernel="sigmoid_leaky_tanh" polarity="negative">
      <targets>
        <target address="thermal_state" weight="1.0"/>
      </targets>
      <params gain="0.6" decay="0.10" threshold_k="4.0" saturation="0.3"/>
    </tag>
  </tags>

</lamina>
"""


class ThermalLamina(UniversalTwin):
    """
    Child class for the toy thermal domain.

    It registers ONE thing — the domain physics.  There is deliberately no
    adaptation, slow-loop, kernel, or meta-state code here: all of that is
    inherited from UniversalTwin.  That absence is the whole point of the
    acceptance test.
    """

    def _register_functions(self):
        self._function_registry["thermal_balance"] = self._thermal_balance

    @staticmethod
    def _thermal_balance(inputs):
        heater, loss_coeff = inputs
        return 20.0 + heater / loss_coeff


@pytest.fixture
def thermal(tmp_path):
    xml = tmp_path / "thermal_lamina.xml"
    xml.write_text(THERMAL_XML, encoding="utf-8")
    t = ThermalLamina(str(xml))
    t.set_sensor("heater", 300)       # → temp 50 °C, below the 60 °C target
    t.set_sensor("loss_coeff", 10)
    t.compute_all()
    return t


# ── The acceptance assertions ────────────────────────────────────────

def test_child_class_contains_no_adaptation_code():
    """Structural proof: the lamina defines only domain math."""
    own = {
        name for name in vars(ThermalLamina)
        if not name.startswith("__")
    }
    assert own == {"_register_functions", "_thermal_balance"}


def test_new_lamina_inherits_the_loop_config(thermal):
    """Math + config alone wired the slow loop on, with the XML numbers."""
    assert thermal.slow_loop_cadence == 5
    assert thermal.adaptation_kernel_type == "model_free"
    assert thermal.adaptation_params["gain_max"] == 1.50
    # The universal mechanism is present though the child added none of it.
    assert "model_free" in thermal._adaptation_kernel_registry


def test_new_lamina_adapts_with_zero_adaptation_code(thermal):
    """Run the standard controller; the inherited slow loop must learn."""
    fc = FeedbackController(thermal)
    assert fc.adaptive_enabled                  # opted in from XML alone

    reports = fc.run(40)                         # 8 slow-loop ticks at cadence 5

    assert not any(r["diverged"] for r in reports)

    ms = thermal.get_meta_state("target_temp")
    assert ms is not None
    assert ms.gain is not None                  # gain was learned
    assert ms.updates >= 1                       # slow loop ran
    assert ms.perf_ewma is not None and math.isfinite(ms.perf_ewma)
    # Gain stayed inside the XML-declared safe bounds.
    assert (thermal.adaptation_params["gain_min"]
            <= ms.gain <= thermal.adaptation_params["gain_max"])
    # At least one slow-loop tick reported adaptation telemetry.
    assert any(r["adaptation"] for r in reports)


def test_inherited_loop_drives_temp_toward_target(thermal):
    """End-to-end sanity: the corrected temperature moves from 50 toward
    the 60 °C target (the fast loop the slow loop tunes actually works)."""
    fc = FeedbackController(thermal)
    start = thermal.get("temp").value           # ~50
    fc.run(40)
    end = thermal.get("temp").value
    assert end > start                           # pushed upward
    assert abs(end - 60.0) < abs(start - 60.0)   # and closer to target


def test_meta_state_persists_across_fast_resets(thermal):
    """The learned thermal meta-state survives the dead-zone snap path,
    exactly as in the circulatory lamina — the persistence is universal."""
    fc = FeedbackController(thermal)
    fc.run(20)
    learned = thermal.get_meta_state("target_temp").gain
    assert learned is not None
    fc.reset_kernel_state()                      # wipe transient fast-loop state
    assert thermal.get_meta_state("target_temp").gain == learned
