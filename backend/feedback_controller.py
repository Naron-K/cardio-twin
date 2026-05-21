"""
FeedbackController — Phase C of the Feedback Loop rollout
==========================================================
Orchestrates the universal feedback cycle defined in
FEEDBACK_LOOP_PLAN.md §5.0:

    1. Compute deviation per outcome
    2. Emit tags (poll, D9)
    3. Run gate kernel per (tag, attr_in_target_composite)
    4. Sum deltas across tags per attribute (D10)
    5. Apply X'' to every targeted attribute (D11)
    6. Dead-zone snap, reset kernel state (D3 + D4)
    7. compute_all() exactly ONCE (D11)

Kernel state lives HERE (not on Attribute / Tag) keyed by
(tag_id, attribute_id) per D4.  Apply-then-recompute-once ordering is
deterministic per D11.  All addresses resolve through
UniversalTwin.resolve_tag_address() so D5 catches ambiguity at parse
time, not in the hot path.

Phase C is the highest-risk phase per the plan — sign convention and
decay rate are easy to get wrong, so the soft circuit breaker (D16) is
included here (a copy lands in the API layer in Phase D).
"""

from __future__ import annotations

from typing import Any, Optional

from universal_twin import (
    UniversalTwin,
    Identifier,
    Metrix,
    Tag,
    TagTarget,
)


# Framework-wide default for the dead-zone snap (D3): epsilon is a
# RELATIVE fraction of each attribute's physio range, so the snap
# threshold makes sense for mmHg, L/min, mL, ohm·cm alike without
# per-attribute calibration.  Per-tag override happens through
# params["epsilon_ratio"].
DEFAULT_EPSILON_RATIO = 0.001

# Soft circuit breaker (D16) — feedback_norm above this means something
# in the loop has gone divergent.  Default chosen well above any
# reasonable settled state (≤ 0.3 per attribute by construction of the
# tanh saturation at 0.3 × physio_range) but below what would indicate
# a true sign-convention bug.
DEFAULT_MAX_NORM = 10.0


