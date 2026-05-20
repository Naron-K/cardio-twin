# Feedback Loop Architecture — Universal Twin

> Tài liệu tóm tắt thiết kế & quyết định cho việc xây dựng cơ chế feedback loop
> trong framework Universal Twin. Đây là bản chốt sau audit; chi tiết toán học
> và lý do chọn từng kernel xem trong nhật ký trao đổi.
>
> **Trạng thái:** chốt thiết kế, chưa triển khai code.
> **Lamina thí nghiệm đầu tiên:** Circulatory (đã có sẵn).

---

## 1. Triết lý cốt lõi

1. **Universal trước, Cardiac sau.** Cardiac chỉ là test case để xác nhận khả thi, không định hình framework. Mọi thứ cardiac-specific phải nằm trong XML, không nằm trong Python framework.
2. **XML cho domain expert, Python cho dev.** Bám pattern hiện có (`_function_registry`).
3. **Default sẵn cho mọi extension point.** Domain expert override khi cần, không bắt buộc.
4. **Loose schema cho v1.** Ưu tiên extensibility hơn validation chặt. Khi framework ổn định sẽ siết dần.
5. **YAGNI cho kernel library.** V1 chỉ build 1 kernel default; thêm kernel mới khi có lamina thực sự cần.

---

## 2. Mô hình toán học chốt

### 2.1 Phân rã giá trị

```
X = X' + X''
```

- `X'` (X-prime) — **External Ingestion**: giá trị do sensor/môi trường ngoài ghi vào (`set_sensor`).
- `X''` (X-double-prime) — **Internal Feedback**: giá trị do loop nội bộ tự sinh ra.
- Hai vector **độc lập**, lưu riêng trên mỗi `Attribute`. Feedback không bao giờ ghi đè ground truth.

### 2.2 Ràng buộc biên hoạt động (v1)

- **`X' = 0` sau set ban đầu** — không có sensor stream song song. Cô lập cơ chế feedback thuần để verify math.
- Khi math ổn định: nới `X' ≠ 0` ở giai đoạn G.

### 2.3 Gate Function (default kernel: `sigmoid_leaky_tanh`)

Cho attribute *i* trong composite mục tiêu, tại cycle *t*:

```
ΔOV_t   = actual - target                                      (deviation)
d_t     = ΔOV_t / tolerance                                    (chuẩn hóa)

G(d)    = 1 / (1 + exp(-k · (|d| - 1)))                        (sigmoid mở gate)
raw     = polarity · gain · w_i · G(d_t) · d_t · tolerance     (tín hiệu hấp thụ)

X''_i,t = A_max · tanh( ((1-λ) · X''_i,t-1 + raw) / A_max )
```

Sau đó `value_i = X'_i + X''_i,t` (qua coupling kernel, mặc định additive), behaviour function chạy lại.

**Bốn thành phần:**

| Phần | Vai trò | Tham số |
|---|---|---|
| `polarity` | Hướng feedback. `-1.0` = negative (corrective, mặc định), `+1.0` = positive (amplifying). Float, hỗ trợ giá trị fractional (vd `0.5` = positive yếu) và `0` (monitor-only). Per-tag config. | `polarity` (mặc định -1.0) |
| Sigmoid `G(d)` | Ngưỡng mở gate; chặn nhiễu nhỏ trong tolerance | `threshold_k` (mặc định 4.0) |
| Leaky integrator `(1-λ)·X''` | Phasing-out, đảm bảo homeostasis. **Nằm bên trong kernel** (mỗi kernel có luật decay riêng), không phải framework-level step. | `decay` = λ (mặc định 0.10) |
| Tanh saturation | Chặn biên độ, đạo hàm liên tục | `saturation` = A_max (mặc định 0.3 × physio range) |

**`w_i` từ đâu:** đọc từ `Composite.distribution_vector` (vector mới, tách khỏi `absorption_vector` dùng cho learning loop — xem §3.3 và D2).

**Bằng chứng hội tụ (sơ lược):** với `X' = 0`, target cố định, polarity = -1:
- Tại `X'' = 0`: deviation = 0 → `G ≈ 0` → `raw ≈ 0` → decay kéo về 0 → fixed point.
- Tanh đảm bảo quỹ đạo không thoát `[-A_max, A_max]`.
- Polarity = +1 (positive feedback) **không đảm bảo hội tụ** — đặc tính sinh học của amplification. Domain expert phải chốt tolerance/saturation cẩn thận khi dùng.

### 2.4 Đơn vị correction

Chốt: correction sống ở **đơn vị gốc của attribute** (mmHg, L/min, mL). Lý do: trực quan cho domain expert. Áp dụng vào `attr.value`, không phải `attr.normalised`.

---

## 3. Kiến trúc framework

### 3.1 Extension points (registry pattern)

```
UniversalTwin
 ├─ _function_registry        (đã có)  attribute computation
 ├─ _deviation_registry       (mới)    cách tính ΔOV
 ├─ _emitter_registry         (mới)    ΔOV → Tag
 ├─ _gate_kernel_registry     (mới)    Tag → ΔX''
 ├─ _coupling_registry        (mới)    cách ghép X' và X''
 └─ _solver_registry          (mới)    algebraic vs ODE
```

Mỗi registry có **1 default** đăng ký sẵn trong `UniversalTwin.__init__`.

### 3.2 Default implementations cho v1

