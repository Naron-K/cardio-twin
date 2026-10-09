# Lamina Circulatory — bộ khung skeleton khi được nạp một mô hình cụ thể

> **Đọc cùng với** `skeleton-diagram-brief.md`. File kia mô tả *cơ chế*
> (domain-neutral). File này là **cùng bộ máy đó với các ô đã điền**: đây là
> những gì thực sự nằm trong `circulatory_lamina.xml` + `circulatory_lamina.py`.
>
> **Mọi con số trong file này đều được đo thật**, bằng cách nạp file XML,
> đặt mọi cảm biến về `baseline` đã khai, rồi chạy. Không có số nào phỏng đoán.
>
> Cấu trúc file này bám đúng thứ tự của file skeleton, để người vẽ đặt hai
> bản cạnh nhau và đối chiếu từng mục.

---

## 0. Vị trí trong bộ khung

```
   <lamina name="Circulatory" id="lamina_circulatory" version="2.0" level="1">
     <upper_lamina id="none"/>       <- ở organism.xml nó có hàng xóm,
     <lower_lamina id="none"/>          nhưng bản thân file thì đứng một mình
     <coupling type="additive"/>
     <behaviour_solver type="algebraic_chain" dt="1.0" unit="second"/>
     <adaptation kernel="model_free" cadence="20"> ... </adaptation>
```

- **level = 1**: đáy của stack. Trong `organism.xml` nó là bên **GỬI**, và
  không nhận gì từ ai — lamina này **không có attribute `INTER_LAMINA` nào**.
- Solver là `algebraic_chain` (một lượt, không lặp) — chuỗi hàm của nó là
  một DAG thật, không có vòng kín, nên không cần `fixed_point`.
- Coupling `additive`: `X = X' + X''`.

---

## 1. Attribute — 20 cái, 11 đo + 9 tính

Không có cái nào là `INTER_LAMINA`.

### SENSOR (11) — X' đến từ ngoài, vòng phản hồi **không bao giờ chạm**

| id | tên | đơn vị | dải khai báo | baseline |
|---|---|---|---|---|
| `SBP` | Systolic Blood Pressure | mmHg | 90 – 180 | 120 |
| `DBP` | Diastolic Blood Pressure | mmHg | 60 – 120 | 80 |
| `eta` | Blood Viscosity | mPa·s | 3.0 – 4.0 | 3.5 |
| `L` | Vessel Length | cm | 1.0 – 100.0 | 50 |
| `r` | Vessel Radius | cm | 0.01 – 1.5 | 0.15 |
| `EDV` | End-Diastolic Volume | mL | 50 – 250 | 120 |
| `HR` | Heart Rate | bpm | 40 – 200 | 72 |
| `r_m` | Membrane Resistance | ohm·cm | 1000 – 10000 | 5000 |
| `r_i` | Intracellular Resistance | ohm/cm | 100 – 500 | 200 |
| `r_e` | Extracellular Resistance | ohm/cm | 100 – 500 | 300 |
| `CVP` | Central Venous Pressure | mmHg | 0 – 12 | 5 |

### PRELIMINARY (9) — do chuỗi hàm tính, **là nơi duy nhất nhận X''**

| id | tên | đơn vị | dải khai báo | tính bởi |
|---|---|---|---|---|
| `MAP` | Mean Arterial Pressure | mmHg | 60 – 110 | step 1 |
| `R` | Vascular Resistance | mmHg·min/L | 10 – 40 | step 2 |
| `SV` | Stroke Volume | mL | 30 – 150 | step 3a |
| `CO` | Cardiac Output | L/min | 2 – 12 | step 3b |
| `T_cycle` | Cardiac Cycle Length | s | 0.30 – 1.60 | step 3c |
| `T_sys` | Ventricular Ejection Time | s | 0.08 – 0.42 | step 3d |
| `Q` | Blood Flow Rate | L/min | 0.5 – 15 | step 4 |
| `lambda` | Length Constant | mm | 0.5 – 5.0 | step 5 |
| `SVR` | Systemic Vascular Resistance | mmHg·min/L | 5 – 40 | step 6 |

