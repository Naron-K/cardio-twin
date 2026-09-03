# Permeability Gates & Inter-Lamina Coupling — Kế hoạch triển khai

> **THAY THẾ MỘT PHẦN — đọc [`GATE_CHANNELS_PLAN.md`](GATE_CHANNELS_PLAN.md) trước.**
>
> Sau checklist của GS Lee (2026-09-02), cái van đặt *giữa* hai lamina đã được
> chuyển vào **màng của từng lamina**, mỗi bên một bộ cổng. Kế hoạch đó đã
> triển khai xong Phase 0–5.
>
> **Cái bị thay thế:**
> - `PermeabilityGate` — **đã xoá**. Thay bằng `Channel` + `AutoGate` +
>   `KeyGate`. Không có alias: một body v1 chạy "gần đúng" trên container hai
>   phía là loại lỗi khó thấy nhất.
> - `controller="threshold|key"` — **đã xoá**. Auto gate và key gate là hai
>   thực thể riêng, vì chỉ một trong hai được phép tắt và chỉ một được phép
>   bỏ qua phần cấu hình còn lại.
> - Schema `<permeability_gates>` — bị parser **từ chối**, kèm thông báo chỉ
>   sang `<channels>`.
> - `<transfer>` — `rate` / `on_close` / `confidence` / `band` chuyển sang
>   **cổng phía nhận**; `time_delay` chuyển sang **channel**, vì độ trễ là
>   tính chất của sợi dây chứ không của đầu nào.
>
> **Cái vẫn đúng và vẫn được dùng:** mọi con số đo trong file này. Chúng là
> baseline mà `backend/tests/fixtures/gate_traces_v1.json` chụp lại, và
> `test_channels_baseline.py` chứng minh thiết kế hai phía tái tạo đúng
> 1800/1800 giá trị tới 12 chữ số thập phân. Ngưỡng, deadband, EWMA, phép đo
> chatter — không đổi một số nào.


Viết 2026-08-25, sau buổi họp với GS Lee (yêu cầu 5 mục) và vòng phản biện
thiết kế. Baseline lúc viết: nhánh `universal-visualisation`, **99/99 test
backend xanh** (`cd backend && python -m pytest tests/ -q`).

Phase 0 độc lập với các phase sau; Phase 1→5 tuần tự; Phase 6 song song từ
sau Phase 4.

**Trạng thái 2026-08-26: mọi phase XONG. 244/244 test backend xanh**
(`cd backend && python -m pytest tests/ -q`); frontend `tsc` + `eslint` +
`vite build` sạch. Ghi chú kết quả nằm ngay đầu mỗi phase bên dưới, kèm mọi
chỗ thực tế đo được khác với plan — đọc những chỗ đó trước, vì chúng là phần
duy nhất plan này chưa biết lúc viết.

---

## Các quyết định thiết kế đã chốt (không mở lại)

| # | Quyết định | Lý do ngắn |
|---|---|---|
| G1 | Giá trị liên-lamina vào **X′** với source mới `INTER_LAMINA`, không vào X″ | X″ thuộc sở hữu vòng feedback *nội bộ* lamina; "sensor sacred" chỉ đứng vững nếu input ngoài-lamina nằm phía external. Khớp mô hình System-of-Twinned-Systems (OmniBioTwin, arXiv 2606.11264) |
| G2 | Key Controller = **khớp-trong-dung-sai** trên không gian chuẩn hoá [0,1] | Dữ liệu thực nhiễu → khớp chính xác số thực không bao giờ xảy ra; không gian [0,1] giữ key trung tính miền |
| G3 | Auto Controller **bắt buộc hysteresis** (2 ngưỡng, `close_below < open_above`) | Một ngưỡng đơn sẽ chatter quanh ngưỡng vì feed có nhiễu Gaussian chủ đích |
| G4 | Gate schema có `rate` (EWMA) + `time_delay` từ v1 | Đồng bộ đa thang thời gian; lọc thông thấp là tuyến chống dao động chính giữa 2 vòng feedback giằng co qua gate mở |
| G5 | Giao tiếp liên-lamina **chỉ** qua composite nguồn; đích là attribute `INTER_LAMINA` | Yêu cầu mục 2 của Lee; enforce lúc parse |
| G6 | Gate **mặc định đóng** | Đóng = ổn định (ẩn dụ van nồi áp suất); chống chaos bằng cấu trúc |
| G7 | Key **tĩnh** ở v1 + telemetry drift; key thích nghi là v2 theo pattern vòng chậm MIT-rule | Đo drift trước khi chữa drift. KHÔNG dùng GNN — hộp đen phản triết lý XML-declared, và tự mâu thuẫn với chính cảnh báo identifiability |
| G8 | Mọi tham số học được phải khai trong XML kèm clamp ("quy tắc ADN") | Chống khủng hoảng định danh khi số tham số học được tăng (hiện tại chỉ ~10: gain + operating_point × 5 outcome) |
| G9 | Attribute `INTER_LAMINA` chưa ghép nối thì nghỉ ở `<baseline>` đã khai | Lamina chạy standalone giữ nguyên hành vi hôm nay; snapshot ghi nguồn là "baseline (uncoupled)" |

Thuật ngữ: "Auto Controller" / "Key Controller" của Lee đặt tên code là
`ThresholdGateController` / `KeyGateController` — vì "Auto Controller" trong
code đã có nghĩa khác (vòng học trọng số `auto_adjust_weights`, đóng băng D17).