| Extension point | Default kernel | Mô tả |
|---|---|---|
| Deviation | `absolute` | `actual - target` |
| Emitter | `binary` | tolerance broken → emit |
| Gate kernel | `sigmoid_leaky_tanh` | xem mục 2.3 |
| Coupling | `additive` | `X = X' + X''` |
| Solver | `algebraic_chain` | `compute_all()` hiện tại |

### 3.3 XML schema mở rộng

```xml
<lamina ...>

  <!-- MỚI: timescale + solver cho behaviour function -->
  <behaviour_solver type="algebraic_chain" dt="1.0" unit="second"/>

  <!-- MỚI: cách kết hợp X' và X'' -->
  <coupling type="additive"/>

  <attributes>...</attributes>      <!-- giữ nguyên -->
  <functions>...</functions>        <!-- giữ nguyên -->

  <!-- MỞ RỘNG: composite có thêm distribution_vector (optional) -->
  <composites>
    <composite id="pump_state">
      <attributes>EDV, SV, HR, CO</attributes>

      <!-- Learning weights (giữ nguyên, dùng cho auto_adjust_weights) -->
      <absorption_vector>
        <weight attribute="EDV">0.25</weight>
        <weight attribute="SV">0.25</weight>
        <weight attribute="HR">0.25</weight>
        <weight attribute="CO">0.25</weight>
      </absorption_vector>

      <!-- MỚI: gate fanout weights (w_i trong §2.3). Optional, default 1/N -->
      <distribution_vector>
        <weight attribute="EDV">0.25</weight>
        <weight attribute="SV">0.25</weight>
        <weight attribute="HR">0.25</weight>
        <weight attribute="CO">0.25</weight>
      </distribution_vector>
    </composite>
  </composites>

  <gates>...</gates>                <!-- giữ nguyên (gate cũ = range/positive/consistency check) -->
  <segments>...</segments>          <!-- giữ nguyên -->

  <!-- MỚI: feedback tags -->
  <tags>
    <tag id="CO_DEVIATION" outcome="target_co"
         deviation_type="absolute"
         emitter="binary"
         gate_kernel="sigmoid_leaky_tanh"
         polarity="negative">         <!-- "negative"/"positive"/số. Default "negative" -->

      <!-- Multi-target: 1 tag có thể bơm vào nhiều composite -->
      <targets>
        <target address="pump_state" weight="1.0"/>
        <!-- Tương lai inter-lamina:
             <target address="lamina_endocrine:hormone_state" weight="0.3"/> -->
      </targets>

      <!-- Loose params: dict tự do, kernel tự interpret -->
      <params gain="0.6" decay="0.10" threshold_k="4.0" saturation="0.3"
              epsilon_ratio="0.001"/>  <!-- override dead-zone per-tag, optional -->
    </tag>
  </tags>

</lamina>
```

**Tag address space:** `[<lamina_id>:]<composite_id>`. Bỏ qua prefix lamina = local. **Validate lúc parse:** nếu bare composite_id khớp nhiều lamina → raise error, yêu cầu prefix rõ ràng (D5).

**Hai vector trên composite — vì sao tách (D2):**

| Vector | Dùng cho | Cập nhật bởi |
|---|---|---|
| `absorption_vector` | Learning loop (`auto_adjust_weights`) — đóng băng GĐ A-E, bật lại GĐ G | Auto Controller |
| `distribution_vector` | Gate fanout (`w_i` trong §2.3) — feedback loop hiện tại | Domain expert (qua XML), framework không tự cập nhật |

Tách hoàn toàn → 2 cơ chế độc lập, không giẫm chân nhau khi Auto Controller bật lại ở GĐ G.

**Distribution vector rules (D2):**
- Block vắng → default `1/N` đồng đều.
- Weight của attribute vắng → default `1/N`.
- Weight âm → raise error lúc parse (dấu do `polarity` carry).
- Tổng weight ≠ 1: **không normalize** — distribution là multiplier, không phải probability.

**Polarity rules (D7):**
- XML chấp nhận `"negative"`, `"positive"`, hoặc số (vd `"0.5"`, `"-1.0"`).
- Parser convert string → float lúc parse. Kernel chỉ thấy float.
- `0` = monitor-only (tag phát ra, log được, nhưng không tạo `X''`).

### 3.4 Backward compatibility

- Code cardiac hiện tại không cần đổi.
- XML hiện tại vẫn parse được — mọi block mới đều **optional** với default.
- Zero migration cost.

---

## 4. Quyết định đã chốt

