"""
Feedback Kernel Interface Demo
==============================
Verify rằng 2 kernel với dynamics khác nhau hoàn toàn vẫn fit cùng 1 interface
→ chứng minh framework universal trước khi commit vào Giai đoạn C.

Hai kernel thí nghiệm:
  1. sigmoid_leaky_tanh   — continuous, scalar state, smooth dynamics
  2. refractory_threshold — discrete event, multi-field state (X'' + clock + last_fire)

Drive cả 2 bằng cùng 1 deviation signal, in trace + ASCII chart để so sánh.
"""

import math


# ─────────────────────────────────────────────────────────────────────────────
# KERNEL INTERFACE (contract chung cho mọi gate kernel)
# ─────────────────────────────────────────────────────────────────────────────
# kernel(prev_state: dict, deviation: float, weight: float, params: dict) -> dict
#
# prev_state: trạng thái kernel từ cycle trước. Bắt buộc có "x_pp" (giá trị X'').
#             Các field khác tùy kernel (clock, integral term, last_fire, ...).
# deviation:  ΔOV chuẩn hóa (đã chia tolerance) từ Identifier.
# weight:     trọng số absorption của attribute này trong composite.
# params:     loose dict — kernel tự .get() với default sensible.
#
# Returns:    new state dict (phải có "x_pp"; các field memory khác tùy kernel).
# ─────────────────────────────────────────────────────────────────────────────


def sigmoid_leaky_tanh(prev_state, deviation, weight, params):
    """
    Default kernel (continuous, scalar memory).
    State: {"x_pp": float}

    Math:
      G    = 1 / (1 + exp(-k·(|d| - 1)))
      raw  = -gain · w · G · d
      x_pp = A_max · tanh( ((1-λ)·x_pp_prev + raw) / A_max )
    """
    gain        = params.get("gain", 0.6)
    decay       = params.get("decay", 0.10)
    threshold_k = params.get("threshold_k", 4.0)
    a_max       = params.get("saturation", 1.0)

    x_pp_prev = prev_state.get("x_pp", 0.0)

    g_open = 1.0 / (1.0 + math.exp(-threshold_k * (abs(deviation) - 1.0)))
    raw    = -gain * weight * g_open * deviation
    inner  = (1.0 - decay) * x_pp_prev + raw
    x_pp   = a_max * math.tanh(inner / a_max)

    return {"x_pp": x_pp}