---

## 2. Chuỗi hàm — 9 hàm, chạy theo thứ tự `step`

Engine sắp theo chuỗi ký tự của `step`: `1, 2, 3a, 3b, 3c, 3d, 4, 5, 6`.

```
  SENSOR                        HÀM                          PRELIMINARY

  SBP ---+
         +--[1  pressure_regulation]------> MAP --+
  DBP ---+   MAP = (1/3)SBP + (2/3)DBP            |
                                                   |
  eta ---+                                         +--+
  L   ---+--[2  vascular_resistance]---> R --------+  |
  r   ---+   R = 8*eta*L / (pi*r^4)                |  |
                                                   |  +--[4  hemodynamic_flow]--> Q
  CVP ---------------------------------------------+--+   Q = (MAP - CVP) / R
         |
  EDV ---+--[3a cardiac_filling]--------> SV --+
             SV = k * min(EDV, limit)          |
             k = 0.55, limit = 200 mL          +--[3b cardiac_pump]------> CO
  HR ------------------------------------------+      CO = HR * SV / 1000
         |
         +--[3c cardiac_rhythm]------> T_cycle          T_cycle = 60 / HR
         +--[3d systolic_interval]---> T_sys            T_sys = max(0.05,
                                                                0.413 - 0.0017*HR)

  r_m ---+
  r_i ---+--[5  electrical_conduction]--> lambda    lambda = sqrt(r_m/(r_i+r_e))
  r_e ---+

  MAP, CO, CVP --[6  systemic_resistance]--> SVR    SVR = (MAP - CVP) / CO
```

**Chú ý cho người vẽ:** hằng số Starling (`k = 0.55`, `limit = 200 mL`) nằm
trong **code Python**, không nằm trong XML — nó là hằng số của *mô hình*
chứ không phải tham số của *thể hiện*. Có sẵn ba hồ sơ bệnh nhân đổi được
bằng `set_patient_profile()`: `normal (0.55, 200)`, `heart_failure (0.30, 150)`,
`athletic (0.65, 220)`.

---

## 3. Composite — 6 cái

Không composite nào của lamina này khai báo `learns_from`, nên **absorption
vector ở đây là cố định, không học**.

| composite | attribute | absorption A | distribution D |
|---|---|---|---|
| `pressure_state` | SBP, DBP, MAP | 0.3333 mỗi cái | 0.3333 mỗi cái |
| `vessel_state` | eta, L, r, R | 0.25 mỗi cái | 0.25 mỗi cái |
| `pump_state` | EDV, SV, HR, CO | 0.25 mỗi cái | 0.25 mỗi cái |
| `conduction_state` | r_m, r_i, r_e, lambda | 0.25 mỗi cái | 0.25 mỗi cái |
| **`output_state`** | **CO** (một mình) | 1.0 | 1.0 |
| `flow_state` | Q (một mình) | 1.0 | 1.0 |

**`output_state` là MẶT TIẾP XÚC** của lamina — composite duy nhất đi ra
ngoài qua channel. Nó chỉ chứa **một** attribute, và đó là một sự thật có
hậu quả nặng, xem §8.

---

## 4. Segment — 3 mảng, 5 outcome

```
  [seg_arterial]  "Arterial"
      attributes : SBP, DBP, MAP, R, Q
      composites : pressure_state, vessel_state, flow_state
      functions  : pressure_regulation, vascular_resistance, hemodynamic_flow
      OUTCOME target_svr : SVR -> 14.0 +/- 4.0  mmHg.min/L
      OUTCOME target_map : MAP -> 85   +/- 15   mmHg

  [seg_cardiac]  "Cardiac"
      attributes : EDV, HR, SV, CO, T_cycle, T_sys
      composites : pump_state
      functions  : cardiac_filling, cardiac_pump, cardiac_rhythm, systolic_interval
      OUTCOME target_co  : CO  -> 5.0  +/- 1.5  L/min
      OUTCOME target_sv  : SV  -> 70   +/- 15   mL

  [seg_conduction]  "Conduction"
      attributes : r_m, r_i, r_e, lambda
      composites : conduction_state
      functions  : electrical_conduction
      OUTCOME target_lambda : lambda -> 2.0 +/- 0.5  mm
```