class FeedbackController:
    """
    Owns per-tag kernel memory and drives the 7-step cycle (§5.0, D18).

    Stateless from the domain object's point of view — Attribute and
    Tag carry no dynamic state.  The controller is the only thing that
    needs persisting if a session is paused and resumed.
    """

    def __init__(self, twin: UniversalTwin,
                 epsilon_ratio: float = DEFAULT_EPSILON_RATIO,
                 max_norm: float = DEFAULT_MAX_NORM):
        self.twin = twin

        # Phase A invariant: feedback math is verified with X' = 0
        # after the initial set.  We don't enforce it here yet — the
        # controller still works if sensors keep streaming — but a
        # comment marker makes the v1 boundary visible.
        self.epsilon_ratio = float(epsilon_ratio)
        self.max_norm = float(max_norm)

        # State storage (D4): key = (tag_id, attr_id), value = kernel
        # state dict (whatever shape the kernel returns).  Persisted
        # across cycles; reset only by the snap dead-zone or an
        # explicit reset_kernel_state() call.
        self._kernel_state: dict[tuple[str, str], dict] = {}

        # Cycle counter — survives across step() calls so logs can be
        # correlated.  Reset by reset_kernel_state().
        self.cycle: int = 0

    # ── State management ─────────────────────────────────────────────

    def reset_kernel_state(self):
        """
        Wipe all kernel state and the cycle counter.

        Also zeros every attribute's value_feedback through the public
        Attribute API (rollback_feedback) — keeps the two stores in
        sync after a manual reset, mirroring the snap path (D4).
        """
        self._kernel_state.clear()
        self.cycle = 0
        for attr in self.twin.attributes.values():
            attr.rollback_feedback()

    def get_state(self, tag_id: str, attr_id: str) -> dict:
        """Return the live state dict for (tag, attr) — empty if absent."""
        return self._kernel_state.get((tag_id, attr_id), {})

    # ── Helpers ──────────────────────────────────────────────────────

    def _resolved_targets(self, tag: Tag) -> list[tuple[str, float]]:
        """
        Expand a tag's targets to a list of local composite ids.

        Cross-lamina prefixes are accepted but currently only act
        within this lamina (Phase G adds the cross-lamina dispatcher);
        prefixes for OTHER laminas are silently dropped with a log.

        Returns list of (composite_id, target_weight).  Local-first
        per D5 — resolve_tag_address() already validated at parse time.
        """
        out: list[tuple[str, float]] = []
        for tgt in tag.targets:
            lam, comp = self.twin.resolve_tag_address(
                tgt.address, tag_id=tag.id
            )
            if lam is not None and lam != self.twin.lamina_id:
                self.twin._log(
                    f"FB: skipping cross-lamina target {tgt.address} "
                    f"for tag {tag.id} (Phase G feature)."
                )
                continue
            out.append((comp, tgt.weight))
        return out

    def _build_kernel_params(self, tag: Tag, outcome_id: str,
                              attr_id: str, target_weight: float) -> dict:
        """
        Assemble the params dict the gate kernel will read.

        Resolution order (most specific wins, D15 / loose params):
            framework defaults  ←  tag.params  ←  controller overrides

        Controller overrides inject the runtime context the kernel
        cannot infer on its own:
          - polarity (from Tag, D7)
          - tolerance (from the BehaviouralOutcome — kernel multiplies
            it back in to restore native units, §2.3)
          - a_max (saturation × attribute's physio range; §2.3 default
            is "0.3 × physio range").  If the tag stored `saturation`
            as a raw multiplier > 1, that bypasses the fractional
            interpretation — the kernel uses whichever is present.
        """
        params = Metrix.lookup(tag)
        params["polarity"] = tag.polarity

        tol = Identifier._tolerance_for_outcome(self.twin, outcome_id)
        if tol > 0:
            params["tolerance"] = tol

        # Resolve a_max from saturation × physio_range when saturation
        # looks like a fractional knob (between 0 and 1).  Otherwise
        # treat saturation as the raw a_max — preserves demo behaviour.
        sat = params.get("saturation", 1.0)
        attr = self.twin.attributes.get(attr_id)
        if attr is not None:
            range_size = attr.physio_max - attr.physio_min
            if range_size > 0 and 0 < float(sat) <= 1.0:
                params["a_max"] = float(sat) * range_size
            else:
                params["a_max"] = float(sat)

        # target_weight has already been consumed at the outer loop
        # (full deviation × target_weight per D8) — passed through
        # for kernels that want to log it.
        params["_target_weight"] = float(target_weight)
        return params

    def _attr_epsilon(self, attr_id: str) -> float:
        """
        Per-attribute snap threshold (D3).

        Uses the controller's epsilon_ratio (a framework default) times
        the attribute's physio range.  Per-tag overrides via
        params["epsilon_ratio"] are NOT applied at the attribute level
        here — when multiple tags target the same attribute their
        ratios would conflict.  The Phase C convention is "framework
        owns the snap"; future work can take the minimum across tags
        if a use case appears.
        """
        attr = self.twin.attributes.get(attr_id)
        if attr is None:
            return 0.0
        range_size = attr.physio_max - attr.physio_min
        if range_size <= 0:
            return 0.0
        return self.epsilon_ratio * range_size

    # ── The 7-step cycle (D18) ───────────────────────────────────────

    def step(self) -> dict:
        """
        Run one full feedback cycle.

        Returns a structured report with everything the API layer
        (Phase D) and frontend (Phase F) need:

            {
              "cycle":           int,
              "tags_emitted":    list[str],     # tag ids that fired
              "deltas_per_attr": dict[str, float],   # signed X'' applied per attr
              "feedback_norm":   float,          # post-snap (D13)
              "diverged":        bool,           # circuit breaker (D16)
              "snapped":         list[str],      # attrs cleaned to 0 this cycle
              "warnings":        list[str],
            }
        """
        warnings: list[str] = []
        self.cycle += 1
        self.twin._log(f"FB cycle {self.cycle} START")

        # ─── Step 1: deviations per outcome ────────────────────────
        outcome_evaluations = self.twin.evaluate_all_outcomes()

        # ─── Step 2: emit tags (D9 poll) ───────────────────────────
        # `emissions` is informational — it reports which tags crossed
        # the emitter's binary threshold this cycle.  Kernel execution
        # in step 3 is INDEPENDENT of this list because the kernel's
        # sigmoid G(d) already filters in-tolerance noise (D9), AND
        # tags with active state need to keep decaying their X'' even
        # in cycles when they don't re-emit.  Without this, X'' would
        # freeze at its last value the moment the outcome re-entered
        # tolerance, violating the §5 GĐ E requirement that "X'' → 0
        # in 5 consecutive cycles" after convergence.
        emissions = Identifier.emit_tags(self.twin, outcome_evaluations)
        tags_emitted = [e["tag"].id for e in emissions]

        # Index emissions by tag id so step 3 can look up the actual
        # normalised deviation for tags that are currently above their
        # binary emitter threshold.
        emitted_by_id = {e["tag"].id: e for e in emissions}

        # Flat dict for fast outcome lookup by id (mirrors Identifier
        # internals — kept local to avoid coupling to its private
        # helper).
        outcome_by_id: dict[str, dict] = {}
        for seg_outcomes in outcome_evaluations.values():
            for fb in seg_outcomes:
                outcome_by_id[fb["outcome_id"]] = fb

        # ─── Step 3: run gate kernel per (tag, target_attr) ────────
        # Iterate over EVERY configured tag with non-zero polarity.
        # When the tag is currently emitting, use its normalised
        # deviation; when it's in-tolerance, pass the sub-tolerance
        # normalised deviation so the sigmoid G(d) damps `raw` while
        # the leaky integrator (1-λ)·x_pp_prev decays existing state.
        #
        # Tags with no kernel state AND no emission are still allowed
        # to run — `raw` is tiny via G(d) ≈ 0 inside tolerance, and
        # the dead-zone snap (step 6) will reset any noise created.
        # Cost is O(tags × attrs_per_composite) per cycle, all cheap.
        new_x_pp: dict[tuple[str, str], float] = {}

        for tag in self.twin.tags.values():
            kernel_name = tag.gate_kernel
            kernel_fn = self.twin._gate_kernel_registry.get(kernel_name)
            if kernel_fn is None:
                warnings.append(
                    f"Unknown gate_kernel '{kernel_name}' for tag '{tag.id}' — skipped."
                )
                continue

            # Monitor-only (polarity == 0) — log on emit but never
            # generate X''.  Skipping the kernel here is also correct
            # because monitor-only tags should not accumulate state.
            if tag.polarity == 0.0:
                if tag.id in emitted_by_id:
                    em = emitted_by_id[tag.id]
                    self.twin._log(
                        f"FB: tag {tag.id} monitor-only (polarity=0) — "
                        f"dev_norm={em['deviation_norm']:.3f} not applied."
                    )
                continue

            # Resolve the current normalised deviation for this tag's
            # outcome — works whether emitter fired or not.
            fb = outcome_by_id.get(tag.outcome)
            if fb is None:
                continue  # outcome not present this cycle
            tolerance = Identifier._tolerance_for_outcome(
                self.twin, tag.outcome
            )
            if tolerance <= 0:
                warnings.append(
                    f"Tag '{tag.id}' has zero-tolerance outcome — skipped."
                )
                continue
            dev_fn = self.twin._deviation_registry.get(tag.deviation_type)
            if dev_fn is None:
                warnings.append(
                    f"Tag '{tag.id}' deviation_type '{tag.deviation_type}' "
                    "unknown — skipped."
                )
                continue
            raw_dev = dev_fn(fb["actual"], fb["target"], tag.params)
            d_norm = raw_dev / tolerance

            for comp_id, target_weight in self._resolved_targets(tag):
                comp = self.twin.composites.get(comp_id)
                if comp is None:
                    warnings.append(
                        f"Tag '{tag.id}' target '{comp_id}' not found — skipped."
                    )
                    continue

                for attr_id in comp.attribute_ids:
                    w_i = comp.get_distribution_weight(attr_id)
                    # D8: full deviation × target_weight per target.
                    weight = w_i * target_weight

                    params = self._build_kernel_params(
                        tag, tag.outcome, attr_id, target_weight
                    )
                    prev_state = self._kernel_state.get(
                        (tag.id, attr_id), {}
                    )

                    # Optimisation: if no prior state AND tag is not
                    # emitting this cycle, the kernel run is wasteful
                    # (G(d) → 0, raw → 0, output → 0).  Skip and let
                    # state stay empty.
                    if not prev_state and tag.id not in emitted_by_id:
                        continue

                    new_state = kernel_fn(prev_state, d_norm, weight, params)
                    self._kernel_state[(tag.id, attr_id)] = new_state
                    new_x_pp[(tag.id, attr_id)] = float(new_state.get("x_pp", 0.0))

        # ─── Step 4: sum deltas per attribute across tags (D10) ────
        delta_per_attr: dict[str, float] = {}
        for (tag_id, attr_id), x_pp in new_x_pp.items():
            delta_per_attr[attr_id] = delta_per_attr.get(attr_id, 0.0) + x_pp

        # Attributes that have stale kernel state but received no fresh
        # x_pp this cycle still contribute via decay carried inside the
        # kernel — we already stored the decayed state in step 3 above.
        # The sum here is over the CURRENT cycle's kernel outputs.

        # ─── Step 5: apply X'' to value_feedback (all attrs first, D11) ─
        # We replace value_feedback wholesale with the per-attribute
        # sum.  This is correct because each kernel state already
        # carries memory from prior cycles via its decay term — re-
        # adding old value_feedback would double-count.
        for attr_id, total in delta_per_attr.items():
            attr = self.twin.attributes.get(attr_id)
            if attr is not None:
                attr.apply_feedback(total)

        # ─── Step 6: dead-zone snap (D3 + D4) ──────────────────────
        # For each attribute whose value_feedback is below its
        # per-attribute epsilon, zero it AND wipe every kernel state
        # touching that attribute.  Keeps Attribute and controller
        # state from drifting.
        snapped: list[str] = []
        for attr_id, attr in self.twin.attributes.items():
            eps = self._attr_epsilon(attr_id)
            if eps > 0 and abs(attr.value_feedback) < eps and attr.value_feedback != 0.0:
                attr.rollback_feedback()
                snapped.append(attr_id)
                # Reset every kernel state keyed to this attribute.
                doomed = [
                    key for key in self._kernel_state
                    if key[1] == attr_id
                ]
                for key in doomed:
                    self._kernel_state[key] = {}

        # ─── Soft circuit breaker (D16, Phase C floor) ─────────────
        # Compute the norm BEFORE recompute so divergence in the
        # SENSOR layer is caught even if the chain would amplify.
        diverged = False
        norm_pre = self.twin.feedback_norm()
        if norm_pre > self.max_norm:
            warnings.append(
                f"CIRCUIT BREAKER: feedback_norm={norm_pre:.4f} > "
                f"max_norm={self.max_norm} after step {self.cycle}. "
                "Aborting cycle (sign convention may be inverted)."
            )
            diverged = True
            # Roll back this cycle's X'' on every attribute that just
            # received feedback.  Sensor X' is sacred (D12).
            for attr_id in delta_per_attr:
                attr = self.twin.attributes.get(attr_id)
                if attr is not None:
                    attr.rollback_feedback()
            # And wipe the kernel state so the next cycle starts fresh.
            self._kernel_state.clear()

        # ─── Step 7: compute_all() exactly ONCE (D11) ──────────────
        # Even on a diverged cycle we recompute so PRELIMINARY values
        # match the cleaned-up SENSOR layer.
        solver_name = self.twin.behaviour_solver_type
        solver_fn = self.twin._solver_registry.get(solver_name)
        if solver_fn is None:
            warnings.append(
                f"Unknown behaviour_solver '{solver_name}' — falling back to compute_all()."
            )
            self.twin.compute_all()
        else:
            solver_fn(self.twin, {})

        norm_post = self.twin.feedback_norm()

        report = {
            "cycle":           self.cycle,
            "tags_emitted":    tags_emitted,
            "deltas_per_attr": {k: round(v, 6) for k, v in delta_per_attr.items()},
            "feedback_norm":   round(norm_post, 6),
            "feedback_norm_pre_recompute": round(norm_pre, 6),
            "diverged":        diverged,
            "snapped":         snapped,
            "warnings":        warnings,
        }
        for w in warnings:
            self.twin._log(f"FB WARN: {w}")
        self.twin._log(
            f"FB cycle {self.cycle} END  norm={norm_post:.4f}  "
            f"emitted={len(tags_emitted)}  snapped={len(snapped)}"
        )
        return report

    # ── Convenience ──────────────────────────────────────────────────

    def run(self, n_cycles: int,
            settled_threshold: Optional[float] = None,
            settled_window: int = 5) -> list[dict]:
        """
        Drive `n_cycles` cycles, optionally stopping early when the
        feedback_norm stays under `settled_threshold` for
        `settled_window` consecutive cycles (D14 — Phase E preview).

        Stops immediately on circuit breaker.
        """
        reports: list[dict] = []
        below = 0
        for _ in range(n_cycles):
            report = self.step()
            reports.append(report)
            if report["diverged"]:
                break
            if settled_threshold is not None:
                if report["feedback_norm"] < settled_threshold:
                    below += 1
                    if below >= settled_window:
                        break
                else:
                    below = 0
        return reports
