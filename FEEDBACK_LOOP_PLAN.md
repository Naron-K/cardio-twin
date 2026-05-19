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
ΔOV_t   = actual - target                         (deviation)
d_t     = ΔOV_t / tolerance                       (chuẩn hóa)

G(d)    = 1 / (1 + exp(-k · (|d| - 1)))           (sigmoid mở gate)
raw     = -gain · w_i · G(d_t) · d_t · tolerance  (tín hiệu hấp thụ có dấu)

X''_i,t = A_max · tanh( ((1-λ) · X''_i,t-1 + raw) / A_max )
```

Sau đó `value_i = X'_i + X''_i,t`, behaviour function chạy lại.

**Ba thành phần:**

| Phần | Vai trò | Tham số |
|---|---|---|
| Sigmoid `G(d)` | Ngưỡng mở gate; chặn nhiễu nhỏ trong tolerance | `threshold_k` (mặc định 4.0) |
| Leaky integrator `(1-λ)·X''` | Phasing-out, đảm bảo homeostasis | `decay` = λ (mặc định 0.10) |
| Tanh saturation | Chặn biên độ, đạo hàm liên tục | `saturation` = A_max (mặc định 0.3 × physio range) |

**Bằng chứng hội tụ (sơ lược):** với `X' = 0`, target cố định:
- Tại `X'' = 0`: deviation = 0 → `G ≈ 0` → `raw ≈ 0` → decay kéo về 0 → fixed point.
- Tanh đảm bảo quỹ đạo không thoát `[-A_max, A_max]`.

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
  <composites>...</composites>      <!-- giữ nguyên -->
  <gates>...</gates>                <!-- giữ nguyên (gate cũ = range/positive/consistency check) -->
  <segments>...</segments>          <!-- giữ nguyên -->

  <!-- MỚI: feedback tags -->
  <tags>
    <tag id="CO_DEVIATION" outcome="target_co"
         deviation_type="absolute"
         emitter="binary"
         gate_kernel="sigmoid_leaky_tanh">

      <!-- Multi-target: 1 tag có thể bơm vào nhiều composite -->
      <targets>
        <target address="pump_state" weight="1.0"/>
        <!-- Tương lai inter-lamina:
             <target address="lamina_endocrine:hormone_state" weight="0.3"/> -->
      </targets>

      <!-- Loose params: dict tự do, kernel tự interpret -->
      <params gain="0.6" decay="0.10" threshold_k="4.0" saturation="0.3"/>
    </tag>
  </tags>

</lamina>
```

**Tag address space:** `[<lamina_id>:]<composite_id>`. Bỏ qua prefix lamina = local. Schema đã chuẩn bị sẵn cho inter-lamina, không cần đổi sau.

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

---

## 5. Roadmap triển khai

### Giai đoạn A — Phân rã `X = X' + X''`

**Mục tiêu:** mỗi `Attribute` mang 2 vector độc lập.

- Thêm `value_external`, `value_feedback` vào dataclass `Attribute`.
- `value` thành `@property` = `value_external + value_feedback` (qua coupling kernel).
- `set_sensor()` chỉ ghi `value_external`.
- Method `apply_feedback(delta)` chỉ ghi `value_feedback`.
- API response trả cả 2 vector tách riêng.

**Pluggable point:** coupling kernel (default = additive).

**Test gate:** với feedback chưa chạy, output trùng 100% behavior cũ.

---

### Giai đoạn B — Tag pipeline (OV → Tag → Identifier → Metrix)

**Mục tiêu:** chuyển deviation thành tín hiệu rời rạc có địa chỉ.

- Thêm dataclass `Tag` (id, outcome, deviation_type, emitter, gate_kernel, targets, params).
- Parser cho `<tags>` block trong XML.
- Address resolver `[<lamina>:]<composite>` (lamina prefix optional).
- Multi-target support: 1 tag fanout vào N composite với weight riêng.
- `Identifier.emit_tags(outcome_evaluations) → list[Tag]`.
- `Metrix.lookup(tag) → params dict`.

**Pluggable points:** deviation_type, emitter (defaults: `absolute`, `binary`).

---

### Giai đoạn C — Registry framework + default gate kernel

**Mục tiêu:** framework các kernel pluggable + cài đặt 1 kernel chạy được.

- Thêm 5 registry vào `UniversalTwin` (xem 3.1).
- Cài đặt `sigmoid_leaky_tanh` kernel theo công thức 2.3.
- Cài đặt 4 default kernel đơn giản còn lại (`absolute`, `binary`, `additive`, `algebraic_chain` — phần lớn chỉ là wrapper code hiện có).
- Đăng ký interface cho `solver_registry` nhưng không cài ODE.
- File mới: `backend/feedback_controller.py` chứa `FeedbackController.step()`.

**Quan trọng:** interface `BehaviourSolver` phải khai báo từ đây, để khi cần `ode_rk4` sau không breaking.

---

### Giai đoạn D — API endpoints