**Minh hoạ sống cho luật "hai nửa của segment"** (§2.4 file skeleton):
`target_svr` theo dõi `SVR`, nhưng `SVR` **không** có trong danh sách
`attributes` của `seg_arterial`. Không sao cả — ba danh sách đó là bản đồ
để đọc, engine không dùng chúng để chặn gì. Nửa có tác dụng runtime là
`behavioural_outcomes`.

**`output_state` và `flow_state` không thuộc segment nào** có outcome trỏ vào.

---

## 5. Tag — 4 tag, và một outcome cố tình không có tag

Cả 4 đều: `deviation_type=absolute`, `emitter=binary`,
`gate_kernel=sigmoid_leaky_tanh`, `polarity=negative`,
`decay=0.10`, `threshold_k=4.0`, `saturation=0.3`, `epsilon_ratio=0.001`.

| tag | nghe outcome | bắn vào composite | gain khai báo |
|---|---|---|---|
| `CO_DEVIATION` | `target_co` | `pump_state` (w=1.0) | **8.0** |
| `SV_DEVIATION` | `target_sv` | `pump_state` (w=1.0) | **8.0** |
| `MAP_DEVIATION` | `target_map` | `pressure_state` (w=1.0) | 0.6 |
| `LAMBDA_DEVIATION` | `target_lambda` | `conduction_state` (w=1.0) | 1.0 |
| *(không có)* | `target_svr` | — | — |

`target_svr` **được đánh giá mỗi chu kỳ và hiện lên màn hình, nhưng không
điều khiển gì cả** — vì không tag nào nghe nó. Đây là cách "chỉ theo dõi"
rẻ nhất: không cần `polarity="0"`, chỉ cần không viết tag.

### Tag bắn vào composite, nhưng chỉ PRELIMINARY mới thực sự nhận

Đây là chỗ dễ vẽ sai nhất khi cụ thể hoá. Tag trỏ vào **cả composite**,
nhưng bước 3 của vòng nhanh bỏ qua mọi attribute không phải PRELIMINARY:

```
  CO_DEVIATION / SV_DEVIATION --> pump_state {EDV, SV, HR, CO}
                                              ^^^      ^^^
                                              SENSOR   SENSOR  -> BỎ QUA
                                  thực nhận X'': SV, CO   (w = 0.25 mỗi cái)

  MAP_DEVIATION --------------> pressure_state {SBP, DBP, MAP}
                                                ^^^  ^^^
                                                SENSOR      -> BỎ QUA
                                  thực nhận X'': MAP     (w = 0.3333)

  LAMBDA_DEVIATION -----------> conduction_state {r_m, r_i, r_e, lambda}
                                                  ^^^^^^^^^^^^^^^
                                                  cả ba là SENSOR -> BỎ QUA
                                  thực nhận X'': lambda  (w = 0.25)
```

Vẽ mũi tên tag chạm vào cả composite, nhưng chỉ **tô đậm** những ô thực sự
nhận được X''.

### Trần bão hoà và ngưỡng snap, tính ra số cụ thể

`a_max = saturation × (physio_max − physio_min)` và
`epsilon = 0.001 × (physio_max − physio_min)`:

| attribute | dải | `a_max` (trần tanh) | `epsilon` (ngưỡng snap) |
|---|---|---|---|
| `MAP` | 50 mmHg | **15 mmHg** | 0.05 mmHg |
| `SV` | 120 mL | **36 mL** | 0.12 mL |
| `CO` | 10 L/min | **3 L/min** | 0.01 L/min |
| `lambda` | 4.5 mm | **1.35 mm** | 0.0045 mm |

---

## 6. Gate nội bộ (validation) — 4 cái

Chạy ở cuối mỗi `compute_all()`:

| attribute | loại | dải | steepness | cờ |
|---|---|---|---|---|
| `MAP` | `soft_range` | 60 – 110 | 1.0 | hypo/hypertension alert |
| `R` | `positive` | > 0 | — | invalid resistance |
| `CO` | `soft_range` | 2 – 12 | 2.0 | abnormal cardiac output |
| `Q` | `soft_range` | 0.5 – 15 | 1.0 | abnormal flow rate |

Đây là loại gate **thứ nhất** trong hai loại (xem §2.7 file skeleton) — canh
một attribute bên trong lamina, hoàn toàn khác gate màng ở §7.

---

## 7. Channel đi ra — `output_state` → lamina hô hấp

Từ `organism.xml` (`bdt_default`, 2 lamina):

```
  <channel id="ch_co_to_resp"
           from="lamina_circulatory:output_state"      <- composite (CO)
           to="lamina_respiratory:CO_ref"              <- attribute INTER_LAMINA
           time_delay="0">
    <extract mode="state"/>

    <transmit>
      <auto_gate id="ta_pump_deviation" refractory_cycles="5">
        <threshold aggregate="deviation" reference="0.30"
                   open_above="0.125" close_below="0.09"/>
      </auto_gate>
    </transmit>

    <receive>
      <key_gate id="rk_co" weight="1.0" rate="0.2"
                on_close="hold" confidence="0.8">
        <key metric="identity"/>
      </key_gate>
    </receive>
  </channel>
```

**Đọc cho đúng:** cổng gửi là `deviation` hai chiều quanh mốc **0.30** trong
không gian [0,1] của `CO`. Đảo ngược ra đơn vị gốc: `0.30` tương ứng
`CO = 2 + 0.30×10 = 5.0 L/min`, tức **mốc là chính cung lượng tim mục tiêu**.
Cổng mở khi `|s − 0.30| ≥ 0.125` (lệch ≥ 1.25 L/min) và chỉ đóng lại khi
tụt xuống `≤ 0.09` (lệch ≤ 0.9 L/min) — **vùng chết rộng 0.35 L/min**, cộng
5 chu kỳ trơ.

Có một body thứ hai, `organism_key.xml` (`bdt_key`), dùng cùng đường dây
nhưng cổng gửi là **`pattern`** thay vì `threshold` — bộ nhận dạng hình dạng
khớp vào `pump_state`:

```
  <pattern from="lamina_circulatory:pump_state"
           match_threshold="0.90" release_below="0.85">
    <weight attribute="EDV" ref="0.03">1.0</weight>
    <weight attribute="SV"  ref="0.11">1.0</weight>
    <weight attribute="HR"  ref="0.70">0.6</weight>
    <weight attribute="CO"  ref="0.58">0.3</weight>
  </pattern>
```

Đây là ví dụ cụ thể duy nhất trong repo về **auto gate dùng pattern**: nó
nhận dạng một *trạng thái nội bộ* của chính lamina mình, nên là auto gate,
không phải key gate.

---

## 8. Ba đặc thù của lamina này (rất nên ghi chú trên sơ đồ)

### 8.1 `output_state` chỉ có một attribute ⇒ **không thể có đường về**

Luật 14 chặn `<backprop>` trên channel này, và chặn vì lý do số học chứ
không phải quy ước: state value là trung bình có trọng số của các attribute,
nên với **một** attribute thì state **chính là** attribute đó dù trọng số
bằng bao nhiêu — mọi bước học đúng bằng 0.

```
   s = (v_CO * 1.0) / 1.0 = v_CO        đổi trọng số 1.0 thành 0.4 -> s không đổi
   dw = rate * delta * (v - v_trung_binh) = rate * delta * 0 = 0
```

Lamina này còn bị chặn lần thứ hai: `output_state` **không khai `learns_from`**.
Muốn có đường về đi vào tuần hoàn thì phải cho nó một mặt tiếp xúc nhiều
attribute *và* một luật học có clamp.

### 8.2 Đường dây chở một chỉ số, nhưng ở đây nó tình cờ **là** cung lượng tim