| # | Quyết định | Chốt |
|---|---|---|
| 1 | Params schema strictness | **Loose** — dict tự do, kernel tự validate |
| 2 | Hướng kiến trúc | **Universal** (Phương án B: kernel registry) |
| 3 | Demo kernel thứ 2 trước khi build | **Không** — tin design, đi thẳng implement |
| 4 | Build ODE solver từ đầu | **Không** — chỉ khai báo interface, để slot trống |
| 5 | Đơn vị correction | **Đơn vị gốc attribute**, không phải normalised |
| 6 | `X' = 0` trong v1 | **Có** — cô lập feedback thuần để verify |
| 7 | Lamina thí nghiệm đầu | **Circulatory** (đã có sẵn) |
| 8 | Vị trí decay | **Trong kernel**, không phải framework step (D1) |
| 9 | Composite vectors | **Tách 2 vector**: `absorption_vector` (learning) + `distribution_vector` (gate fanout) (D2) |
| 10 | Epsilon dead-zone | **Tương đối**: `rho · (physio_max - physio_min)`, default `rho=0.001` (D3) |
| 11 | Kernel state | **Lưu ở `FeedbackController`** với khóa `(tag_id, attr_id)` (D4) |
| 12 | Snap behavior | Snap reset **cả** `value_feedback` lẫn kernel state về 0/neutral (D4 clarified) |
| 13 | Tag address ambiguous | **Validate lúc parse**, bắt buộc prefix nếu trùng tên cross-lamina (D5) |
| 14 | Coupling signature | `coupling(x_prime, x_pp, params) → float`. `x_prime=None` → trả `x_pp` (D6) |
| 15 | Polarity | **Float trong dataclass**, XML chấp nhận string thân thiện. Default `-1.0` (D7) |
| 16 | Multi-target fanout | Full deviation × `target_weight` (D8) |
| 17 | Tag emission frequency | **Poll** mỗi cycle (D9) |
| 18 | Multi-tag cùng target | **Sum** delta (D10) |
| 19 | Multi-target apply order | Apply hết → recompute **một lần** ở cuối (D11) |
| 20 | Rollback policy | Chỉ rollback `X''`, không bao giờ chạm `X'` (D12) |
| 21 | Circuit breaker | Thêm `max_norm` + `max_iterations` ở GĐ D (D16) |
| 22 | Trình tự cycle (7 bước) | Codified ở §5.0 (D18) |

---

## 5. Roadmap triển khai

### 5.0 Trình tự thực thi một cycle feedback (D18)

`FeedbackController.step()` chạy đúng 7 bước, theo thứ tự:

```
1. Tính deviation cho mọi outcome              (deviation_registry)
2. Emit tags                                    (emitter_registry, poll toàn bộ — D9)
3. Chạy gate kernel cho từng (tag, attr)       (lấy/lưu state ở controller — D4)
4. Cộng dồn delta theo target                   (sum — D10)
5. Apply X'' vào value_feedback                 (mọi target trước — D11)
6. Dead-zone snap-to-zero                       (epsilon tương đối — D3)
                                                (snap RESET cả X'' lẫn kernel state — D4)
7. compute_all() MỘT lần                        (recompute cuối cycle — D11)
```

**Lưu ý:**
- Decay **không** xuất hiện như bước riêng — nó nằm bên trong bước 3 (D1).
- Mỗi kernel tự decay theo luật riêng; framework chỉ điều phối thứ tự.
- Snap (bước 6) là numerical cleanup, **không phải** decay (D1 clarified).

---

### Giai đoạn A — Phân rã `X = X' + X''`

**Mục tiêu:** mỗi `Attribute` mang 2 vector độc lập + Composite có 2 vector tách riêng.

**Sửa `Attribute`:**
- Thêm `value_external`, `value_feedback` vào dataclass.
- `value` thành `@property` = `coupling(value_external, value_feedback, params)` (qua coupling kernel, mặc định additive).
- `set_sensor()` chỉ ghi `value_external`.
- Method `apply_feedback(delta)` chỉ ghi `value_feedback`.
- `rollback()` **chỉ rollback `value_feedback`** (D12). `value_external` không bao giờ bị chạm — sensor là sacred.

**Sửa `Composite`:**
- Thêm field `distribution_vector` song song với `absorption_vector` đã có (D2).
- Parser: block `<distribution_vector>` optional; vắng → default `1/N`.

**Sửa API response:** mỗi attribute trả cả 2 vector tách riêng (`value_external`, `value_feedback`) thay vì chỉ scalar `value`.

**Comment cảnh báo** trong `universal_twin.py` chỗ `auto_adjust_weights()`: ghi rõ đóng băng trong GĐ A-E, chỉ chạm `absorption_vector`, không bao giờ chạm `distribution_vector` (D17).

**Pluggable point:** coupling kernel (default = additive, signature `coupling(x_prime, x_pp, params) → float`; `x_prime=None` → trả `x_pp` — D6).

**Test gate:** với feedback chưa chạy (`value_feedback = 0` toàn bộ), output trùng 100% behavior cũ.

---

### Giai đoạn B — Tag pipeline (OV → Tag → Identifier → Metrix)

**Mục tiêu:** chuyển deviation thành tín hiệu rời rạc có địa chỉ.

**Dataclass `Tag`:**
```python
@dataclass
class Tag:
    id: str
    outcome: str
    deviation_type: str = "absolute"
    emitter: str = "binary"
    gate_kernel: str = "sigmoid_leaky_tanh"
    polarity: float = -1.0            # D7 — float, không phải string
    targets: list[TagTarget] = ...    # list of (address, weight)
    params: dict = ...                # loose dict
```

**Parser:**
- Block `<tags>` trong XML.
- Polarity converter: string `"negative"`/`"positive"` → float; chấp nhận luôn số (D7).
  ```python
  POLARITY_MAP = {"negative": -1.0, "positive": +1.0}
  polarity = POLARITY_MAP.get(raw, float(raw))
  ```
- Address resolver `[<lamina>:]<composite>`:
  - Local-first lookup.
  - Validate lúc parse: nếu bare composite_id khớp nhiều lamina → raise lỗi rõ ràng yêu cầu prefix (D5).
- Multi-target: 1 tag fanout vào N composite với `target_weight` riêng (D8).

**Identifier + Metrix:**
- `Identifier.emit_tags(outcome_evaluations) → list[Tag]` — poll toàn bộ outcome mỗi cycle (D9).
- `Metrix.lookup(tag) → params dict` — chỉ là dict access.