---

## Phase 0 — Trả nợ 3 lỗi lamina hô hấp tìm ra (docs/laminae.md)

**XONG 2026-08-25.** 0-A, 0-B, 0-C đều đã làm; 119/119 test xanh (99 baseline
+ 20 mới trong `backend/tests/test_phase0.py`). Ràng buộc "0-A trước Phase 5"
đã thoả. Ghi chú kết quả nằm ngay trong từng mục dưới đây.

Làm lúc nào cũng được, nhưng **0-A phải xong trước Phase 5**.

### 0-A. Polarity theo target thay vì theo tag

Hiện trạng: dấu nằm trên `<tag>`, nên tag đa-target như `PACO2_DEVIATION`
(targets: `ventilation_state` ×1.0 và `gas_exchange_state` ×0.4) buộc dùng
một dấu cho hai composite có chiều ghép nối khác nhau.

| Việc | File | Chi tiết |
|---|---|---|
| Schema | `*_lamina.xml` | `<target address="..." weight="..." polarity="positive"/>` — vắng mặt thì **kế thừa dấu của tag** → mọi XML cũ chạy y nguyên |
| Dataclass | `universal_twin.py` (~dòng 434) | `TagTarget.polarity: Optional[float] = None` |
| Parser | `_parse_tags` (~dòng 1189) | chỉ gọi `resolve_polarity` khi attribute có mặt — LƯU Ý `resolve_polarity(None)` trả −1.0, không được gọi vô điều kiện |
| Controller | `_resolved_targets` (feedback_controller.py ~dòng 142) | trả `(comp_id, weight, polarity_hiệu_lực)`; `_build_kernel_params` nhận polarity làm tham số thay vì luôn đọc `tag.polarity` |
| Monitor-only | feedback_controller.py | giữ check `tag.polarity == 0` cấp tag; thêm skip cấp target khi target polarity = 0 |
| Kiểm chứng | `respiratory_lamina.xml` | khai dấu tường minh cho 2 target của PACO2_DEVIATION. **Đo trước khi chốt dấu**: chạy kịch bản ép hypoventilation, xem X″ trên gas_exchange_state sửa hay khuếch đại (đúng quy trình đã đo gain 0.7) |
| Docs | `docs/laminae.md` | sửa đoạn "That is a change to the feedback design and it is not made here" |

Test: kế thừa mặc định; dấu riêng được parse; kernel nhận đúng dấu theo
target; 99 test cũ giữ xanh.

**Kết quả đo (25 chu kỳ, ép hypoventilation RR 7 / V_T 300, PaCO2 khởi điểm
164 mmHg, chỉ đổi dấu của target `gas_exchange_state`):**

| dấu target | PaCO2 cuối | PaO2 cuối | A-a cuối |
|---|---|---|---|
| positive | 44.65 | 93.12 | 4.73 |
| negative | 44.65 | 87.84 | 2.13 |
| 0 | 44.65 | 90.48 | 3.43 |

PaCO2 **giống hệt tới số lẻ cuối** ở cả ba. Bắt buộc phải vậy:
`PaCO2 = 0.863·VCO2/V_A` chỉ đọc VCO2 và V_A, mà `gas_exchange_state` không
chứa cái nào. Ghép nối là thật nhưng **một chiều** — phương trình khí phế nang
mang PaCO2 vào PAO2, không mang ngược — và chuỗi tính đã tự truyền rồi (PAO2
leo từ −55.75 lên ~94 ở cả ba run, chỉ nhờ hiệu chỉnh của V_A). Dấu ở target
đó là cộng X″ chồng lên một hiệu chỉnh đã tới nơi.

Chốt: `ventilation_state` → `polarity="positive"` (khai tường minh),
`gas_exchange_state` → `polarity="0"`. Target vẫn khai vì ghép nối đáng nói,
nhưng không tác động vì nó không thể — đúng tiền lệ `AA_MONITOR`.

Thêm một rule fail-fast không có trong plan gốc: tag `polarity="0"` mà target
khai dấu khác 0 → ValueError lúc parse. Check cấp tag short-circuit trước khi
đọc target, nên khai như vậy sẽ nằm trong XML trông như có hiệu lực mà không
làm gì.

### 0-B. Ràng buộc trên giá trị NHÌN THẤY, sau coupling

Lỗi gốc: hàm floor V_A ở 0.05 nhưng màn hình hiện −2.88 vì X″ cộng vào SAU
guard của hàm (A-a gradient tương tự: clamp 0 trong code, hiển thị −2.69).

Quy tắc (chỉ dùng dữ liệu đã khai, trung tính miền) — khoảng cho phép =
physio range **mở rộng để chứa X′**:

```
lo = min(physio_min, X′);  hi = max(physio_max, X′)
X″ ← clamp(X″, lo − X′, hi − X′)
```

Hai tính chất bắt buộc (mỗi cái một test):

1. X′ bệnh lý ngoài dải (MAP 120 > max 110) vẫn hiện nguyên — không lặp lại
   lỗi soft_range che bệnh đã sửa 2026-06-23.
2. Feedback không bao giờ tạo giá trị phi vật lý (V_A âm, A-a âm).

Vị trí: `Attribute.apply_feedback()` (~dòng 160) — choke point mà cả step 5
của controller lẫn đường restore kernel-state đều đi qua. Controller phát
hiện clamp bằng so tổng đã yêu cầu với `attr.value_feedback` thực nhận, log
`FB WARN: X'' clamped on <attr>`. Chấp nhận lệch giữa kernel state `x_pp` và
giá trị áp thực — tiền lệ `rollback_feedback`; dead-zone snap sẽ dọn.