def refractory_threshold(prev_state, deviation, weight, params):
    """
    Neuron-like kernel (discrete event, multi-field memory).
    State: {"x_pp": float, "refractory_clock": int, "fired_this_cycle": bool}

    Behavior:
      - Nếu đang trong refractory period (clock > 0): không fire, decay clock.
      - Nếu |d| > threshold AND clock = 0: FIRE — bơm 1 phát impulse cố định.
      - Sau khi fire: set clock = refractory_period; X'' decay theo τ.
      - Giữa các fire: X'' giảm exponential.
    """
    threshold     = params.get("threshold", 1.0)       # |d| để fire
    impulse       = params.get("impulse", 0.5)         # biên độ mỗi phát
    refractory    = params.get("refractory_period", 5) # số cycle nghỉ
    tau           = params.get("tau", 8.0)             # decay time constant

    x_pp_prev = prev_state.get("x_pp", 0.0)
    clock     = prev_state.get("refractory_clock", 0)

    # Decay X'' exponential mỗi cycle (homeostasis)
    x_pp = x_pp_prev * math.exp(-1.0 / tau)

    fired = False
    if clock > 0:
        # Đang trong refractory period
        clock -= 1
    elif abs(deviation) > threshold:
        # Đủ điều kiện fire
        x_pp += -math.copysign(impulse, deviation) * weight
        clock = refractory
        fired = True

    return {
        "x_pp": x_pp,
        "refractory_clock": clock,
        "fired_this_cycle": fired,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DRIVER: chạy cả 2 kernel với cùng 1 deviation signal
# ─────────────────────────────────────────────────────────────────────────────

def deviation_signal(t):
    """
    Stress test:
      t=0-20:  d=+2.0 — perturbation lớn kéo dài (cả 2 kernel phải react)
      t=20-60: d=0    — settling phase (cả 2 phải về 0)
      t=60-80: d=+0.3 — nhiễu nhỏ trong tolerance (cả 2 phải IGNORE)
      t=80-100: d=0   — final settling
    """
    if t < 20:    return  2.0
    if t < 60:    return  0.0
    if t < 80:    return  0.3
    return 0.0


def run_kernel(kernel_fn, params, name, n_cycles=100, weight=1.0):
    state = {}
    trace = []
    for t in range(n_cycles):
        d = deviation_signal(t)
        state = kernel_fn(state, d, weight, params)
        trace.append({
            "t":     t,
            "d":     d,
            "x_pp":  state["x_pp"],
            "fired": state.get("fired_this_cycle", False),
        })
    return name, trace


# ─────────────────────────────────────────────────────────────────────────────
# OUTPUT: ASCII chart + summary metrics
# ─────────────────────────────────────────────────────────────────────────────

def ascii_chart(trace, title, width=60):
    """In line chart đơn giản của x_pp theo cycle."""
    vals = [row["x_pp"] for row in trace]
    vmin, vmax = min(vals), max(vals)
    span = (vmax - vmin) or 1.0

    print(f"\n  {title}")
    print(f"  range: [{vmin:+.3f}, {vmax:+.3f}]")
    print(f"  {'─' * width}")

    # Vẽ ngang (timeline)
    rows = 12
    for r in range(rows, 0, -1):
        line = "  "
        threshold = vmin + (r / rows) * span
        for row in trace:
            if row["x_pp"] >= threshold:
                line += "█"
            elif row.get("fired"):
                line += "│"  # đánh dấu fire event
            else:
                line += " "
        # In giá trị tham chiếu bên phải
        print(f"{line}  {threshold:+.3f}")

    print(f"  {'─' * width}")
    # Trục thời gian
    print(f"  {'0'.ljust(20)}{'cycles'.center(20)}{'100'.rjust(20)}")


def summary(trace, name):
    fires = sum(1 for r in trace if r.get("fired"))
    settled = abs(trace[-1]["x_pp"]) < 1e-3
    peak    = max(abs(r["x_pp"]) for r in trace)
    # Verify ignore noise window (cycles 60-80)
    noise_response = max(abs(r["x_pp"]) for r in trace[60:80])
    return {
        "kernel":          name,
        "fires":           fires,
        "peak |x_pp|":     round(peak, 4),
        "final x_pp":      round(trace[-1]["x_pp"], 6),
        "settled (≈0)":    settled,
        "noise window peak |x_pp|": round(noise_response, 4),
    }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 64)
    print("  FEEDBACK KERNEL INTERFACE DEMO")
    print("  Cùng interface, dynamics hoàn toàn khác → framework universal?")
    print("=" * 64)

    runs = [
        run_kernel(
            sigmoid_leaky_tanh,
            params={"gain": 0.6, "decay": 0.10, "threshold_k": 4.0, "saturation": 1.0},
            name="sigmoid_leaky_tanh",
        ),
        run_kernel(
            refractory_threshold,
            params={"threshold": 1.0, "impulse": 0.4, "refractory_period": 5, "tau": 8.0},
            name="refractory_threshold",
        ),
    ]

    for name, trace in runs:
        ascii_chart(trace, title=name)

    print("\n" + "=" * 64)
    print("  SUMMARY")
    print("=" * 64)
    for name, trace in runs:
        s = summary(trace, name)
        print(f"\n  {s['kernel']}")
        for k, v in s.items():
            if k == "kernel": continue
            print(f"    {k:<32} {v}")

    print("\n" + "=" * 64)
    print("  INTERFACE CHECK")
    print("=" * 64)
    print("  Cả 2 kernel:")
    print("    • Cùng signature: (prev_state, deviation, weight, params) -> state")
    print("    • Cùng quy ước key 'x_pp' trong return state")
    print("    • State extras tùy kernel: scalar (sigmoid) vs {x_pp, clock, fired} (refractory)")
    print("    • Loose params dict — không validator chung")
    print("  → Framework đỡ được cả continuous lẫn discrete dynamics.")
    print("  → Interface CHỐT được, có thể bắt đầu Giai đoạn C.")