**Pluggable points:** deviation_type, emitter (defaults: `absolute`, `binary`).

---

### Giai đoạn C — Registry framework + default gate kernel + FeedbackController

**Mục tiêu:** framework các kernel pluggable + cài đặt 1 kernel chạy được + controller điều phối cycle.

**Registries:**
- Thêm 5 registry vào `UniversalTwin` (xem 3.1).
- Cài đặt 5 default kernel:
  - `sigmoid_leaky_tanh` theo công thức §2.3 (decay nằm trong kernel — D1).
  - `absolute`, `binary`, `additive`, `algebraic_chain` — phần lớn là wrapper code hiện có.
- Đăng ký interface cho `solver_registry` nhưng không cài ODE.

**`FeedbackController` (file mới `backend/feedback_controller.py`):**

```python
class FeedbackController:
    def __init__(self, twin: UniversalTwin):
        self.twin = twin
        # State storage: D4 — khóa (tag_id, attr_id), không gắn vào domain object
        self._kernel_state: dict[tuple[str, str], dict] = {}

    def step(self) -> dict:
        # Trình tự 7 bước theo §5.0 — D18
        # ...
```

**State management (D4):**
- State lưu ở `FeedbackController._kernel_state[(tag_id, attr_id)]`, không trên `Attribute`/`Tag`.
- Persist qua các cycle. Tag fire lại = continue từ state cũ.
- Khi snap (bước 6 cycle) → reset cả `attr.value_feedback = 0` **lẫn** `self._kernel_state[(tag_id, attr_id)] = {}` (D4 clarified).

**Multi-target & multi-tag handling:**
- Multi-target trong 1 tag: full deviation × `target_weight` cho mỗi target (D8).
- Nhiều tag cùng target: sum delta (D10).
- Apply hết delta → recompute `compute_all()` **một lần** ở cuối (D11).

**Quan trọng:** interface `BehaviourSolver` phải khai báo từ đây, để khi cần `ode_rk4` sau không breaking.

---

### Giai đoạn D — API endpoints + Circuit breaker

- `POST /api/feedback/step?lamina=circulatory` — chạy 1 cycle, trả tags + deltas + state mới.
- `POST /api/feedback/run?lamina=circulatory&cycles=N` — batch N cycle.
- Giữ nguyên `/api/compute` (snapshot `X'' = 0`).
- `?lamina=` query param chuẩn bị sẵn cho multi-lamina.

**Circuit breaker (D16):** bảo vệ trước sign convention sai gây phân kỳ âm thầm.
- `max_norm` (default 10.0): nếu `feedback_norm > max_norm` → abort cycle, raise warning.
- `max_iterations` (default 1000): cap cứng cho batch run.
- Phát hiện sớm bug trước khi vào settling test (GĐ E).

Response shape:
```json
{
  "cycle": 7,
  "tags_emitted": ["CO_DEVIATION"],
  "absorption_deltas": {"EDV": +0.31, "SV": +0.17, "HR": +0.22, "CO": +0.30},
  "feedback_norm": 0.84,
  "sensors": {...},
  "computed": {...}
}
```

---

### Giai đoạn E — Settling test (bằng chứng homeostasis)

- Thêm method `UniversalTwin.feedback_norm()` — normalize theo physio range (D13):
  ```python
  feedback_norm = Σ|X''_i| / Σ(physio_max_i - physio_min_i)
  ```
  **Generic, dùng cho mọi lamina.**
- "Settled" definition (D14): `feedback_norm < threshold` trong **5 cycle liên tiếp**.
- Test cardiac cụ thể:
  1. Set sensor đẩy CO ngoài tolerance (HR=110, EDV=180 → CO ≈ 10.9).
  2. Chạy 100 cycle với `X' = 0`.
  3. Assert: `feedback_norm` giảm đơn điệu, CO hội tụ vào dải `target ± tolerance`, sau khi hội tụ không có tag mới và `X'' → 0` trong 5 cycle liên tiếp.
- **Test bổ sung (D10):** tạo 1 tag negative + 1 tag positive cùng target, verify sum delta hành xử đúng (không triệt tiêu ngoài ý muốn).

---

### Giai đoạn F (defer) — Frontend

- Panel "Feedback" hiển thị `X'` vs `X''` per attribute (stacked bar).
- Step / Run / Reset buttons.
- Line chart `feedback_norm` qua các cycle.

---

### Giai đoạn G (defer) — Mở rộng tương lai

| Hạng mục | Khi nào cần | Đã chuẩn bị gì |
|---|---|---|
| Bật `X' ≠ 0` (sensor stream song song feedback) | Sau khi settling test pass | Coupling pluggable đã có |
| Kernel mới (`pid`, `refractory_threshold`, `hysteresis`) | Khi có lamina yêu cầu | Registry pattern đã có |
| ODE solver (`ode_rk4`) | Khi có lamina ODE (vd thần kinh) | `_solver_registry` interface đã có |
| Multi-lamina + inter-lamina gating | Khi build lamina thứ 2 | Tag address `<lamina>:<composite>` đã hỗ trợ |
| Deviation type khác (`relative`, `rate`) | Khi có outcome cần | Registry đã có |
| Auto Controller weight learning | Sau khi feedback loop ổn | Đã có `auto_adjust_weights()`; đóng băng trong giai đoạn A-E |

---

## 6. Ước lượng công sức