**Sửa thêm khi làm (plan gốc đoán sai một chỗ):** snap KHÔNG dọn được trường
hợp clamp ghim vĩnh viễn ở 0, vì điều kiện snap loại trừ `value_feedback` đã
bằng 0.0. Đo trên ca shunt (FiO2 0.9 + SpO2 85% → A-a ≈ 540 mmHg trên max
khai báo 80): `PF_DEVIATION` liên tục đòi nới rộng A-a, clamp từ chối mỗi chu
kỳ, `x_pp` bão hoà ở ~21 và nằm đó mãi — X′ mà quay lại trong dải là dồn 21
mmHg vào một bước. Nay snap nhận thêm các attribute bị clamp ghim ở 0. Cảnh
báo vẫn kêu mỗi chu kỳ, và đúng là nên kêu: vòng lặp thật sự vẫn đang đòi thứ
mô hình nói là không thể.

### 0-C. Attribute tính hỏng phải bị đánh dấu

| Việc | File | Chi tiết |
|---|---|---|
| Twin | `universal_twin.py` | `self.failed_attributes: dict[str, str]` (id → lý do); xoá đầu `compute_all()`; ghi ở cả 2 nhánh lỗi trong `_resolve()` (ERROR computing + No function registered) |
| Snapshot | `snapshot.py` | mỗi entry computed thêm `"stale": bool`, `"error": str \| null` |
| REST | `_run_simulation` (main.py) | thêm cùng 2 trường — endpoint này build dict riêng, không dùng snapshot.py |
| Frontend | `useCardioStream.ts` + đúng MỘT chỗ render giá trị computed | stale → mờ + badge; không đụng gì khác |

Test: ép một hàm raise (vd `r = 0` → `_calc_resistance` raise) →
`failed_attributes` chứa R, snapshot có `stale: true`.

### Loại trừ chủ đích khỏi Phase 0

Lỗi thứ nguyên của R (MODEL_SPEC.md §5): sửa nó kéo theo tái hiệu chuẩn
(R đúng ≈ 110 rơi ngoài gate [10,40] của chính mô hình; cần dời cả r baseline
lẫn gate). Task riêng, làm cùng domain expert.

---

## Phase 1 — Hợp đồng schema (viết XML trước, code sau)

**XONG 2026-08-25.** 151/151 test xanh (thêm 31 test trong
`backend/tests/test_organism.py`). Đã giao: source `INTER_LAMINA` +
`set_inter_lamina()`, `backend/organism.xml`, `backend/organism.py` (dataclass
+ parser + 5 rule fail-fast), mục `inbound` trong snapshot và REST, và phần UI
tối thiểu để lamina standalone giữ nguyên hành vi như G9 hứa.

Ba chỗ phải làm thêm mà plan không liệt kê, đều là hệ quả trực tiếp:

1. **`_resolve()` phải coi INTER_LAMINA như input.** Nó không có
   `computed_by`, nên rơi vào nhánh "No function registered" — và sau 0-C thì
   nhánh đó *đánh dấu stale*. CO_ref sẽ hiện gạch ngang vì tội là input.
   Đổi check `source == "SENSOR"` thành `source in EXTERNAL_SOURCES`.
2. **Seed baseline lúc parse.** `SimulatedSource` lọc theo `SENSOR` nên
   không sinh số cho CO_ref (đúng ý plan) — nhưng thế thì không ai seed nó,
   `value` = None, và cả chuỗi dưới seam tắt. G9 nói "nghỉ ở `<baseline>`";
   chỗ duy nhất làm được là lúc parse.
3. **Frontend phân loại lại.** `computed` lọc `source !== 'SENSOR'`, nên
   CO_ref sẽ nhảy vào panel "Model output" như một giá trị mô hình tự tính.
   Đổi thành `=== 'PRELIMINARY'` + thêm nhóm `inbound`, render read-only
   (không slider) kèm dòng provenance.

Một quyết định vượt ngoài plan: `inbound` là **key riêng** trong snapshot,
không nhập vào `sensors`. Lý do: "sensor" mang một khẳng định cụ thể (đo
được, từ thiết bị, bất khả xâm phạm vì là ground truth); nới nó thành "mọi
thứ tôi không tự tính" là xoá đúng cái ranh giới mà G1 dựng lên.

Và một phát hiện: **không composite nào trong hai lamina hiện chứa attribute
INTER_LAMINA**, nên rule bỏ-qua-không-phải-PRELIMINARY hiện chưa bảo vệ gì
thật. Test dựng tình huống trong bộ nhớ thay vì sửa XML — thêm CO_ref vào
`transport_state` là đổi mô hình (trọng số phân phối, fan-out của
DO2_DEVIATION), quyết định của domain expert chứ không phải của Phase 1.

### 1a. Source mới `INTER_LAMINA`

`CO_ref` (respiratory) đổi `SENSOR` → `INTER_LAMINA`. Description của nó
trong XML đã viết sẵn: "this is the seam where lamina_circulatory's computed
CO attaches". Hệ quả dây chuyền:

- `set_sensor()` từ chối nó; thêm `set_inter_lamina(attr_id, value,
  confidence, provenance)` ghi X′.