Vì `output_state` chỉ có `CO`, state value ánh xạ ngược lại đúng một đại
lượng có tên. Đó là **trường hợp may**, không phải quy tắc: mặt tiếp xúc có
4 attribute sẽ chở một *chỉ số pha trộn* không ánh xạ về đại lượng nào cả.

### 8.3 `Q` và `CO` là hai con số khác nhau, và cả hai đều đúng

Ở baseline: **`CO` = 4.752 L/min** (cung lượng tim, từ `HR × SV`) nhưng
**`Q` = 2.230 L/min** (lưu lượng, từ `(MAP − CVP)/R`, với `R` tính bằng
Poiseuille cho **một** mạch). Hai công thức trả lời hai câu hỏi khác nhau và
`R` không phải sức cản hệ thống. Hàm step 6 (`SVR = (MAP − CVP)/CO = 18.59`)
là đại lượng tương ứng ở cấp hệ thống. Trên sơ đồ nên vẽ `Q` và `CO` ở hai
nhánh riêng, **không nối chúng bằng dấu bằng**.

---

## 9. Số đo thật ở baseline

Đặt mọi cảm biến về `baseline` đã khai, chạy `compute_all()` một lần:

| attribute | giá trị | chuẩn hoá |
|---|---|---|
| SBP | 120.0 mmHg | 0.3333 |
| DBP | 80.0 mmHg | 0.3333 |
| eta | 3.5 mPa·s | 0.5000 |
| L | 50.0 cm | 0.4949 |
| r | 0.15 cm | 0.0940 |
| EDV | 120.0 mL | 0.3500 |
| HR | 72.0 bpm | 0.2000 |
| r_m | 5000 ohm·cm | 0.4444 |
| r_i | 200 ohm/cm | 0.2500 |
| r_e | 300 ohm/cm | 0.5000 |
| CVP | 5.0 mmHg | 0.4167 |
| **MAP** | **93.333 mmHg** | 0.6667 |
| **R** | **39.615** mmHg·min/L | 0.9872 |
| **SV** | **66.000 mL** | 0.3000 |
| **CO** | **4.752 L/min** | 0.2752 |
| **T_cycle** | **0.833 s** | 0.4103 |
| **T_sys** | **0.291 s** | 0.6194 |
| **Q** | **2.230 L/min** | 0.1193 |
| **lambda** | **3.162 mm** | 0.5916 |
| **SVR** | **18.589** mmHg·min/L | 0.3882 |

**State value của 6 composite ở baseline:**

```
   pressure_state    0.4444        output_state      0.2752   <- mặt tiếp xúc
   vessel_state      0.5190        flow_state        0.1193
   pump_state        0.2813        conduction_state  0.4465
```

**Năm outcome ở baseline:**

| outcome | thực tế | mục tiêu | lệch | tolerance | trạng thái |
|---|---|---|---|---|---|
| `target_map` | 93.333 | 85 | +8.333 | 15 | trong dải |
| `target_co` | 4.752 | 5.0 | −0.248 | 1.5 | trong dải |
| `target_sv` | 66.0 | 70 | −4.000 | 15 | trong dải |
| `target_svr` | 18.589 | 14.0 | **+4.589** | 4.0 | **trên dải** |
| `target_lambda` | 3.162 | 2.0 | **+1.162** | 0.5 | **trên dải** |

Nghĩa là ngay ở baseline đã có **hai** outcome ngoài dải, và chúng xử sự
hoàn toàn khác nhau — đúng vì một cái có tag, một cái không.

---

## 10. Vòng nhanh chạy thật — `LAMBDA_DEVIATION`

Đây là ví dụ chạy được sạch nhất: một tag, một attribute nhận X''.

```
  chu kỳ   lambda     X''      deviation   tag phát
     0     3.1623    0.0000     +1.1623    (trước khi chạy)
     1     2.8775   -0.2848     +0.8775    LAMBDA_DEVIATION
     2     2.7144   -0.4479     +0.7144    LAMBDA_DEVIATION
     3     2.6370   -0.5252     +0.6370    LAMBDA_DEVIATION
     4     2.6055   -0.5568     +0.6055    LAMBDA_DEVIATION
     6     2.5884   -0.5739     +0.5884    LAMBDA_DEVIATION
    12     2.5854   -0.5769     +0.5854    LAMBDA_DEVIATION
```