| GĐ | Effort | Risk | Ghi chú |
|---|---|---|---|
| A | ~0.5 ngày | Thấp | Touches `Attribute`, ripple sang API response |
| B | ~0.5 ngày | Thấp | XML + parser pattern đã quen |
| C | ~1.5 ngày | **Cao nhất** | Sign convention + decay rate cần tune; interface design quan trọng |
| D | ~2 giờ | Thấp | |
| E | ~2 giờ | Trung bình | Có thể surface tuning issue từ C |
| F | ~1 ngày | Optional | |

**Tổng giai đoạn A-E:** ~3 ngày làm việc.

---

## 7. Câu hỏi mở (đã giải quyết qua decisions log §10)

1. ~~**Sign convention tag-level:**~~ → **Giải:** D7 — polarity là float per-tag, default `-1.0`. Công thức §2.3 thành `raw = polarity · gain · w · G · d · tolerance`.

2. ~~**Tag emission frequency:**~~ → **Giải:** D9 — poll mỗi cycle.

3. ~~**Multiple tags cùng target:**~~ → **Giải:** D10 — sum delta. Test bổ sung positive×negative ở GĐ E.

4. ~~**Tolerance rebound:**~~ → **Giải:** dead-zone snap-to-zero (§9.2 + D3).

5. ~~**`feedback_norm` metric:**~~ → **Giải:** D13 — normalize theo physio range.

**Câu hỏi mở còn lại (chỉ quan sát trong GĐ E, không blocker):**

- **Edge case D4:** tag đóng gate, `X''` đang decay nhưng *chưa* chạm epsilon, rồi deviation mới xuất hiện → kernel tiếp tục từ `X''` còn dư. Có thể đúng (quán tính sinh học) hoặc sai (nhiễu cũ rò vào correction mới). Quan sát thực tế trong GĐ E test, ghi lại behavior, quyết sau nếu có vấn đề.

---

## 8. Nguyên tắc viết code

- Đăng ký kernel bằng decorator hoặc dict assignment trong `_register_*()` methods, đối xứng với `_register_functions()`.
- Kernel function signature thống nhất: `kernel(state, params, context) → new_state`. State có thể là scalar/dict tùy kernel.
- Không validate params strictly — kernel tự `params.get("gain", 0.5)` với default sensible.
- Mỗi kernel có docstring nêu rõ: input shape, output shape, params expected (loose contract documented).
- Log đầy đủ qua `self._log()` để debug feedback dynamics.

---

---

## 9. Demo verification (đã chạy) + cải tiến

### 9.1 Kết quả demo

File: [`feedback_kernel_demo.py`](feedback_kernel_demo.py) — chạy 2 kernel dynamics khác nhau hoàn toàn trên cùng 1 deviation signal để verify interface universal.

| Kernel | Dynamics | State shape | Settled? | Lọc nhiễu? |
|---|---|---|---|---|
| `sigmoid_leaky_tanh` | continuous, smooth | `{x_pp}` | ⚠️ 1% residual sau 100 cycle | ✓ peak nhiễu 0.09 |
| `refractory_threshold` | discrete event, multi-state | `{x_pp, clock, fired}` | ✓ < 1e-4 | ✓ peak nhiễu 0.004 |

**Pass criteria:**

- [x] Cả 2 kernel cùng signature `(prev_state, deviation, weight, params) → state`.
- [x] State extras tùy kernel (scalar vs dict 3 field) — interface không ràng buộc.
- [x] Loose params dict — không cần validator chung.
- [x] Mỗi kernel react đúng dynamics đặc trưng (sigmoid smooth, refractory fire-and-rest).
- [x] Cả 2 ignore nhiễu trong dead-zone (|d| nhỏ).

→ **Interface chốt. Có thể bắt đầu Giai đoạn A.**

### 9.2 Phát hiện #1 — Sigmoid kernel settle chậm

**Hiện tượng:** `sigmoid_leaky_tanh` với λ=0.10 còn ~1% residual `x_pp` sau 100 cycle dù `deviation = 0`. Không sai về math (đúng exponential decay), nhưng không thực sự "phẳng" về 0.

**Vì sao quan trọng:** trong test E (Giai đoạn E), bài kiểm tra settling cần `feedback_norm → 0` rõ ràng. Residual 1% sẽ làm assert flaky.

**Phương án cải tiến — Dead-zone snap-to-zero ở framework level (D3 + D4 clarified):**

```python
# Trong FeedbackController.step() bước 6, SAU khi apply X''.
# Epsilon TƯƠNG ĐỐI theo physio range (D3):
for attr in twin.attributes.values():
    epsilon = rho * (attr.physio_max - attr.physio_min)  # rho default = 0.001
    if abs(attr.value_feedback) < epsilon:
        attr.value_feedback = 0.0
        # Snap RESET kernel state đồng thời (D4 clarified)
        for key in [k for k in controller._kernel_state if k[1] == attr.id]:
            controller._kernel_state[key] = {}
```

**Lý do chọn cách này:**

