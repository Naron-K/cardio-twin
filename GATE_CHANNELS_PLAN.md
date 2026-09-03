# Kênh truyền / kênh nhận & hai loại cổng — Kế hoạch triển khai

> **Trạng thái (2026-09-03): Phase 0–6 đã xong.** 358 test backend xanh,
> `tsc` sạch, `vite build` sạch, màn hình `#body` đã chạy lại và được kiểm
> bằng Chrome headless trên backend thật.
>
> Tiêu chí nghiệm thu đạt: **1800/1800 giá trị trùng khít baseline v1** tới
> 12 chữ số thập phân. Hai tấm ảnh đều nằm trong repo —
> `backend/tests/fixtures/gate_traces_v1.json` (đóng băng) và
> `gate_traces_v2.json` — diff chúng thì **chỉ có tên đổi**, không một dòng
> số nào.
>
> Q1–Q6 đã được chốt ngày 2026-09-03: (1) tuần hoàn 1, hô hấp 2; (2) một
> composite / lamina, **không** phân hướng; (3) xả lũ chỉ ràng buộc phía
> mình; (4) trọng số nhân vào **độ lệch**; (5) `identity` và pattern đều hợp
> lệ; (6) tối đa 4 cổng mỗi mặt.
>
> Khác biệt so với bản viết ban đầu, đều do đo mà ra:
> - **Luật 8** đếm theo `(lamina, mặt)` gộp cả hai phía, không theo
>   `(lamina, side, hướng)` — bản đầu cho tới 16 cổng/lamina thay vì 8 như
>   L5, và xếp cổng nhận vào mặt *ngược* với hướng dây tới.
> - **`<lamina face="...">`** là trường mới: một lamina ở cuối stack không
>   gửi gì nên không suy ra được mặt tiếp giáp, và nếu không khai thì nó
>   vĩnh viễn không thể có cổng auto phía nhận.
> - **`refractory_cycles` trên trigger pattern** trước đây được parser nhận
>   nhưng không ai đọc. Xem Phase 4.
> - **`mode="band"`** suýt bị xoá cùng `Transfer`; đã khôi phục trên cổng
>   phía nhận.

Viết 2026-09-02, sau checklist của GS Lee (5 chỉ đạo cốt lõi + 3 nguyên tắc
kiến trúc). Baseline lúc viết: nhánh `universal-visualisation`, **255/255 test
backend xanh**, `tsc` sạch, còn một khối chưa commit (organism_key.xml +
rule 6 + picker body) — **commit khối đó trước khi động vào plan này**, vì
Phase 0 dưới đây cần một baseline có thể `git checkout` lại được.

Mục đích xuyên suốt: **universal**. Không một dòng nào trong plan này được
nhắc tên `CO`, `pump_state` hay `lamina_respiratory` trong code chạy thật;
tất cả nằm trong XML. Guardrail cũ vẫn giữ: một cơ chế universal phải
trung-tính-miền VÀ được ít nhất một lamina thật dùng.

---

## 1. Yêu cầu của Lee, đối chiếu với cái đang có

| # | Lee yêu cầu | Hiện trạng (sau Phase 6 của PERMEABILITY_GATES_PLAN) | Khoảng cách |
|---|---|---|---|
| L1 | **Cô lập độ phức tạp** — nhìn từ ngoài, một lamina là *một composite*; mọi thay đổi bên trong đã được hấp thụ vào giá trị composite đó | Rule 2: nguồn gate phải là composite ✔. Nhưng mỗi gate tự chọn composite bất kỳ; key gate còn đọc 4 attribute *bên trong* composite | Chưa có khái niệm "composite mặt tiếp giáp" của một lamina về một phía |
| L2 | **Chỉ giao tiếp lớp liền kề** (trên/dưới), cấm cross-laminar | Không có kiểm tra nào. Cả hai lamina đang khai `level="1"` — tức là *cùng mức*, chưa ai định nghĩa "trên/dưới" | Thiếu hẳn khái niệm stack. Xem Q1 |
| L3 | **Permeability** — cổng tồn tại để X không ép Y ngay lập tức | Đúng tiền đề của G6 + EWMA `rate` ✔ | — |
| L4 | **Tách kênh truyền và kênh nhận** — hai bộ cổng riêng, không multiplex | **MỘT** `PermeabilityGate` ôm cả hai: controller đọc bên gửi, `_transfer` ghi thẳng vào X′ bên nhận. Bên nhận **không có tiếng nói** | Khoảng cách lớn nhất. Đây là trục của plan |
| L5 | **≤ 8 cổng / lamina** (4 lên, 4 xuống) | Không giới hạn | Rule mới |
| L6 | **Hoãn lambda, dùng trọng số vô hướng** cho "bao nhiêu đi qua" | Có `rate` (EWMA, *tốc độ*) và `open_fraction` (nhân vào rate, Phase 4). Không có tham số nào nói *lượng* | Thiếu `weight`, và phải định nghĩa "lượng" cho universal (xem C5) |
| L7 | **Auto gate ≠ Key gate**, hai thực thể độc lập trong mỗi kênh | Hai *controller* trên **cùng một class**, chọn bằng `controller="threshold\|key"`. Threshold gate mở xong vẫn qua EWMA 0.2 — không "xả tung". Key gate hiện đọc composite của **chính lamina gửi** → theo phân loại của Lee đó là cơ chế *nội bộ*, không phải "nhận chìa khoá từ ngoài" | Phải tách class, tách ngữ nghĩa mở, và xếp lại `organism_key.xml` |