- Quy tắc feedback-bỏ-qua-sensor (feedback_controller.py, chỗ
  `attr.source == "SENSOR"` trong step 3) đổi thành *bỏ qua mọi source ≠
  PRELIMINARY* — X′ ngoài-lamina cũng bất khả xâm phạm.
- `SimulatedSource` tự động không sinh số cho nó (lọc theo
  `list_attributes("SENSOR")`) → standalone mất CO_ref → áp dụng G9: chưa
  ghép nối thì nghỉ ở `<baseline>` đã khai (5.0), snapshot ghi
  "baseline (uncoupled)".

### 1b. File cấp BDT: `backend/organism.xml`

Topology liên-lamina không thuộc về lamina nào → file riêng (tiền lệ:
`ingestion_manifold.xml`).

```xml
<organism id="bdt_default" version="1.0">
  <laminae>
    <lamina id="lamina_circulatory" />
    <lamina id="lamina_respiratory" />
  </laminae>

  <permeability_gates>
    <gate id="pg_co_to_resp"
          from="lamina_circulatory:pump_state"     <!-- CHỈ composite được làm nguồn (G5) -->
          to="lamina_respiratory:CO_ref"            <!-- đích là attribute INTER_LAMINA -->
          controller="threshold">
      <extract attribute="CO" />                    <!-- attribute nào của composite lên dây -->
      <controller_params
          watch="CO" aggregate="attr"               <!-- attr | mean | max trên vector chuẩn hoá -->
          open_above="0.75" close_below="0.60"      <!-- HYSTERESIS (G3), đơn vị [0,1] -->
          refractory_cycles="5" />
      <transfer mode="proportional"
          rate="0.2"                                <!-- EWMA mỗi chu kỳ bên nhận (G4) -->
          time_delay="0"                            <!-- tính bằng chu kỳ bên NHẬN -->
          on_close="hold"                           <!-- hold | decay_to_baseline -->
          confidence="0.8" />
    </gate>
  </permeability_gates>
</organism>
```

Key controller cùng khung, khác controller:

```xml
<gate id="..." controller="key">
  <!-- release_below thêm ở Phase 3 sau khi đo: key một ngưỡng chatter
       148 lần / 400 chu kỳ. Rule 4 nay áp cho cả hai controller. -->
  <key metric="weighted_distance" match_threshold="0.9" release_below="0.85">
    <weight attribute="SBP" ref="0.65">1.0</weight>   <!-- điểm tham chiếu trong [0,1] -->
  </key>
  <transfer mode="band" band_min="..." band_max="..." />
</gate>
```

### 1c. RULES — "ADN" enforce lúc parse (fail-fast)

1. Gate mặc định đóng (G6).
2. Nguồn liên-lamina chỉ được là composite (G5).
3. Đích phải là attribute `INTER_LAMINA` — ghi vào SENSOR/PRELIMINARY của
   lamina khác → ValueError lúc parse.
4. `close_below < open_above` bắt buộc — không hysteresis = không parse.
5. Mọi tham số học được phải khai kèm clamp (G8).

---

## Phase 2 — Container đa lamina: `backend/organism.py`

**XONG 2026-08-25.** 173/173 test xanh (thêm 22 test trong
`backend/tests/test_organism_tick.py`). Đã giao: `Organism` (twins,
controllers, gates, `_gate_state`), thứ tự tick chốt cứng một chỗ,
`Organism.seed()`, breaker cấp cơ thể, `OrganismSession` trong `session.py`,
và socket cho cơ thể. `Session` một-lamina **không đổi một dòng**.

Hai chỗ lệch khỏi plan, cả hai đều có lý do cụ thể:

1. **Plan sai về độ trễ** — xem ô đánh dấu ở bước 3 dưới đây. Đo được bên
   nhận dùng giá trị ngay trong cùng tick. Code và test nói đúng sự thật đó.
2. **Endpoint riêng `/ws/organism`, không phải `?organism=` trên
   `/ws/feedback`.** Hai payload khác hẳn hình dạng (lồng theo lamina so với
   phẳng), và message điều khiển cũng khác (`set_sensor` phải kèm `lamina`,
   vì trên một cơ thể "set HR" là mơ hồ). Cho client phát hiện điều đó *từ
   câu trả lời* là kiểu lỗi trông như đang chạy được. Đổi lại thì dễ nếu bạn
   muốn đúng chữ của plan.