1. **Clean separation** — kernel chỉ lo dynamics, framework lo numerical cleanup. Snap **không phải** decay (D1).
2. **Universal** — mọi kernel hiện tại và tương lai tự động hưởng lợi, không cần code thêm.
3. **Không phá interface** — không thêm field nào vào kernel state, không đổi signature.
4. **Configurable per-tag** — `<params epsilon_ratio="0.001"/>` override; mặc định framework dùng `rho=0.001`.
5. **Math-friendly** — snap ở biên độ rất nhỏ không thay đổi semantics động học.
6. **Epsilon tương đối** — đồng nhất về tỷ lệ trên mọi attribute (D3). Tránh trường hợp `1e-3` mmHg vs `1e-3` L/min lệch ý nghĩa.
7. **Snap reset cả state** — đảm bảo Attribute và kernel state không drift khỏi nhau (D4 clarified).

**Triển khai:** ~10 dòng code trong `FeedbackController.step()` ở Giai đoạn C. Không sửa kernel nào.

### 9.3 Phát hiện #2 — Discrete reset settle sạch hơn continuous decay

**Hiện tượng:** `refractory_threshold` settle về < 1e-4 trong cùng số cycle, không cần snap-to-zero. Lý do: exponential decay với τ=8 + không có signal mới sau cycle 20 → x_pp giảm theo `e^(-80/8) ≈ 3e-5`, nhanh hơn nhiều so với linear decay λ=0.10.

**Bài học cho framework:** không cần "fix" kernel này — discrete reset (refractory clock cắt signal hoàn toàn khi clock > 0) là một dạng absorption tự nhiên không có ở continuous kernel.

**Không kéo logic refractory vào sigmoid kernel** — YAGNI. Mỗi kernel giữ dynamics riêng, framework dùng dead-zone (9.2) như cleanup chung. Khi nào có lamina thực sự cần combine 2 cơ chế, viết kernel thứ 3 (vd `sigmoid_refractory`), không monkey-patch kernel cũ.

### 9.4 Tổng kết tác động vào plan

| Section trong plan | Thay đổi |
|---|---|
| §3.1 (extension points) | Không đổi |
| §3.2 (default kernels) | Không đổi |
| §5 Giai đoạn C | Snap dead-zone với epsilon **tương đối** (D3), reset cả kernel state (D4). ~10 dòng code. |
| §5 Giai đoạn E | Settling: `feedback_norm` normalize theo physio range; "settled" = dưới ngưỡng 5 cycle liên tiếp. |
| §7 câu hỏi mở | Tất cả Q1-Q5 đã có quyết định trong decisions log §10. |

**Không có breaking change.** Cấu trúc, interface, XML schema vẫn backward compatible 100%.

---

## 10. Decisions Log — Feedback Loop Audit Resolution

> Bản chốt 22 quyết định (20 từ audit + 2 clarification thêm trong review). Nguyên
> tắc: cân bằng — chọn phương án đơn giản nhất *không* tạo nợ kỹ thuật cho GĐ G.
> Khi đơn giản và an toàn xung đột, ưu tiên an toàn.

### Tầng 1 — Blocker, phải áp dụng trước khi code Giai đoạn A

#### D1 — Vị trí của decay (audit #1)

**Quyết định:** Decay là responsibility của **kernel**, không phải framework.

**Lý do:** Mỗi kernel có luật decay riêng — `sigmoid_leaky_tanh` dùng `(1-λ)` tuyến tính, `refractory_threshold` dùng `e^(-1/τ)` mũ. Framework không có công thức decay generic áp được cho mọi kernel. Để decay ở cả hai chỗ sẽ chạy hai lần mỗi cycle `(1-λ)²`, làm sai bằng chứng hội tụ §2.3.

**Tác động vào plan:**
- §2.3: giữ nguyên — decay nằm trong công thức kernel.
- §5.0 + §5 GĐ C: pseudocode chỉ gọi kernel; kernel tự lo decay nội bộ.
- §9.2: dead-zone snap **không phải** decay, nó là numerical cleanup chạy *sau* kernel. Hai cơ chế cùng tồn tại, không xung đột.

#### D2 — Tách absorption_vector (audit #2)

**Quyết định:** Tách thành **hai vector** trên `Composite`:
- `absorption_vector` — giữ nguyên vai trò cũ: trọng số cho learning loop (`auto_adjust_weights`).
- `distribution_vector` — mới: `w_i` cho gate function fanout (công thức §2.3).

**XML schema (chốt sau review):**
- Block `<distribution_vector>` mới, optional.
- Vắng → default `1/N` đồng đều. Backward compat 100%.
- Weight vắng cho 1 attribute → `1/N`.
- Weight âm → raise lỗi parse.
- Tổng weight: **không normalize** — distribution là multiplier, không phải probability.
- Weight cho attribute không thuộc composite → raise lỗi parse (typo bảo vệ).

**Lý do tách:** Plan không bỏ learning, chỉ *đóng băng* trong GĐ A-E và bật lại ở GĐ G. Dùng chung một vector → đến G hai cơ chế giẫm chân nhau. Tách ngay chỉ tốn một field dataclass — rẻ hơn nhiều so với gỡ rối sau.

**Tác động vào plan:**
- §5 GĐ A: thêm `distribution_vector` vào `Composite`.
- §3.3: XML example mở rộng có cả 2 vector.
- §5 GĐ G (Auto Controller): learning chỉ động vào `absorption_vector`.

#### D3 — EPSILON cho dead-zone là tương đối (audit #10)

**Quyết định:** Epsilon **tương đối theo physio range**:
```
epsilon_i = rho · (physio_max_i - physio_min_i)
```
`rho` mặc định = `0.001`. Cho phép override per-tag qua `<params epsilon_ratio="..."/>`.