- `POST /api/feedback/step?lamina=circulatory` — chạy 1 cycle, trả tags + deltas + state mới.
- `POST /api/feedback/run?lamina=circulatory&cycles=N` — batch N cycle.
- Giữ nguyên `/api/compute` (snapshot `X'' = 0`).
- `?lamina=` query param chuẩn bị sẵn cho multi-lamina.

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

- Thêm method `UniversalTwin.feedback_norm()` — tổng `|X''|` trên tất cả attribute. **Generic, dùng cho mọi lamina.**
- Test cardiac cụ thể:
  1. Set sensor đẩy CO ngoài tolerance (HR=110, EDV=180 → CO ≈ 10.9).
  2. Chạy 100 cycle với `X' = 0`.
  3. Assert: `feedback_norm` giảm đơn điệu, CO hội tụ vào dải `target ± tolerance`, sau khi hội tụ không có tag mới và `X'' → 0`.

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

## 7. Câu hỏi mở (cần làm rõ trước/trong khi triển khai)

1. **Sign convention tag-level:** mặc định `delta = -gain · ... · d` là corrective (negative feedback). Có tag nào cần positive feedback (amplification) không? Nếu có → thêm field `polarity` per tag.

2. **Tag emission frequency:** mỗi cycle scan toàn bộ outcome, hay event-driven (chỉ emit khi crossing boundary)? V1 scan toàn bộ cho đơn giản.

3. **Multiple tags cùng target cùng cycle:** 2 tag cùng bơm vào `pump_state` cùng lúc → sum delta hay max delta? V1 mặc định sum.

4. **Tolerance rebound:** sau khi value rơi vào tolerance, gate đóng. Nhưng decay vẫn tiếp tục kéo `X''` về 0, làm value drift ngược ra. ~~Có cần "memory anchor" giữ value tại tolerance edge không?~~ → **Đã có hướng giải:** dead-zone snap-to-zero ở framework level. Xem mục 9.2.

5. **`feedback_norm` metric:** dùng raw `Σ|X''|` hay normalize theo physio range? Universal hơn nếu normalize. **Cần chốt khi vào giai đoạn E.**

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

**Phương án cải tiến — Dead-zone snap-to-zero ở framework level:**

```python
# Trong FeedbackController.step(), SAU khi kernel chạy:
for attr in twin.attributes.values():
    if abs(attr.value_feedback) < EPSILON:
        attr.value_feedback = 0.0
```

**Lý do chọn cách này:**

1. **Clean separation** — kernel chỉ lo dynamics, framework lo numerical cleanup. Không nhét logic snap vào trong kernel.
2. **Universal** — mọi kernel hiện tại và tương lai tự động hưởng lợi, không cần code thêm.
3. **Không phá interface** — không thêm field nào vào kernel state, không đổi signature.
4. **Configurable per-tag nếu cần** — `<params epsilon="0.001"/>` cho phép tag-level override; mặc định framework dùng `1e-3`.
5. **Math-friendly** — snap-to-zero ở biên độ rất nhỏ không thay đổi semantics động học, chỉ loại bỏ residual số học.

**Triển khai:** 3 dòng code trong `FeedbackController.step()` ở Giai đoạn C. Không sửa kernel nào.

### 9.3 Phát hiện #2 — Discrete reset settle sạch hơn continuous decay

**Hiện tượng:** `refractory_threshold` settle về < 1e-4 trong cùng số cycle, không cần snap-to-zero. Lý do: exponential decay với τ=8 + không có signal mới sau cycle 20 → x_pp giảm theo `e^(-80/8) ≈ 3e-5`, nhanh hơn nhiều so với linear decay λ=0.10.

**Bài học cho framework:** không cần "fix" kernel này — discrete reset (refractory clock cắt signal hoàn toàn khi clock > 0) là một dạng absorption tự nhiên không có ở continuous kernel.

**Không kéo logic refractory vào sigmoid kernel** — YAGNI. Mỗi kernel giữ dynamics riêng, framework dùng dead-zone (9.2) như cleanup chung. Khi nào có lamina thực sự cần combine 2 cơ chế, viết kernel thứ 3 (vd `sigmoid_refractory`), không monkey-patch kernel cũ.

### 9.4 Tổng kết tác động vào plan

| Section trong plan | Thay đổi |
|---|---|
| §3.1 (extension points) | Không đổi |
| §3.2 (default kernels) | Không đổi |
| §5 Giai đoạn C | Thêm 3 dòng dead-zone snap-to-zero trong `FeedbackController.step()`. Mặc định `EPSILON = 1e-3`. Hỗ trợ per-tag override qua `params.epsilon`. |
| §5 Giai đoạn E | Settling assert có thể dùng `feedback_norm < 1e-3` thay vì `< 1e-6` — phù hợp với epsilon framework. |
| §7 câu hỏi mở | Q4 (tolerance rebound) → đã giải qua dead-zone snap (mục 9.2). |

**Không có breaking change.** Cấu trúc, interface, XML schema giữ nguyên 100%.

---

*Cuối tài liệu. Bản này là spec để bắt đầu code giai đoạn A.*