Gate hiện **luôn đóng** vì registry controller rỗng (Phase 3 mới đổ vào) —
và đó không phải chỗ trống tạm, mà đúng trạng thái nghỉ đã khai (G6). Nhờ
vậy tiêu chí nghiệm thu số 2 của Phase 5 ("organism với gate chưa từng mở
cho kết quả GIỐNG HỆT hai lamina standalone") **kiểm được ngay bây giờ**,
trước khi gate biết mở, chứ không phải sau.

```python
class Organism:
    twins:       dict[str, UniversalTwin]        # id → twin (qua laminae.load_twin)
    controllers: dict[str, FeedbackController]   # một controller/lamina, như cũ
    gates:       list[PermeabilityGate]          # parse từ organism.xml
    _gate_state: dict[str, dict]                 # state controller cổng — Ở ĐÂY,
                                                 # không trên dataclass (tiền lệ _kernel_state)
```

**Thứ tự một tick — chốt cứng, một chỗ, comment kỹ** (chỗ dễ cãi nhất):

1. Ghi sensor cho mọi lamina
2. `compute_all()` mọi lamina
3. **Gate pass**: đọc giá trị SAU compute của bên gửi → buffer delay → EWMA
   → ghi X′ bên nhận
4. `controller.step()` mọi lamina

~~Giá trị truyền tick này được bên nhận DÙNG ở tick sau — độ trễ 1 chu kỳ là
sàn của `time_delay`, chấp nhận và ghi vào docs (chính nó là cơ chế chống
giằng co rẻ nhất).~~

**SAI — đo được ngược lại 2026-08-25.** Bên nhận dùng giá trị **NGAY trong
tick đó**, không phải tick sau. Lý do: step 4 là `FeedbackController.step()`,
mà việc cuối cùng của nó là `compute_all()` lần nữa. Gate ghi ở step 3, chuỗi
bên nhận dẫn lại từ đó vài dòng sau, trong cùng một tick. Đo trên mối nối
CO → CO_ref: DO2 nhảy 988.42 → 1043.77 ngay tại tick giá trị vượt qua.

Hệ quả cho Phase 4: **không có độ trễ ngầm 1 chu kỳ nào để dựa vào** —
`time_delay=0` nghĩa là bằng 0 thật. EWMA `rate` là *toàn bộ* tuyến chống dao
động, đúng như G4 vốn đã nói, chứ không phải "thêm một lớp nữa".

Cái thật sự trễ một nhịp là **phía gửi**: gate đọc giữa step 2 và step 4, nên
giá trị mang X′ của chu kỳ này cộng X″ của chu kỳ *trước*. Đó là cái giá của
việc chạy gate trước các vòng feedback thay vì sau — phương án ngược lại đưa
cho bên nhận một con số mà vòng lặp bên gửi đã kịp phản ứng rồi.

Circuit breaker toàn cục: `Σ feedback_norm` các lamina + cap độ lớn truyền
qua gate; vượt → đóng mọi gate + log. KHÔNG rollback nội bộ lamina — breaker
cục bộ của từng lamina tự lo phần nó.

`Session` một-lamina **không đổi một dòng**. Thêm `OrganismSession` song
song; WS nhận `?organism=` cạnh `?lamina=`.

---

## Phase 3 — Hai gate controller (registry trong organism.py)

**XONG 2026-08-25.** 198/198 test xanh (thêm 24 test trong
`backend/tests/test_gate_controllers.py`). Cả hai controller đăng ký sẵn trong
`Organism.__init__`, đúng pattern `UniversalTwin._register_default_*`.

**Deadband đo được, không phải khẳng định suông.** Cho controller ăn một chuỗi
400 mẫu đậu ngay trên ngưỡng (0.75 ± 0.02):

| cấu hình | transitions / 400 |
|---|---|
| một ngưỡng (`close_below=0.7499`) | **205** |
| band hẹp 0.74–0.75 | 163 |
| band 0.60–0.75 như đã khai | **1** |

Phải đo *tách khỏi mô hình*: bên trong organism, vòng feedback của bên gửi kéo
giá trị ra khỏi biên nên không dựng được gate chatter ở đó — một tính chất tốt
của mô hình và là một tính chất vô dụng cho test muốn chứng minh deadband.

**Rule 4 nay áp cho cả key controller, vì đo ra chứ không phải vì đối xứng.**
Key gate ban đầu viết một ngưỡng `match_threshold`, lý lẽ là "match vốn đã là
dung sai rồi". Đo trên feed nhiễu với match đậu ngay trên ngưỡng (0.9150 so
với 0.90): **148 lần lật mở/đóng trong 400 chu kỳ**. Thêm `release_below`, bắt
buộc, `release_below < match_threshold` enforce lúc parse. Không XML nào đang
dùng `key` nên không phá gì.

Telemetry drift có từ v1 (G7): mỗi lần đánh giá ghi `distance`, EWMA của nó,
`distance_first`, min/max, và `drift = ewma − first`. Test hai chiều — key
trôi thì `drift` phải hiện, key ổn định thì phải im, vì telemetry lúc nào cũng
kêu "đang trôi" thì không nói lên gì.

Gate đã khai (`watch=CO`, mở ≥0.75) chạy đúng đầu-cuối: HR 72 → CO_norm 0.275
đóng; HR 100 → 0.46 vẫn đóng; HR 200 → vượt ngưỡng, mở, CO_ref nhảy 5.00 →
9.85.

**Một lỗi Phase 3 tự tạo ra và đã vá luôn, không đẩy sang Phase 4.** Trước
Phase 3 không gate nào mở được nên không gì cũ đi được. Ngay khi mở được, một
gate mở rồi đóng để lại cho bên nhận giá trị cuối cùng đã vượt qua — và
snapshot khai `state: coupled, open_fraction: 1.0, age: 0`, tức một số đo sống
từ một cái van đang đóng. Đo được: CO_ref đậu ở 8.73 tự nhận là hiện tại trong
khi tuần hoàn đã về 4.84. Đó đúng là con bug lâu đời nhất của dự án đội mũ
mới, nên không được phép ship một phase rồi vá ở phase sau. Nay provenance
chuyển sang `state: "held"`, `open_fraction: 0.0`, và `age` đếm lên mỗi chu kỳ.
Việc *chọn* `hold` hay `decay_to_baseline`, ring buffer trễ và EWMA vẫn là
Phase 4 — cái vá ở đây chỉ là nói thật về mặc định `hold`.

Chữ ký đóng băng, đúng phong cách các kernel hiện có:

```python
controller(state: dict, source_vec: dict[str, float], params: dict) -> dict
# bắt buộc trả {"open_fraction": float trong [0,1], ...phần còn lại là state}
```

- **`threshold`** (`ThresholdGateController` — "Auto" của Lee): máy trạng
  thái 2 ngưỡng + refractory. Đóng→mở khi `watch ≥ open_above`; mở→đóng khi
  `≤ close_below`. `open_fraction` nhị phân, hoặc sigmoid mượn nguyên toán
  conductance của gate `soft_range` (universal_twin.py, validate_gates) cho
  chế độ tỷ lệ.
- **`key`** (`KeyGateController` — "Key" của Lee): khoảng cách có trọng số /
  cosine tới vector tham chiếu trong [0,1], khớp-trong-dung-sai (G2). **Kèm
  telemetry drift từ v1**: log khoảng cách mỗi lần đánh giá — dữ liệu để
  quyết định key thích nghi (G7) có cần không, thay vì đoán.

Cả hai stateful; state nằm trong `Organism._gate_state`, serialisable để lên
snapshot.

---

## Phase 4 — Transfer engine

**XONG 2026-08-25.** 219/219 test xanh (thêm 19 test trong
`backend/tests/test_transfer.py`). Ba tầng: ring buffer trễ → EWMA → ghi qua
`set_inter_lamina` kèm provenance đầy đủ. Cộng `mode="band"` và cả hai
`on_close`.

**Một chỗ cố ý làm khác plan.** Công thức trong plan nhân `open_fraction` vào
**giá trị**: `delayed_value · f(open_fraction)`. Với một đại lượng sinh lý thì
sai — gate mở nửa sẽ báo cung lượng tim 2.4 L/min cho một quả tim đang chạy
4.8, đó không phải "đọc được một nửa" mà là đọc sai. Nay nó vào **rate**: gate
mở nửa thì tiến về giá trị thật với nửa tốc độ, đúng cái mà cái van nửa mở
làm. Với gate đang ship thì hai cách giống hệt nhau (binary mode chỉ ra 0 hoặc
1); khác biệt chỉ có ở gate proportional — tức đúng chỗ mà giá trị bị scale sẽ
gây hại.

**EWMA làm đúng việc G4 giao** (giữ HR 200 để vòng feedback tuần hoàn tự làm
CO dao động):

| rate | CO_ref qua 4 chu kỳ |
|---|---|
| 1.00 | 13.20 → 7.13 → 14.91 → 10.62 |
| 0.20 | 6.64 → 6.74 → 8.37 → 8.82 |

rate 1.0 là sợi dây, truyền nguyên cuộc cãi vã của bên gửi sang.

**Một bug tìm ra khi đo, không phải khi đọc code.** `time_delay=1` và `3`
**không bao giờ giao gì cả**. Nguyên nhân: hợp đồng của gate controller là
"giá trị trả về LÀ toàn bộ state mới", nên container thay nguyên dict mỗi chu
kỳ — và xoá luôn ring buffer của transfer engine nằm chung dict. Nay tách
`_gate_state[gate.id]` thành `{"controller": {...}, "transfer": {...}}`, hai
chủ sở hữu không với được vào key của nhau. Sau khi sửa, `time_delay=3` giao
đúng chuỗi cũ dịch đi 3 chu kỳ.

**`mode="band"` từ chối chứ không clamp.** Clamp chính là việc gate
`soft_range` từng làm và đã bị sửa 2026-06-23: nó âm thầm kéo sinh lý ngoài
dải về "bình thường", MAP 120 hiện thành 110, che đúng cái bệnh mà twin sinh
ra để chỉ. Từ chối nói "mối nối này không mô hình hoá cái đó" — đúng; clamp
nói "nó là 6.0" — sai.

Và một bug nữa của chính mình: `decay_to_baseline` ban đầu ghi provenance cả
khi **chưa từng có gì vượt qua**, biến một baseline chưa ai đụng thành thứ
trông như giá trị coupled đã suy giảm. Gate chưa từng chở gì thì không được
nhận công gì.

- Ring buffer dài `time_delay` chu kỳ bên nhận, mỗi gate một buffer.
- `transmitted ← transmitted + rate · (delayed_value · f(open_fraction) − transmitted)`
  — lọc thông thấp là tuyến phòng thủ chống dao động chính (G4).
- Đóng cổng: `hold` giữ giá trị cuối (provenance stamp tuổi) hoặc
  `decay_to_baseline`.
- Ghi qua `set_inter_lamina(...)`; snapshot mang provenance: gate id, lamina
  nguồn, tuổi giá trị, open_fraction hiện tại.

---

## Phase 5 — Mối nối sống đầu tiên: CO → CO_ref

**XONG 2026-08-26.** 229/229 test xanh (thêm 8 test trong
`backend/tests/test_seam.py` — file riêng theo lệ mỗi phase một file kể từ
Phase 1, chứ không nhét vào `test_organism.py` vốn nói về rule schema).

**Tiêu chí 1 như plan viết là sai cả hai vế, và đo mới biết.**

1. **EDV không phải cần gạt lên CO ở trạng thái dừng.** Vòng feedback tuần
   hoàn có outcome `target_co = 5.0 ± 1.5`, nên nó tiêu đúng ngân sách hiệu
   chỉnh để dọn dẹp chính cái nhiễu mà test đang áp. Đo: ép EDV 60 suốt 40 chu
   kỳ → CO đậu ở **5.97**, *cao hơn* lúc đầu. EDV 240 → CO 4.14 (ngược chiều
   trực giác). HR mới là cần gạt trung thực, vì đó là sensor bị ép mà vòng lặp
   không ghi ngược vào được.