Đọc được ngay ba tính chất của kernel trên bảng này:

- **Hội tụ, không dao động** — tích phân rò rỉ (`decay = 0.10`) kéo lại,
  X'' dừng ở −0.5769 và đứng yên.
- **Không về tới đích, và đúng như vậy** — lệch dừng ở +0.5854 chứ không
  về 0, vì `polarity·gain·w·G·d` đạt cân bằng với số hạng rò rỉ. Đây là bộ
  điều khiển tỷ lệ có rò, không phải PID có tích phân triệt tiêu sai số.
- **Không chạm trần** — |−0.5769| < `a_max` 1.35 mm, nên `tanh` chưa cong.

`SVR` thì trong suốt 12 chu kỳ đó giữ nguyên `X'' = 0.0`: không tag nào
nghe `target_svr`.

---

## 11. Cổng màng chạy thật — ba kịch bản

Chạy `Organism("organism.xml")`, giữ HR ở một giá trị đến khi ổn định:

| HR | CO | state | \|s−0.30\| | cổng gửi | open_fraction | trạng thái dây | số đã gửi | `CO_ref` bên nhận |
|---|---|---|---|---|---|---|---|---|
| 72 | 4.752 | 0.2752 | 0.0248 | **đóng** | 0.000 | `shut` | — | 5.000 *(baseline riêng)* |
| 120 | 5.919 | 0.3916 | 0.0916 | **mở** | 1.000 | `crossing` | 5.594 | 5.594 |
| 45 | 4.250 | 0.2281 | 0.0719 | **đóng** | 0.000 | `held` | — | 5.109 *(đang già đi)* |

Ba dòng này minh hoạ đúng ba cơ chế, nên rất đáng vẽ thành ba khung nhỏ:

**Dòng 1 — nghỉ, cổng đóng.** Lệch 0.0248 < ngưỡng mở 0.125. Lamina hô hấp
ngồi trên baseline 5.0 của chính nó. Nó **không sai**, chỉ là *chưa được
thông báo* — và `provenance` nói ra điều đó thay vì để 5.0 trông như một
giá trị đã ghép.

**Dòng 2 — vùng chết đang giữ cổng mở.** Chú ý 0.0916 **nhỏ hơn** ngưỡng
mở 0.125! Cổng vẫn mở vì nó đã mở lúc quá độ (CO vọt lên 7.92 khi HR nhảy
lên 120, tức lệch 0.292), và 0.0916 vẫn **trên** ngưỡng đóng 0.09. Đây
chính là hiện tượng trễ mà hai ngưỡng sinh ra — vẽ được thành một mũi tên
đi vòng trong máy trạng thái.

**Dòng 3 — `held` chứ không phải `shut`.** Cổng đã đóng, nhưng bên nhận
đang **giữ** 5.109 mà nó lấy được lần cuối, và đếm tuổi (`on_close="hold"`).
Một người đọc sơ đồ phải phân biệt được ô này với ô "chưa bao giờ nhận gì".

---

## 12. Vòng chậm chạy thật — và một điều cần biết

Cấu hình trong XML:

```
   <adaptation kernel="model_free" cadence="20">
     perf_alpha  0.10      gain_rate 0.02     gain_min 0.30    gain_max 1.20
     op_rate     0.10      op_min   -0.30     op_max   0.30    settle_band 0.50
```

Chạy với HR = 120 (để `target_co` ở ngoài dải liên tục), 60 chu kỳ:

```
  chu kỳ    CO        X''       gain     perf_ewma   ghi chú
      1   4.3708   -2.8696     None       1.9467     vòng chậm chưa chạy
     19   5.9323   -1.5802     None       0.8041     perf đang giảm (tốt lên)
     20   5.9327   -1.5814     0.62       0.7858     <- TICK VÒNG CHẬM #1
     21   6.2062   -1.3462     0.62       0.7694     hiệu chỉnh yếu đi
     40   6.6579   -1.0602     0.60       1.0440     <- TICK #2, perf đã xấu đi
     60   6.6736   -1.0608     0.62       1.1062     <- TICK #3, đảo hướng
```