**Lý do:** §2.4 chốt correction sống ở đơn vị gốc attribute. Epsilon tuyệt đối `1e-3` có nghĩa khác nhau cho mmHg (dải ~40–180) và L/min (dải ~4–8). Epsilon tương đối làm ngưỡng snap đồng nhất về mặt tỷ lệ trên mọi attribute.

**Tác động vào plan:** §9.2 — thay "default 1e-3" bằng công thức tương đối.

#### D4 — Vị trí và vòng đời của kernel state (audit #5 + #11)

**Quyết định lưu ở đâu:** `FeedbackController` giữ dict `{(tag_id, attr_id): state}`. Domain object (`Attribute`, `Tag`) không mang state động học.

**Quyết định vòng đời:** State persist qua các cycle. Tag fire lại = continue từ state cũ.

**Quyết định snap (clarification sau review):** Khi snap kích hoạt (`X'' < epsilon`):
- Reset `attr.value_feedback = 0`
- **Đồng thời** reset `controller._kernel_state[(tag_id, attr_id)] = {}` cho mọi tag đang chạm attribute này
- Lý do: nếu chỉ reset `X''` mà giữ kernel state cũ, cycle sau kernel sẽ tính từ x_pp dư, drift khỏi `value_feedback = 0`.

**Lý do:** Khóa `(tag_id, attr_id)` xử lý đúng trường hợp hai tag cùng kernel trên cùng attribute. Tách state khỏi domain object giữ `Attribute`/`Tag` "thuần", dễ test. Continue (thay vì reset mỗi cycle) phản ánh quán tính sinh lý.

**Edge case cần quan sát (không blocker):** Tag đóng gate, `X''` đang decay nhưng *chưa* chạm epsilon, deviation mới xuất hiện → kernel tiếp tục từ `X''` còn dư. Có thể đúng (quán tính) hoặc sai (nhiễu cũ rò vào correction mới). → Đưa vào câu hỏi mở để GĐ E quan sát.

**Tác động vào plan:** §5 GĐ C — `FeedbackController` khai báo dict state với khóa cặp + snap reset logic.

#### D5 — Quy tắc resolve tag address (audit #3)

**Quyết định:** Local-first; **bắt buộc prefix `lamina_id:` nếu ambiguous**; validate ngay **lúc parse XML** (không lazy).

**Lý do:** Fail sớm lúc parse tốt hơn fail âm thầm lúc runtime. Hiện chỉ có 1 lamina nên ambiguity chưa xảy ra, nhưng viết rule vào schema ngay để không phải đổi khi build lamina thứ hai.

**Tác động vào plan:** §3.3 + §5 GĐ B — address resolver kiểm tra ambiguity lúc parse, raise lỗi rõ ràng.

#### D6 — Coupling kernel signature (audit #6)

**Quyết định:** Chốt signature:
```python
def coupling(x_prime: float | None, x_pp: float, params: dict) -> float
```
Khi `x_prime is None` (sensor chưa set) → trả `x_pp` thuần.

**Về `multiplicative`:** v1 chỉ dùng `additive`. Kernel `multiplicative` (chưa triển khai) sẽ phải tự clamp — `x_prime · (1 + x_pp)` với `x_pp = -1` cho `value = 0` (tim ngừng đập) là biên sinh học không hợp lệ.

**Tác động vào plan:** §3.1 — ghi rõ signature coupling. §3.2 — ghi chú cảnh báo clamp cho `multiplicative` (chưa triển khai v1).

### Tầng 2 — Chốt được ngay, áp dụng khi vào đúng giai đoạn

#### D7 — Polarity per tag (audit #7)

**Quyết định (chốt sau review):** `polarity` là **float** trong dataclass `Tag`, default `-1.0`. XML chấp nhận string thân thiện hoặc số:
- `polarity="negative"` → `-1.0`
- `polarity="positive"` → `+1.0`
- `polarity="0"` → monitor-only (phát tag, log, không tạo X'')
- `polarity="0.5"` → positive yếu (fractional)
- `polarity="-1.0"` → numeric trực tiếp

Parser convert string → float lúc parse:
```python
POLARITY_MAP = {"negative": -1.0, "positive": +1.0}
polarity = POLARITY_MAP.get(raw, float(raw))
```

**Lý do float thay vì string:**
1. Semantic separation: `gain` = magnitude, `polarity` = direction.
2. Tránh string branching ở layer math (kernel không phải `if polarity == "negative"`).
3. Universal-ready: hỗ trợ fractional polarity, monitor-only (=0), advanced override mà không đổi schema.

**Tác động vào plan:** §2.3 — công thức `raw = polarity · gain · w · G · d · tolerance`. §3.3 — schema `<tag polarity="...">`. §5 GĐ B — parser convert string → float.

#### D8 — Multi-target fanout (audit #4)

**Quyết định:** Full deviation × `target_weight`. Mỗi target nhận trọn deviation rồi nhân trọng số riêng. **Không** chia deviation theo tỷ lệ.

**Lý do:** Mô hình điều khiển, không phải mô hình vật lý cần bảo toàn năng lượng. Full × weight đơn giản và trực quan.

**Tác động vào plan:** §5 GĐ B — multi-target apply theo công thức này.

#### D9 — Tần suất emit tag (audit #8)

**Quyết định:** **Poll** — mỗi cycle quét toàn bộ outcome.

**Lý do:** Event-driven tiết kiệm CPU nhưng phải lưu trạng thái lần trước để detect crossing edge — thêm phức tạp không cần cho v1. Sigmoid `G(d)` đã tự lọc nhiễu trong tolerance.