2. **Gate đã khai không thể mở cho CO tụt.** Nó canh CO chuẩn hoá thô so với
   một ngưỡng cao duy nhất (0.75 ≈ CO 9.5 L/min): mở cho tim đập nhanh, đóng
   im cho tim suy. Đo, giữ HR 35: CO đậu ở **3.39 L/min**, seam không mở lần
   nào, và hô hấp cứ tính DO2 từ baseline 5.0 — **sai 32%, âm thầm, đúng
   chiều mà lâm sàng quan tâm nhất**. Một cái van tự mô tả là "đóng khi bơm
   không có gì đáng nói" mà coi sốc là không đáng nói thì đang canh một nửa
   chủ đề của chính nó.

**Sửa: thêm `aggregate="deviation"` — trung tính miền, ở [0,1].** Khoảng cách
tới một `reference` khai tường minh, nên lệch **cả hai chiều** ra cùng một
con số và một cặp ngưỡng phủ cả hai. `reference="0.30"` là baseline
CO_ref (5.0) của chính *bên nhận*, đổi sang không gian chuẩn hoá của bên gửi:
gate mở đúng lúc thực tế thôi khớp với điều bên kia đang giả định.

Hai biên **suy ra, không phải chọn theo cảm giác**:

| biên | giá trị | suy từ đâu |
|---|---|---|
| `open_above` | 0.125 | dung sai của bên nhận: `target_do2 = 1000 ± 250`, `DO2 = CaO2·CO_ref·10`, CaO2 đo được 19.80 → sai số CO đẩy DO2 ra khỏi dải là 250/198.0 = **1.262 L/min = 0.126 chuẩn hoá** |
| `close_below` | 0.09 | nhiễu đo được: sd của CO_norm trên feed sống là 0.0104; deadband 0.035 = **3.4 sd** |

Chatter, tín hiệu đậu ngay trên `open_above`, 400 chu kỳ (cùng phương pháp
Phase 3 — đo *tách khỏi* mô hình):

| close_below | bề rộng band | transitions |
|---|---|---|
| 0.1249 (một ngưỡng) | 0.0001 | **177** |
| 0.115 | 0.010 | 91 |
| 0.100 | 0.025 | 3 |
| **0.090 (đã khai)** | **0.035** | **1** |

Kết quả sau khi sửa — cùng một gate, hai chiều:

| ép | CO đậu | deviation | gate | DO2 |
|---|---|---|---|---|
| nghỉ (HR 72) | 4.75 | 0.025 | đóng | 988 |
| HR 90 | 5.94 | 0.094 | đóng (trong deadband) | — |
| HR 110 | 6.36 | 0.136 | **mở** | ↑ |
| HR 200 | 10.17 | 0.517 | **mở** | 1226 |
| **HR 35** | **3.39** | **0.161** | **mở** | **860** |

Và điều đáng giá hơn con số: ở HR 30, DO2 tụt qua sàn dung sai của chính
lamina hô hấp, nên **vòng feedback của nó bắt đầu phản ứng**. Không phải "một
con số đã chạy", mà là "một phán xét đã đổi" — đó mới là lý do mối nối đáng
có.

Tiêu chí 3 cũng phải viết lại: "settle" là **biên độ co lại**, không phải mức
giảm. Hai chiều đi tới đó bằng hai cách và cả hai đều đã settle — HR 200 đạt
đỉnh 0.046 rồi tắt dần; HR 35 leo chậm tới 0.0026 rồi phẳng. Khẳng định "đỉnh
cuối thấp hơn đỉnh đầu" chỉ đúng cho một trong hai, và nó đo hình dạng của
quá độ chứ không đo hội tụ.

4 tiêu chí nghiệm thu:

1. **Ghép có tác dụng**: hạ EDV bên tuần hoàn → CO tụt → gate mở → DO2 hô
   hấp tụt trong ≤ N chu kỳ.
2. **Đóng mặc định**: organism với gate chưa từng mở cho kết quả GIỐNG HỆT
   hai lamina standalone (so snapshot).
3. **Không giằng co**: cả hai vòng feedback bật + gate mở → norm toàn cục
   settle (tái dùng pattern test settling Phase E).
4. **Không hồi quy**: 99 test baseline xanh nguyên.

Vì sao 0-A phải xong trước phase này: CO→DO2 là quan hệ THUẬN, nhưng mối nối
thứ hai bất kỳ (vd PaCO2 → điều khiển hô hấp) đụng quan hệ nghịch ngay —
per-target polarity phải có sẵn trong khung trước khi ai đó khai mối nối đó.

---

## Phase 6 — Wire + UI (song song từ sau Phase 4)

**XONG 2026-08-26.** 244/244 test backend xanh (thêm 13 test trong
`backend/tests/test_wire.py`, 2 trong `test_streaming_runtime.py`, 1 trong
`test_phase0.py`); frontend `tsc` + `eslint` + `vite build` sạch.

Đã giao:

- **`GET /api/organism`** — cặp song sinh của `/api/schema`, một tầng trên.
  Trả cấu trúc đã *giải quyết xong* (hai biên, transfer, learnables) chứ
  không phải attribute XML thô, vì bên đọc phải vẽ một cái van và dán nhãn
  nó. Nó **load laminae** chứ không chỉ liệt kê, nên organism vi phạm rule 2
  hay 3 bị từ chối ngay ở request hỏi về cơ thể (400), chứ không phải ở tick
  đầu tiên của một socket ai đó đã mở và đang nhìn.
- **`snapshot["gates"]`** — thay cho `gate_declarations`, gộp khai báo và
  trạng thái sống vào **một** entry. Tách đôi chính là thứ khiến bên đọc phải
  đi tìm state ở chỗ khác rồi vẽ một cái van không có state. Provenance đọc
  thẳng từ **attribute bên nhận**, cùng một object mà `inbound` của lamina đó
  hiển thị — hai chỗ cùng tính một khẳng định là cách chúng trôi khỏi nhau.
- **`OrganismMap`** — lamina là hộp, gate là cạnh, **ba** trạng thái chứ
  không phải hai: `open` / `held` / `shut`. Vị trí sinh từ khai báo (cạnh
  chạy ngược được route xuống dưới, dù cơ thể đang ship không có cái nào), và
  không file nào ở đây gọi tên một lamina, attribute hay gate.
- **`BodyDashboard`** (`#body`) + `useOrganismStream` — màn hình riêng chứ
  không phải panel trên twin view: twin view hỏi *một lamina đang tính gì*,
  màn này hỏi *giá trị băng qua ở đâu*. Rail bên trái là `InputRail` cũ, một
  cái cho mỗi lamina, dựng từ schema của chính lamina đó — vì một gate đóng
  cho tới khi có gì làm nó mở, và không có cần gạt thì diagram là tranh tĩnh.

### Ba bug chỉ chạy thật mới thấy

1. **Stream chết im lặng trên Windows.** `_log` in ra stdout cp1252; câu log
   monitor-only cấp target thêm ở 0-A chứa `→` (U+2192). `print` ném
   `UnicodeEncodeError`, giết task control của `StreamingRuntime`, và để lại
   socket **mở và im**. Năm frame, rồi hết — trên màn hình không phân biệt
   được với một mô hình đã settle. Ảnh hưởng cả `/ws/feedback` lẫn
   `/ws/organism`. Sửa hai chỗ: `_log` không để lỗi mã hoá hạ cả run (log
   trong bộ nhớ vẫn giữ nguyên chữ thật, vì snapshot đọc nó); và vòng lặp
   control chết thì **chết ồn ào** — traceback ra log, exception giữ ở
   `runtime.error`. `stop()` không ném lại nó, nếu không lỗi sẽ hiện ra ở
   chỗ dọn dẹp thay vì chỗ hỏng (đúng cái đã xảy ra).
2. **CO_ref hiện 9.55 L/min kèm nhãn "baseline (uncoupled)"** — quên truyền
   `inboundProvenance` qua stream cơ thể.
3. **`InputRail` không biết trạng thái `held`.** Viết ở Phase 1, khi chưa
   gate nào mở được, nên mọi thứ khác `coupled` đều đọc thành "baseline
   (uncoupled)". Lần đầu một gate mở rồi đóng: rail ghi 5.20 L/min là baseline
   chưa ai đụng, trong khi chính seam bên cạnh ghi "held 76c". Nay ba trạng
   thái, và hai chỗ nói cùng một câu.

Cả ba đều cùng một họ với con bug lâu đời nhất của dự án: **một thứ đã chết
hoặc đã cũ trông y hệt một thứ đang sống.**

---

## Không làm (để khỏi bị cuốn)

- **Key thích nghi** — v2, theo pattern vòng chậm MIT-rule (clamp chặt,
  cadence thưa, khai trong XML), SAU KHI telemetry drift Phase 3 chứng minh
  cần. KHÔNG dùng GNN (G7).
- **Eval chuỗi `<formula>`** — viết cho người đọc, sẽ lệch âm thầm với code
  chạy thật. Biểu thức máy-đọc-được là trường mới song song, nếu cần.
- **`POST` đổi lamina/organism global của process** — tái tạo shared mutable
  state mà thiết kế lamina-per-connection vừa loại bỏ.
- **Ràng buộc bảo toàn cứng** (nâng `Q_CO_match` thành hard constraint chặn
  bước adaptation vi phạm) — ý tưởng tốt, cần quyết định thiết kế riêng,
  không trộn vào đây.
- **Tái hiệu chuẩn R** — task riêng với domain expert (xem Phase 0, loại trừ).

## Trình tự phụ thuộc

```
Phase 0 (độc lập; 0-A trước Phase 5)
Phase 1 → 2 → 3 → 4 → 5
Phase 6 song song từ sau Phase 4
```

Khối lượng lớn nhất: Phase 2 (container + thứ tự tick). Phase 3–4 nhỏ hơn vẻ
ngoài — toàn bộ pattern (registry, state ngoài dataclass, fail-fast parse) đã
có tiền lệ trong code để chép theo.

## Tham khảo

- OmniBioTwin — System-of-Twinned-Systems, arXiv 2606.11264 (multi-rate
  synchronization là một trong 7 lớp của framework này).
- Bang-bang control với hysteresis deadband — nền của ThresholdGateController.
- `docs/laminae.md` — ba bài học từ lamina thứ hai (nguồn của Phase 0).
- `MODEL_SPEC.md` §5 — hồ sơ lỗi thứ nguyên của R.