`operating_point` giữ nguyên 0.0 suốt: `settled` luôn `False` vì
`|dev|/tol` không xuống dưới `settle_band = 0.50`. Nên trong lần chạy này
vòng chậm **chỉ vặn `gain`**, không hợp nhất gì.

> ### ⚠ Một hành vi đo được, nên biết trước khi vẽ
>
> `CO_DEVIATION` khai `gain = 8.0` trong XML. Nhưng ở chu kỳ 20, vòng chậm
> ghi `gain = 0.62` vào `MetaState`, và từ đó `_build_kernel_params` **lấy
> giá trị của vòng chậm đè lên giá trị của tag**.
>
> Con số 0.62 đến từ `0.6 + 0.02` — tức vòng chậm mồi từ `gain_seed`
> (mặc định **0.6** trong code) **chứ không phải từ `gain = 8.0` mà tag đã
> khai**. `gain_max = 1.20` cũng chặn không cho nó quay lại 8.0 được nữa.
>
> Hệ quả đo được: X'' yếu từ −1.58 xuống −1.35 ngay chu kỳ sau, và CO trôi
> **xa** mục tiêu (5.93 → 6.67), perf_ewma xấu đi từ 0.786 lên 1.106.
>
> Tôi không kết luận đây là lỗi — có thể chủ ý là "vòng chậm sở hữu gain".
> Nhưng nếu vẽ mũi tên "gain khai trong XML → kernel", hình sẽ chỉ đúng
> trong 19 chu kỳ đầu. Vẽ đúng thì mũi tên đó phải bị `MetaState.gain`
> cắt ngang kể từ tick vòng chậm đầu tiên.

---

## 13. Sơ đồ đề xuất riêng cho lamina này

**A — DAG chuỗi hàm.** Đúng §2. 11 ô cảm biến bên trái, 9 hàm ở giữa,
9 ô tính bên phải. Đây là hình dễ hiểu nhất với người ngoài.

**B — Sáu composite chồng lên DAG.** Cùng bố cục hình A, khoanh 6 vùng
composite. Cho thấy `CO` thuộc **cả** `pump_state` **và** `output_state`,
và `MAP` thuộc **cả** `pressure_state` và (qua step 4, 6) là đầu vào của
`Q` và `SVR`. Đây là hình chứng minh composite không phải một phân hoạch.

**C — Ba segment × sáu composite.** Bản cụ thể của sơ đồ 11 trong file
skeleton: hàng = 3 segment, cột = 6 composite, ô = attribute. Chỉ rõ
`output_state` và `flow_state` không nằm dưới outcome nào.

**D — Bản đồ tag.** 5 outcome bên trái, 4 tag ở giữa, 3 composite bên phải;
`target_svr` là đầu dây **cụt** (không tag). Trong mỗi composite, tô đậm
attribute PRELIMINARY thực nhận X'', làm mờ các SENSOR bị bỏ qua.

**E — Bảng baseline + hai outcome ngoài dải.** Hình tĩnh, dùng số ở §9.

**F — Máy trạng thái của `ta_pump_deviation`.** Trục là `|s − 0.30|`,
đánh dấu 0.09 và 0.125, vẽ đường đi của kịch bản HR 120 để thấy nó mở ở
0.292 rồi ở lại mở tại 0.0916.

**G — Ba trạng thái đường dây.** `shut` / `crossing` / `held` với số thật
ở §11, kèm giá trị `CO_ref` bên nhận trong từng trạng thái.

**H — Hai vòng lặp trên `target_co`.** Dùng bảng §12: làn nhanh mỗi chu kỳ,
làn chậm ở chu kỳ 20/40/60, mũi tên `gain` đi xuống, và nút chặn ở chỗ
`MetaState.gain` đè lên gain của tag.