**Tác động vào plan:** Xác nhận §7 Q2 — chốt poll cho v1.

#### D10 — Nhiều tag cùng một target (audit #9)

**Quyết định:** **Sum** — `delta_total = Σ delta_i`.

**Cảnh báo tương tác với D7:** nếu một tag `polarity=negative` và một tag `polarity=positive` cùng bơm vào một target, sum sẽ bù trừ. Phần lớn trường hợp là hành vi đúng, nhưng **thêm test riêng ở GĐ E** cho kịch bản này.

**Tác động vào plan:** Xác nhận §7 Q3 — chốt sum. §5 GĐ E — thêm test positive-vs-negative cùng target.

#### D11 — Thứ tự apply multi-target (audit #12)

**Quyết định:** Apply **tất cả** delta vào mọi attribute trước, rồi gọi `compute_all()` **một lần** ở cuối.

**Lý do:** Deterministic, không phụ thuộc thứ tự khai báo `<target>` trong XML. Tránh việc attribute PRELIMINARY (MAP, R) cập nhật khác nhau tùy thứ tự.

**Tác động vào plan:** §5 GĐ C — `FeedbackController.step()` apply rồi recompute một lần.

#### D12 — Rollback policy (audit #13)

**Quyết định:** Khi gate fail, **chỉ rollback `X''`**. `X'` (sensor) không bao giờ bị rollback.

**Lý do:** Nhất quán với triết lý §2.1 — feedback không bao giờ ghi đè ground truth, và ngược lại ground truth không bị xóa bởi một cycle feedback hỏng.

**Tác động vào plan:** §5 GĐ A — `Attribute.rollback()` chỉ tác động `value_feedback`.

### Tầng 3 — Hoãn tới đúng giai đoạn

#### D13 — feedback_norm metric (audit #14)

**Quyết định:** Normalize theo physio range để nhất quán với D3:
```
feedback_norm = Σ|X''_i| / Σ(physio_max_i - physio_min_i)
```

#### D14 — Định nghĩa "settled" (audit #15)

**Quyết định:** `feedback_norm` dưới ngưỡng trong **5 cycle liên tiếp**.

#### D15 — Hoãn không cần quyết v1 (audit #16, #17, #18)

- #16 graded_sigmoid emitter: định nghĩa công thức khi thực sự cần (không phải v1).
- #17 dt semantics: với `algebraic_chain`, `dt` vô nghĩa (steady-state). Hoãn tới khi có ODE solver.
- #18 deviation_type rate: định nghĩa nơi lưu `prev_actual` khi thực sự cần.

#### D16 — Circuit breaker (audit #19)

**Quyết định:** **Nâng nhẹ ưu tiên** — thêm guard `max_norm` (default 10.0) và `max_iterations` (default 1000) ngay ở GĐ D, không hoãn.

**Lý do:** GĐ C rủi ro cao nhất vì sign convention cần tune. Nếu lỡ sai dấu, vòng lặp phân kỳ âm thầm. Guard rất rẻ, nên có sẵn trước khi chạy settling test.

#### D17 — Boundary với auto_adjust_weights() cũ (audit #20)

**Quyết định:** Sau khi tách vector (D2), xung đột giảm hẳn. Chỉ cần **comment cảnh báo** trong code tại `universal_twin.py` chỗ `auto_adjust_weights()`, ghi rõ nó đóng băng trong GĐ A-E. Không cần throw.

### Bổ sung — D18

#### D18 — Trình tự thực thi trong một cycle

**Quyết định:** Codified thành §5.0 — 7 bước chuẩn của `FeedbackController.step()`.

**Lý do:** Audit không nêu, nhưng plan thiếu một chỗ duy nhất viết rõ trình tự một cycle. Developer GĐ C cần nhất điều này.

### Bảng tổng hợp nhanh

| # audit | Quyết định | Tầng | Giai đoạn áp dụng |
|---|---|---|---|
| 1 | Decay thuộc kernel | 1 | A (sửa doc trước) |
| 2 | Tách 2 vector + XML schema | 1 | A |
| 3 | Local-first, prefix nếu ambiguous, validate lúc parse | 1 | B |
| 4 | Full deviation × target_weight | 2 | B |
| 5 | State ở FeedbackController, khóa (tag,attr) | 1 | C |
| 6 | Signature chốt; x_prime None → x_pp thuần | 1 | A/C |
| 7 | Polarity là float trong dataclass; XML accept string/số | 2 | B |
| 8 | Poll | 2 | C |
| 9 | Sum | 2 | C |
| 10 | Epsilon tương đối theo physio range | 1 | C (sửa §9.2) |
| 11 | State persist; snap reset cả X'' lẫn kernel state | 1 | C |
| 12 | Apply hết → recompute 1 lần | 2 | C |
| 13 | Chỉ rollback X'' | 2 | A |
| 14 | Normalize feedback_norm | 3 | E |
| 15 | Settled = 5 cycle liên tiếp | 3 | E |
| 16-18 | Hoãn | 3 | — |
| 19 | Circuit breaker, nâng ưu tiên | 3→2 | D |
| 20 | Comment cảnh báo, không throw | 3 | A-E |
| D18 | Trình tự cycle 7 bước | 1 | C (§5.0) |

---

*Cuối tài liệu. Tất cả Tầng 1 đã áp vào plan. Sẵn sàng code Giai đoạn A.*