Một điều cần nói thẳng: **plan trước không sai, nó trả lời một câu hỏi hẹp
hơn** ("khi nào một giá trị được băng qua") và giải quyết bằng một cái van
đặt *giữa* hai lamina. Lee đặt van ở **màng của từng lamina**, mỗi bên một
bộ. Về mặt code đây là refactor, không phải viết lại: hysteresis, EWMA, ring
buffer trễ, provenance, snapshot, breaker — tất cả giữ nguyên, chỉ **đổi chủ
sở hữu**.

---

## 2. Tham khảo — cái gì đã có tiền lệ, cái gì Lee chặt hơn

Không mục nào dưới đây được bê nguyên; mỗi mục chỉ mượn đúng một ý và ghi rõ
ý đó rơi vào quyết định nào.

| Nguồn | Ý mượn | Rơi vào |
|---|---|---|
| **OSI / kiến trúc lớp đóng** — mỗi lớp chỉ nói chuyện với lớp kề qua *service access point*; cross-layer là ngoại lệ có tên riêng, không phải mặc định ([ScienceDirect: Adjacent Layer](https://www.sciencedirect.com/topics/computer-science/adjacent-layer)) | L2 là quy tắc chuẩn của mọi kiến trúc lớp; cái phải làm là *enforce lúc parse*, không phải tranh luận | C7 / Rule 7 |
| **MMSF / MML** (Borgdorff, Hoekstra et al., *Phil. Trans. R. Soc. A* 2014) — submodel có **input port và output port riêng**, "coupled separately from the submodel implementation, in MML, so that submodels do not have to know what code they are coupled to"; conduit là *one-way, point-to-point*; filter là conduit *có trạng thái* làm scale-bridging ([PDF](https://pure.uva.nl/ws/files/2412981/166807_20130378.full.pd.pdf)) | Tách port truyền/nhận là chuẩn 10 năm nay. **Channel = conduit; EWMA + delay = filter; khai ở organism = MML.** Lamina không được biết nó nối với ai | C1, C2, C6, C10 |
| **Co-simulation** (Gomes et al., *Co-simulation: State of the art*, [arXiv 1702.00686](https://arxiv.org/pdf/1702.00686)) — Gauss-Seidel ép thứ tự để đơn vị sau nhận input đã ở `t+H`; *algebraic loop* = biến gián tiếp phụ thuộc chính nó qua các đơn vị, phát hiện bằng feedthrough; một kịch bản co-sim **hành xử như một đơn vị** → lồng được | Thứ tự tick hiện tại đã là Gauss-Seidel một chiều. Rule 7 + channel một chiều làm vòng phụ thuộc *hiện ra trong khai báo* thay vì phải dò. Organism-as-unit là hướng universal đệ quy (một organism làm lamina của organism lớn hơn) — **ghi nhận, không làm** | C11, mục "Không làm" |
| **OmniBioTwin** ([arXiv 2606.11264](https://arxiv.org/html/2606.11264)) — coupling operator `C_{j→i}` tường minh cho từng cặp có thứ tự, lịch `δ_i^t ∈ {0,1}` cho đa nhịp | Xác nhận "operator khai tường minh theo cặp có hướng". **Nhưng OmniBioTwin cho phép many-to-many, không giới hạn liền kề** — Lee chặt hơn, và lý do của Lee (chống hỗn loạn) là lý do kiến trúc, không phải toán | C7 |
| **Schmitt trigger / deadband** ([Toshiba FAQ](https://toshiba.semicon-storage.com/us/semiconductor/knowledge/faq/linear_opamp/how-can-i-provide-hysteresis-for-a-comparator.html)) — một ngưỡng trên tín hiệu nhiễu thì dither; hai ngưỡng là cách chuẩn | Rule 4 đã đo được (177 và 148 lần lật / 400 chu kỳ). **Giữ cho mọi trigger mới**, kể cả trigger của auto gate | Rule 4 |
| **Safety Instrumented Systems / layers of protection** ([control.com](https://control.com/textbook/process-safety-and-instrumentation/safety-instrumented-functions-and-systems/)) — lớp an toàn *độc lập* với lớp điều khiển; relief valve mở theo áp suất bất kể bộ điều khiển nói gì; logic fail-safe *de-energise-to-trip* | Auto gate của Lee chính là relief valve: một lớp riêng, đánh giá **trước** key gate, **không tắt được bằng cấu hình**. Nhưng relief valve xả vào *môi trường*, không ép thẳng vào thiết bị kế bên → C4 | C3, C4, C11 |
| **Kênh ion voltage-gated vs ligand-gated** ([LibreTexts](https://bio.libretexts.org/Bookshelves/Cell_and_Molecular_Biology/Basic_Cell_and_Molecular_Biology_(Bergtrom)/17:_Membrane_Function/17.03:_Ligand_and_Voltage_Gated_Channels_in_Neurotransmission)) — voltage-gated mở theo **trạng thái nội bộ** (điện thế màng); ligand-gated mở khi **phân tử bên ngoài** gắn vào; cả hai đều nằm **trên màng của tế bào sở hữu** | Đúng ẩn dụ Lee dùng, và nó cho ra định nghĩa sạch: *auto = nội bộ (đọc composite của mình), key = ngoại (đọc thứ được trình ra ở kênh)*; và cổng **thuộc về lamina**, mỗi bên màng một bộ | C2, C3 |
| **ISO 23247-6 (composition)** — federated composition, hợp đồng giao diện giữa twin của các bên khác nhau ([ISO](https://www.iso.org/standard/87426.html)) | Củng cố G1/G5/Rule 3: đích phải là chỗ bên nhận *đã khai* là nhận. Không đổi gì | — |

---

## 3. Quyết định thiết kế (đề xuất chốt — mục nào có `Q` thì chờ Lee)

| # | Quyết định | Lý do ngắn |
|---|---|---|
| C1 | **Channel là đối tượng riêng**: một cặp lamina *liền kề*, **một chiều**, từ *một* composite bên gửi tới *một* attribute `INTER_LAMINA` bên nhận. Cổng truyền của bên gửi ghi *vào* channel; cổng nhận của bên nhận đọc *từ* channel. Channel là "khe synap" | L4. Có chỗ cho giá trị *đã truyền nhưng chưa được nhận* — trạng thái thật mà thiết kế cũ không biểu diễn được. Ring buffer trễ sống ở đây (nó là tính chất của dây) |
| C2 | **Cổng thuộc về một lamina và một phía**: `side ∈ {transmit, receive}`. Không cổng nào vừa truyền vừa nhận | L4, đúng chữ. MMSF: port riêng, khai ở tầng trên |
| C3 | **Hai thực thể**: `AutoGate` và `KeyGate` — hai dataclass, hai registry trigger, một helper hysteresis dùng chung. *Auto* đọc **composite của chính lamina mình** (nội bộ). *Key* đọc **thứ được trình ra ở kênh** (ngoại): phía nhận = vector composite bên gửi đi kèm giá trị; phía truyền = vector composite của lamina nhận (nhu cầu) | L7. Lee: dùng chung logic ngưỡng thì được, gộp thực thể thì không |
| C4 | **Auto = xả lũ**: khi nổ, `weight ≡ 1`, `rate ≡ 1`, bỏ qua delay — *của phía mình*. **Không** ghi đè cổng của lamina bên kia | L7 "bất chấp cấu hình khác". Relief valve xả vào môi trường; receptor của tế bào kế bên vẫn tự quyết. Nếu auto của A ép được vào B thì fail-safe của A thành forced-write vào B — đúng cái hỗn loạn mà cổng sinh ra để chặn. **Q3** |
| C5 | **Key = trọng số**, định nghĩa *lượng* cho universal: `received = baseline_nhận + weight · (value − baseline_nhận)`, tính trong **không gian chuẩn hoá [0,1]** rồi đổi về đơn vị bên nhận. `weight=1` → nguyên giá trị (hành vi hôm nay); `weight=0.5` → nửa *độ lệch* so với điều bên nhận đang giả định | L6. "Thông tin" = độ lệch khỏi giả định; nhân thẳng vào giá trị thì CO 4.8 thành 2.4 (Phase 4 đã bác). **Q4** |
| C6 | **`rate` / `time_delay` / `on_close` / `confidence` chuyển sang phía NHẬN**; phía truyền chỉ có mở/đóng + weight. Delay nằm ở channel | Hấp thụ nhanh hay chậm là việc của bên nhận (MMSF: filter là conduit có trạng thái, không phải submodel). Giải luôn mâu thuẫn G4 ↔ xả lũ: bên gửi xả, **bên nhận vẫn hấp thụ theo rate của mình** — trừ receive-auto (hấp thụ rate 1) |
| C7 | **Liền kề = stack khai trong organism.xml**: `<lamina id=".." level="n"/>`; mọi channel phải có `\|Δlevel\| = 1`. `level` trong file lamina thành thông tin, không dùng để xét | L2. Vị trí trong stack là tính chất của *cơ thể*, không phải của lamina (một lamina có thể đứng ở mức khác trong cơ thể khác). **Q1** |
| C8 | **≤ 4 cổng / (lamina, hướng)** → ≤ 8 / lamina. Hướng = `up` (tới level cao hơn) hoặc `down`. Rule 6 (một attribute đích – một channel) giữ nguyên | L5 |
| C9 | **Một composite mặt tiếp giáp / (lamina, hướng)**: mọi channel *và* mọi auto gate của một lamina về một hướng đọc **cùng một** composite | L1. Từ ngoài nhìn vào, lamina *là* composite đó. **Q2** |
| C10 | **Cổng khai trong organism.xml, gộp theo channel → phía**. File lamina không đổi | Giữ nguyên tắc dự án: lamina chạy standalone được. Key phía truyền tham chiếu composite của lamina *khác* — thứ đó không được phép nằm trong file lamina. MMSF khai coupling ở MML, không trong submodel |
| C11 | **Thứ tự trong gate pass, mỗi channel**: (1) auto truyền → (2) key truyền (bỏ qua nếu auto đã nổ) → ghi channel → (3) auto nhận → (4) key nhận (bỏ qua nếu auto nhận đã nổ) → ghi X′. Giá trị **chỉ băng qua khi phía truyền mở VÀ phía nhận mở**; không thì nằm ở channel và *đếm tuổi* | L7 "hoạt động ở thời điểm khác nhau": auto là lớp bảo vệ, xét trước. Thứ tự tick 4 bước của Organism (sensor → compute → gate pass → feedback) **không đổi** |
| C12 | **Lambda hoãn, và hoãn bằng fail-fast**: parser *nhận diện* `<transform>` và từ chối kèm thông báo "v2, chưa hỗ trợ" | L6. Từ chối rõ tốt hơn để ai đó nhét `eval` vào — đúng tiền lệ "không eval chuỗi formula" |
| C13 | **Schema cũ `<permeability_gates>` bị từ chối**, không âm thầm diễn dịch lại. Cả hai body XML được migrate trong Phase 1 | Fail-fast. Một body cũ chạy được "gần đúng" trên container mới là loại lỗi khó thấy nhất |

Giữ nguyên: G1–G9, Rule 1–6, D12 sensor-sacred, thứ tự tick 4 bước, breaker
cơ thể, hai điểm đo của Phase 2/4 (không có trễ ngầm; `open_fraction` không
nhân vào giá trị).

---

## 4. Hình dạng XML (v2)

```xml
<organism id="bdt_default" version="2.0">
  <laminae>
    <lamina id="lamina_circulatory" level="1"/>
    <lamina id="lamina_respiratory" level="2"/>     <!-- C7: stack là của cơ thể -->
  </laminae>

  <channels>
    <!-- Một channel = một dây một chiều giữa hai lamina LIỀN KỀ (rule 7),
         từ đúng một composite (C9) tới đúng một attribute INTER_LAMINA (rule 3, 6). -->
    <channel id="ch_pump_up"
             from="lamina_circulatory:pump_state"
             to="lamina_respiratory:CO_ref"
             time_delay="0">                          <!-- delay là của dây -->
      <extract attribute="CO"/>

      <!-- Cổng của lamina_circulatory, phía TRUYỀN. ≤4 (rule 8). -->
      <transmit>
        <auto_gate id="ta_pump_deviation" refractory_cycles="5">
          <!-- trigger đọc composite của CHÍNH nó: pump_state -->
          <threshold watch="CO" aggregate="deviation" reference="0.30"
                     open_above="0.125" close_below="0.09"/>
        </auto_gate>
        <key_gate id="tk_o2_demand" weight="1.0">
          <!-- chìa khoá từ NGOÀI: composite mặt tiếp giáp của lamina nhận -->
          <key from="lamina_respiratory:transport_state"
               metric="weighted_distance" match_threshold="…" release_below="…">
            <weight attribute="DO2" ref="…">1.0</weight>
          </key>
        </key_gate>
      </transmit>

      <!-- Cổng của lamina_respiratory, phía NHẬN. rate/on_close ở đây (C6). -->
      <receive>
        <auto_gate id="ra_transport_crisis" refractory_cycles="5">
          <threshold watch="DO2" aggregate="deviation" reference="…"
                     open_above="…" close_below="…"/>   <!-- đọc transport_state của mình -->
        </auto_gate>
        <key_gate id="rk_pump" weight="1.0" rate="0.2" on_close="hold" confidence="0.8">
          <!-- receptor: khớp thứ đang được trình ra ở kênh. identity = "đúng loại
               phân tử" (composite id bên gửi); weighted_distance = đúng hình dạng -->
          <key metric="identity"/>
        </key_gate>
      </receive>
    </channel>
  </channels>
</organism>
```

Trigger của **auto gate** nhận `<threshold>` *hoặc* `<pattern>` (khớp
weighted-distance vào composite *của mình* — đây là chỗ `organism_key.xml`
hạ cánh: nhận dạng "tim đang suy" là nhận dạng **nội bộ**, nên theo Lee nó là
auto gate có trigger pattern, không phải key gate). Cả hai trigger đều bắt
buộc hai ngưỡng (rule 4).

Key của **key gate** nhận `metric ∈ {identity, weighted_distance, cosine}`.
`identity` khớp *nhãn* (composite id được mang trên kênh) — "đúng loại phân
tử"; hai metric kia khớp *hình dạng* — "đúng cấu trúc". Với `identity` không
cần ngưỡng: nhãn khớp hay không, không có nhiễu để chatter.

### RULES bổ sung (enforce lúc parse, cộng vào 1–6)

7. **Liền kề**: `|level(from) − level(to)| = 1`. Vi phạm → nêu rõ hai level.
8. **≤ 4 cổng / (lamina, side, hướng)** — đếm qua mọi channel của lamina đó.
9. **Một composite mặt tiếp giáp / (lamina, hướng)**: hai channel cùng lamina
   cùng hướng mà khác composite → lỗi nêu cả hai.
10. **`<transform>` bị từ chối** (C12).
11. **Không có `<permeability_gates>`** trong v2; gặp là lỗi kèm câu chỉ sang
    `<channels>` (C13).
12. **Mỗi phía của channel có ≥ 1 cổng.** Channel không cổng phía nhận là dây
    ép thẳng vào X′ — đúng cái Lee cấm.

---

## 5. Phase

Phase 0 trước tất cả. 1 → 2 → 3 tuần tự. 4 và 5 song song sau 2. 6 cuối.

### Phase 0 — Chụp baseline để chứng minh "refactor không đổi số"

Đo *trước* khi sửa, để Phase 2 có tiêu chí nghiệm thu bằng số chứ không
bằng niềm tin. Xuất trace JSON cho hai body hiện có, 40 chu kỳ, seed 11, với
đúng các kịch bản đã đo ở Phase 5 cũ:

| body | ép | ghi lại mỗi chu kỳ |
|---|---|---|
| `organism.xml` | nghỉ, HR 90, 110, 200, 35 | `open_fraction`, `transmitted`, `CO_ref`, `DO2`, provenance.state |
| `organism_key.xml` | nghỉ, HR 140, (HR 150, EDV 55), (HR 120, EDV 60) | như trên + `match`, `drift` |

Lưu ở `backend/tests/fixtures/gate_traces_v1.json`. Test đọc file này ở
Phase 2. **Không sửa gì khác ở phase này.**

### Phase 1 — Hợp đồng schema v2 (XML trước, code sau)

| Việc | File | Chi tiết |
|---|---|---|
| Dataclass | `organism.py` | `Channel(id, source, dest, extract, time_delay, transmit: list[Gate], receive: list[Gate])`; `AutoGate(id, trigger, refractory)`; `KeyGate(id, key, weight, rate, on_close, confidence)`. `PermeabilityGate` **xoá** (không giữ alias — C13) |
| Stack | `OrganismSpec.levels: dict[lamina_id → int]` | Đọc `level` từ `<lamina>`; thiếu → lỗi |
| Parser | `_parse_channel`, `_parse_auto_gate`, `_parse_key_gate` | Rule 1, 4, 5, 6 giữ; thêm 7–12 |
| Migrate | `organism.xml`, `organism_key.xml` | Viết lại theo §4. Số ngưỡng **giữ nguyên** (đã đo). Comment giải thích *vì sao* mỗi cổng ở phía nó ở |
| Learnable | giữ `<learnable>` trên `key_gate` | Rule 5 áp cho `weight` nếu khai learnable |

Test (`tests/test_channels_schema.py`): mỗi rule mới một test dương + một
test âm; schema cũ bị từ chối với thông báo có chữ `<channels>`;
`organism_key.xml` parse ra auto gate với trigger pattern (không còn là
`controller="key"`).

### Phase 2 — Container: gate pass hai phía, channel có trạng thái

Trục của plan. `Organism` giữ nguyên `tick()` 4 bước; chỉ `_gate_pass` đổi.

```
cho mỗi channel (theo thứ tự khai):
  src_vec  = composite mặt tiếp giáp bên gửi      (đã compute ở bước 2)
  dst_vec  = composite mặt tiếp giáp bên nhận

  # phía truyền — của lamina gửi
  tx_open, tx_flood, tx_weight = _side(channel.transmit, own=src_vec, presented=dst_vec)
  nếu tx_open: channel.offer(value=reading, label=source.member, vec=src_vec, weight=tx_weight, flood=tx_flood)
  channel.age += 1 (nếu không offer mới)

  # phía nhận — của lamina nhận
  rx_open, rx_flood, rx_gate = _side(channel.receive, own=dst_vec, presented=channel.offered)
  nếu tx_open và rx_open:
      delayed = channel.through_delay()          # ring buffer, như cũ
      amount  = C5(delayed, weight = tx_weight · rx_gate.weight)
      rate    = 1.0 nếu (tx_flood hoặc rx_flood) else rx_gate.rate
      EWMA + set_inter_lamina(provenance{state, channel, gates: {tx, rx}, flood, age})
  không thì: _on_close theo rx_gate.on_close (như cũ), provenance.state = held / decaying / waiting
```

`_side()` là **một** hàm cho cả hai phía: chạy auto trước, key sau; auto nổ
thì bỏ qua key và trả `flood=True`. Trạng thái mỗi cổng vẫn ở
`Organism._gate_state[gate_id] = {"controller": …}`; trạng thái channel
(buffer, offered, age) ở `Organism._channel_state[channel_id]` — hai chủ,
không với tay sang nhau (bài học Phase 4).

Registry: `_auto_trigger_registry = {"threshold": …, "pattern": …}`,
`_key_metric_registry = {"identity": …, "weighted_distance": …, "cosine": …}`.
`register_*` public như cũ để test lái cổng tất định.

**Tiêu chí nghiệm thu (bằng số):**

1. **Không đổi số**: `organism.xml` v2 với `ta_pump_deviation` + `rk_pump`
   (identity, rate 0.2, hold) tái tạo `gate_traces_v1.json` **tới 1e-9** ở
   mọi chu kỳ, mọi kịch bản. Bắt buộc phải bằng nhau, vì cùng ngưỡng, cùng
   EWMA, cùng delay, chỉ khác chỗ đứng — nếu không bằng là refactor sai.
2. `organism_key.xml` v2 (auto/pattern) tái tạo trace của nó, kể cả `drift`.
3. **Gate đóng = standalone**: body với mọi cổng đóng cho snapshot **giống
   hệt** hai lamina chạy riêng (tiêu chí cũ, chạy lại).
4. **Kênh có nhớ**: truyền mở, nhận đóng → `channel.offered` có giá trị,
   `age` tăng, X′ bên nhận **không đổi**, provenance = `waiting`. Đây là
   trạng thái thiết kế cũ không có, nên phải có test riêng.
5. 255 test cũ: những test nói về `PermeabilityGate` / `controller=` viết
   lại theo v2; phần còn lại xanh nguyên.

### Phase 3 — Liền kề, giới hạn, mặt tiếp giáp (rule 7–9 trên cơ thể ≥ 3 lamina)

Rule 7 với hai lamina là tầm thường. Cần một lamina thứ ba để chứng minh:
test dựng `_MINIMAL_LAMINA` thứ ba trong tmp (đã có tiền lệ trong
`test_organism.py`) ở level 3, rồi:

- channel `level 1 → level 3` bị từ chối, thông báo nêu cả hai level;
- `1 → 2 → 3` qua hai channel parse được;
- lamina ở level 2 có 4 cổng lên + 4 xuống parse được, cổng thứ 5 một hướng
  bị từ chối;
- hai channel cùng lamina cùng hướng khác composite bị từ chối (rule 9).

Không đụng XML ship. Đây là phase chứng minh rule, không phải phase thêm hành vi.

### Phase 4 — Hành vi mới: xả lũ, trọng số, key nhu cầu, receive-auto

Chỉ bắt đầu sau Phase 2 xanh, và **mỗi mục là một bảng đo** như mọi phase
trước. Số ngưỡng dưới đây *chưa có* — điền sau khi đo, theo đúng cách Phase 5
cũ suy `open_above` từ dung sai bên nhận.

| Mục | Kịch bản đo | Ghi gì |
|---|---|---|
| 4a **Xả lũ** (C4) | HR 200, `ta_pump_deviation` nổ; so `rate` hiệu lực với và không có receive-auto | Xả lũ phía truyền + receive-key rate 0.2 → CO_ref đi chậm như cũ (chứng minh C6). Xả lũ *cả hai phía* → CO_ref nhảy một bước; kiểm tra breaker cơ thể có kêu không |
| 4b **Trọng số** (C5) | `rk_pump weight=0.5`, HR 35 | CO_ref đậu ở `5.0 + 0.5·(3.39−5.0) = 4.20`, không phải 1.70. Test khẳng định đúng công thức, và một test khẳng định `weight=1` bằng hệt trace v1 |
| 4c **Key nhu cầu** (transmit-key, C3) | `tk_o2_demand` key trên `transport_state` của hô hấp; ép SpO2 tụt | Cổng truyền mở **vì bên nhận cần**, dù CO bình thường (auto không nổ). Đây là hành vi mà thiết kế cũ *không thể* có, và là lý do có transmit-key |
| 4d **Receive-auto** | `ra_transport_crisis`; ép SpO2 tụt + HR 200 | Bên nhận hấp thụ rate 1; so với 4a |
| 4e **Chatter** | mọi trigger mới, tín hiệu đậu trên ngưỡng, 400 chu kỳ, tách khỏi mô hình | ≤ 1 transition, như Phase 3/5 cũ |
| 4f **Drift** | pattern trigger của `organism_key.xml` | telemetry vẫn báo `drift` sau khi đổi chỗ |

Điểm phải cảnh giác, ghi trước khi đo: 4c tạo **vòng qua hai lamina** (hô hấp
trình nhu cầu → tuần hoàn mở → CO sang → DO2 đổi → nhu cầu đổi). Đây chính là
algebraic loop của Gomes, giờ *hiện ra trong khai báo*. Thứ tự Gauss-Seidel
một chiều + EWMA phía nhận là hai tuyến phòng thủ; test settling (pattern
Phase E) là bắt buộc cho 4c.

### Phase 5 — Snapshot, API, UI

- `snapshot["gates"]` → `snapshot["channels"]`: mỗi entry = channel + hai
  phía, mỗi phía là danh sách cổng với `kind`, `open`, `flood`, `reason`,
  state; cộng `offered`, `age`, `state ∈ {crossing, waiting, held, decaying, shut}`.
  `waiting` là trạng thái mới trên màn hình và **phải khác màu** với `held`:
  một cái là "bên gửi đã đưa, bên nhận chưa lấy", một cái là "đã lấy, giờ
  cũ" — cùng họ với con bug lâu đời nhất.
- `GET /api/organism` v2: `levels`, `channels[…].transmit/receive[…]`.
  Frontend `GateSpec` → `ChannelSpec`, `GateSpec` (kind, side).
- `OrganismMap`: lamina xếp **theo level** (trục dọc = stack, đúng chữ
  "trên/dưới" của Lee) thay vì trái→phải theo thứ tự khai; một channel là
  một cạnh với **hai van** — một ở mỗi đầu — glyph khác nhau cho auto/key,
  và trạng thái xả lũ có hiển thị riêng. Không file nào gọi tên lamina/cổng.
- `InputRail` inbound provenance: thêm `waiting`.
- **5b — nợ đã thấy khi đọc code (2026-09-02)**: `BodyDashboard` thiếu hai
  guard mà `TwinDashboard` đã có — so `organism_id` của tick với schema
  (stream đã trả `organismId`) và đánh dấu stream chết. Picker body vừa thêm
  làm nó với tới được. Làm ở đây vì đang đụng đúng file; nhỏ, tách commit.

### Phase 6 — Docs

`docs/laminae.md` (mục "Adding a lamina" thêm: khai `level`, mặt tiếp giáp,
≤8 cổng), comment đầu `organism.xml` (12 rule), `PERMEABILITY_GATES_PLAN.md`
thêm một đoạn đầu chỉ sang file này và nói rõ cái gì bị thay thế
(`PermeabilityGate`, `controller=`), cái gì giữ.

---

## 6. Câu hỏi cần Lee chốt trước khi bắt đầu Phase 1

| Q | Câu hỏi | Nếu không có câu trả lời, plan giả định |
|---|---|---|
| Q1 | Tuần hoàn và hô hấp là **hai lớp liền kề** (1 và 2) hay **hai lớp cùng mức**? Cả hai file đang khai `level="1"`. Nếu cùng mức thì theo rule 7 mối nối CO→CO_ref **không được tồn tại**, và cần một lamina trung gian (hoặc một định nghĩa "liền kề ngang") | Liền kề: tuần hoàn 1, hô hấp 2 (C7). Chiều "lên" là chiều CO đi |
| Q2 | "Một composite duy nhất" là **một composite / lamina** hay **một composite / lamina / hướng**? Cái đầu chặt hơn nhiều: `pump_state` sẽ phải là mặt tiếp giáp cho cả lớp trên lẫn lớp dưới | Một / hướng (C9) |
| Q3 | Auto gate "xả tung bất chấp cấu hình khác" — *khác* là của **phía mình** (weight, rate, delay) hay gồm cả **cổng nhận của lamina kia**? | Chỉ phía mình (C4). Lý do ở bảng §2, dòng SIS |
| Q4 | "Bao nhiêu dữ liệu đi qua" theo trọng số: nhân vào **giá trị** hay vào **độ lệch khỏi giả định của bên nhận** (C5)? Nhân vào giá trị thì CO 4.8 với weight 0.5 thành 2.4 L/min | Độ lệch (C5) |
| Q5 | Cổng nhận với key `identity` (khớp *loại* tín hiệu, không khớp hình dạng) có được coi là cổng thật không, hay Lee muốn mọi key đều là **pattern**? Nếu bắt buộc pattern, body mặc định sẽ phải khai một key cho "pump bất thường" ở phía nhận — mà "bất thường" là *mismatch*, không phải match, nên cần hai key (cao/thấp) thay vì một | `identity` là hợp lệ. Dopamine gắn vào receptor là khớp *loại* phân tử |
| Q6 | Với 4 slot / hướng: Lee muốn **đúng 4 loại** (transmit-auto, transmit-key, receive-auto, receive-key — mỗi loại một) hay **tối đa 4 bất kỳ**? | Tối đa 4 bất kỳ (C8), rule 6 đã chặn hai cổng đổ vào một attribute |

Q1 và Q4 là hai câu **đổi số đo**; còn lại đổi rule, làm sau cũng được.

---

## 7. Không làm (để khỏi bị cuốn)

- **Lambda / `<transform>`** — v2, và chỉ khi có một nhu cầu cụ thể mà trọng
  số không biểu diễn được. Khi làm: biểu thức máy-đọc-được là trường mới,
  không eval `<formula>`.
- **Organism-as-lamina** (đệ quy theo Gomes) — hướng universal đúng, nhưng
  chưa có cơ thể thứ hai để cần nó. Ghi nhận, không dựng.
- **Key thích nghi / weight học** — vẫn chờ telemetry drift (G7). Rule 5 đã
  sẵn chỗ khai `learnable` cho `weight`.
- **Cross-laminar có phép** (kiểu "cross-layer" của OSI) — Lee cấm tuyệt đối;
  không thêm cửa sau `allow_cross_level`.
- **Tái hiệu chuẩn R**, **artwork hô hấp** — vẫn là task riêng.

## 8. Trình tự phụ thuộc và khối lượng

```
commit khối đang dở  →  Phase 0
Phase 1 → 2 → 3
Phase 4 ∥ Phase 5 (sau 2)
Phase 6
```

Khối lượng lớn nhất: Phase 2 (`_gate_pass` hai phía + channel state) và
Phase 5 (`OrganismMap` xếp theo level, hai van một cạnh). Phase 1 và 3 gần
như toàn parser + test, có tiền lệ chép theo. Phase 4 là phase **đo**, thời
gian nằm ở việc đo chứ không ở code.

## 9. Tham khảo

- Borgdorff, Hoekstra et al. — *A framework for multi-scale modelling*, Phil. Trans. R. Soc. A 372:20130378 (2014). Port riêng, conduit/filter/mapper, MML.
- Gomes, Thule, Broman, Larsen, Vangheluwe — *Co-simulation: State of the art*, arXiv 1702.00686. Gauss-Seidel/Jacobi, algebraic loops, hierarchical co-simulation.
- Wang, Huang, Bian — *OmniBioTwin*, arXiv 2606.11264. Coupling operators theo cặp có hướng; đa nhịp.
- ISO 23247-6:2026 — Digital twin composition.
- OSI closed-layer principle; Schmitt trigger / deadband; Safety Instrumented Systems & layers of protection; kênh ion voltage-gated vs ligand-gated — link ở bảng §2.
- `PERMEABILITY_GATES_PLAN.md` — thiết kế bị thay thế một phần; mọi số đo ở đó vẫn đúng và được tái dùng làm baseline.
- `docs/laminae.md` — ba bài học của lamina thứ hai.
