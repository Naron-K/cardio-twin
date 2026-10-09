# Lõi skeleton của Digital Twin — tài liệu mô tả để vẽ sơ đồ

> **Mục đích:** mô tả đầy đủ *cơ chế* của phần lõi (engine), đủ để một người
> khác vẽ lại sơ đồ kiến trúc mà không cần đọc code.
>
> **Phạm vi:** chỉ mô tả bộ khung tổng quát — engine đọc file `.xml` mô tả
> mô hình rồi mô phỏng. **Không** nhắc tới bất kỳ lamina cụ thể nào và không
> nhắc tới công thức chuyên ngành. Mọi thứ dưới đây là *domain-neutral*:
> đổi file XML là đổi mô hình, code không đổi.
>
> **Nguyên tắc thiết kế xuyên suốt (nên thể hiện được trong hình vẽ):**
> 1. Chuyên gia miền sửa **XML**, lập trình viên sửa **code**. Hai thứ tách rời.
> 2. Mọi thứ **đi qua cổng (gate)**. Kể cả tín hiệu lỗi đi ngược.
> 3. Một cổng **không bao giờ nhìn thấy attribute** bên trong composite —
>    nó chỉ thấy **một con số** mà composite trình ra.
> 4. Giá trị đến từ bên ngoài là **bất khả xâm phạm**; vòng lặp nội bộ chỉ
>    được sửa cái do chính nó tính ra.
> 5. Cái gì **được phép học** thì phải **khai báo cận (clamp)** trước.

---

## 1. Toàn cảnh: hai tầng

```
    +----------------------- TẦNG 2: ORGANISM (cơ thể) -----------------------+
    |  organism.xml  ->  danh sách lamina + các CHANNEL nối chúng + thứ tự tick |
    |                                                                          |
    |   +-- LAMINA A --+      CHANNEL (dây)        +-- LAMINA B --+            |
    |   | UniversalTwin |==[transmit gates]==[receive gates]==>| UniversalTwin| |
    |   | + Feedback    | <------- backward pass (delta) ------ | + Feedback   | |
    |   |   Controller  |                                      |   Controller | |
    |   +---------------+                                      +--------------+ |
    +--------------------------------------------------------------------------+
              ^                                                   ^
              | lamina_X.xml                                      | lamina_Y.xml
    +---------+------------- TẦNG 1: LAMINA (một hệ) -------------+-----------+
    | attributes -> functions -> composites -> segments -> outcomes -> tags   |
    |                        -> feedback controller                           |
    +-------------------------------------------------------------------------+
```

- **Tầng 1 — `UniversalTwin`** (một lamina = một hệ con): biết cách tự tính
  chuỗi hàm của mình và tự chạy vòng phản hồi nội bộ của mình. Chạy được
  **một mình**, không cần biết có ai khác tồn tại.
- **Tầng 2 — `Organism`** (cơ thể): nhiều lamina + topology nối chúng.
  Thứ duy nhất tầng này sở hữu mà không lamina nào sở hữu được là **THỨ TỰ**:
  khi nào một giá trị được phép đi từ lamina này sang lamina kia.
- Topology *không* nằm trong file lamina nào cả — viết nó vào một file
  lamina sẽ làm lamina đó không chạy độc lập được nữa.

---

## 2. Từ điển thành phần (các "node" cần vẽ)

### 2.1 Attribute — đơn vị giá trị

Một attribute **không phải một con số**, mà là một gói:

| Trường | Ý nghĩa |
|---|---|
| `id`, `name`, `unit` | định danh, đơn vị |
| `source` | **SENSOR** / **PRELIMINARY** / **INTER_LAMINA** (xem dưới) |
| `physio_min`, `physio_max` | dải hợp lệ đã khai báo — dùng để chuẩn hoá |
| `baseline` | giá trị nghỉ (khi chưa ai ghép vào) |
| `noise_sigma` | biên độ nhiễu cho feed tổng hợp |
| `value_external` = **X'** | kênh ngoài: cảm biến, hoặc kết quả chuỗi hàm |
| `value_feedback` = **X''** | kênh phản hồi: lượng hiệu chỉnh do vòng lặp sinh ra |
| `normalised` | giá trị trong không gian **[0,1]** |
| `confidence` | 1.0 sensor · 0.9 tính ra · 0.5 chưa ghép · gate tự khai |
| `computed_by`, `depends_on` | hàm nào tính ra nó, phụ thuộc ai |
| `provenance` | nếu là INTER_LAMINA: đến từ channel/gate nào, tuổi, độ mở cổng |

**Phương trình nền tảng của cả hệ thống (vẽ to, ở vị trí trung tâm):**

```
        X  =  X'  +  X''
              ^        ^
              |        +-- chỉ vòng phản hồi được ghi (apply_feedback)
              +----------- chỉ nguồn ngoài / chuỗi hàm được ghi (set_value)

        normalised = clamp01( (X - physio_min) / (physio_max - physio_min) )
```

Phép cộng X' + X'' do **coupling kernel** thực hiện (mặc định `additive`,
có thể thay bằng kernel khác — xem §6).

**Ba loại `source` — ai được phép ghi X':**

```
   SENSOR        đo từ ngoài.  Thiêng liêng: vòng phản hồi KHÔNG BAO GIỜ chạm.
   PRELIMINARY   do chuỗi hàm của chính lamina này tính.  <- nguồn DUY NHẤT
                                                             được ghi X''.
   INTER_LAMINA  do lamina KHÁC đẩy sang qua channel.  Cũng thiêng liêng:
                 đó là ground truth của người khác.
```

### 2.2 Function — một mắt xích trong chuỗi tính

`<function id step formula inputs output>`. Metadata nằm trong XML,
phần cài đặt (code) nằm trong lớp con và đăng ký vào `_function_registry`.
Engine sắp xếp các hàm **theo `step`** rồi giải đệ quy theo `depends_on`,
có bộ chặn vòng lặp vô hạn. Hàm nào ném lỗi thì attribute đó **giữ giá trị
chu kỳ trước** và được ghi vào danh sách `failed_attributes` — vì một số cũ
và một số mới trông giống hệt nhau, phải có chỗ nói ra sự khác biệt đó.

### 2.3 Composite — nhóm attribute, và là **mặt tiếp xúc** của lamina

Đây là khái niệm trung tâm nhất. Một composite gồm N attribute và
**hai vector song song, cùng độ dài N, hai chức năng hoàn toàn khác nhau**:

```
   composite  C = { a1, a2, ..., aN }

   absorption_vector   A = [A1 ... AN]   -- HẤP THỤ: gộp N attribute thành 1 số
                                            (được phép HỌC, nếu khai báo clamp)

   distribution_vector D = [w1 ... wN]   -- PHÂN PHỐI: chia tín hiệu hiệu chỉnh
                                            ngược lại cho từng attribute
                                            (vòng phản hồi chỉ ĐỌC, không ghi;
                                             chỉ chuyên gia sửa XML mới đổi được)
```

Hai vector cố tình tách rời để vòng học và vòng phản hồi không giành nhau
cùng một dãy số. Cả hai đều là **hệ số nhân đầy đủ**, tổng **không** bị
chuẩn hoá về 1 (chuyên gia viết tổng = 2 thì tổng vẫn là 2 suốt vòng đời).

**State value** — một composite tự tóm tắt thành một số:

```
        s = SUM(v_i * A_i) / SUM(A_i)     với v_i = normalised của attribute i
                                          -> s luôn nằm trong [0,1]
```

- Attribute nào chưa đọc được (None) thì bị **loại cùng với trọng số của nó**
  — không được kéo tóm tắt về 0 như thể "đo được và bằng 0".
- Nếu mọi trọng số còn lại đều bằng 0 thì trả về **None** (không phải 0.0):
  "không có tin" khác với "trạng thái bằng 0".

**Đây là chỗ hai chiều gặp nhau:** absorption vector là bước gộp *đi ra*,
distribution vector là bước tán *đi vào*.

### 2.4 Segment — phân vùng logic của một lamina, và **nơi chứa mục tiêu**

Segment chia một lamina thành các mảng có tên. Đây là **cấp phân chia
trong lòng lamina**, song song với composite chứ không phải cùng một thứ:

```
   COMPOSITE  = nhóm attribute để GỘP THÀNH MỘT SỐ và trình ra ngoài
                (hướng ra ngoài: cổng, channel, tag đều nói chuyện với nó)

   SEGMENT    = nhóm attribute + composite + function để TỰ ĐÁNH GIÁ
                (hướng vào trong: lamina tự chấm điểm mình theo từng mảng)
```

```
   <segment id name>
     <description/>
     <attributes>  a1, a2, a3        </attributes>   -- tổ chức / hiển thị
     <composites>  c1, c2            </composites>   -- tổ chức / hiển thị
     <functions>   f1, f2, f3        </functions>    -- tổ chức / hiển thị
     <behavioural_outcomes>                          -- PHẦN CÓ TÁC DỤNG RUNTIME
       <outcome id name attribute target tolerance unit/>
       <outcome .../>
     </behavioural_outcomes>
   </segment>
```

**Hai nửa của segment, và phải vẽ tách chúng ra:**

| Nửa | Nội dung | Vai trò |
|---|---|---|
| **Nửa tổ chức** | 3 danh sách `attributes` / `composites` / `functions` | bản đồ: mảng này gồm những gì. Engine **không** dùng nó để chặn hay để tính — nó đi thẳng ra API và lên màn hình để người đọc hiểu lamina được chia thế nào |
| **Nửa chức năng** | `behavioural_outcomes` | **đây mới là thứ vòng lặp chạy trên đó**: segment là nơi duy nhất outcome tồn tại |

**Vì sao segment là mắt xích không thể bỏ:** mọi đường vào vòng phản hồi
đều đi qua nó.

```
   evaluate_all_outcomes()  ->  { segment_id: [feedback_object, ...] }
                                  \_________/
                                  chính hình dạng này là đầu vào bước 1
                                  của vòng nhanh, và là đầu vào của
                                  Identifier.emit_tags

   tra cứu tolerance của một outcome  ->  duyệt qua các segment
   tag khai `outcome="..."`            ->  phải khớp một outcome trong một segment
   <backprop from="...">               ->  luật 14 kiểm tra outcome đó có tồn tại
                                           trong segment của lamina NHẬN không
   vòng chậm (MetaState)               ->  lập chỉ mục theo outcome, tức là
                                           theo cái segment khai ra
```

Nói gọn: **không có segment thì không có outcome; không có outcome thì
không có deviation; không có deviation thì cả vòng phản hồi lẫn đường về
đều không có gì để chạy trên đó.** Một lamina không khai segment nào vẫn
tính chuỗi hàm và vẫn đẩy giá trị qua channel được — nhưng nó trở thành
mô hình *câm*: không tự đánh giá, không phát tag, không học.

**Quan hệ giữa hai cách chia (nên vẽ thành một hình riêng — sơ đồ 11):**
một attribute có thể vừa nằm trong một composite (để được gộp và đi ra
ngoài) vừa nằm trong một segment (để được chấm điểm). Hai cách chia
**chồng lên nhau, không lồng vào nhau** — chúng cắt cùng một tập attribute
theo hai trục khác nhau.

```
                    +---- composite C1 ----+   +---- composite C2 ----+
   segment S1  |    |   a1      a2         |   |                     |
               |    +----------------------+   |                     |
   segment S2  |    |           a3         |   |   a4      a5        |
                    +----------------------+   +---------------------+
                     ^ gộp theo chiều DỌC        ^ gộp theo chiều DỌC
     ^ chấm điểm theo chiều NGANG (outcome của S1, outcome của S2)
```

### 2.5 Behavioural Outcome — mục tiêu và sai số

**Luôn sống bên trong một segment.** Không có outcome đứng tự do.

`<outcome attribute target tolerance>` do chuyên gia miền khai báo.
Mỗi chu kỳ nó sinh ra một *feedback object*:

```
   deviation        = actual - target
   within_tolerance = |deviation| <= tolerance
   status           = normal | above | below
```

Và **sai số chuẩn hoá** — con số duy nhất được phép đi xa (qua tag, qua
channel), vì nó không mang đơn vị:

```
        E = sign(dev) * max(0, |dev| - tol) / tol
                       \____________________/
                       vùng chết: trong tolerance thì E = 0 tuyệt đối
```

Chia cho tolerance là thứ làm nó **phổ quát**: sai số đo bằng đơn vị này và
sai số đo bằng đơn vị kia trở thành cùng một loại số.

### 2.6 Tag — sợi dây nối "mục tiêu sai" tới "composite nào phải sửa"

```
   <tag id outcome deviation_type emitter gate_kernel polarity>
     <targets>
       <target address="[lamina:]composite" weight polarity/>   <- nhiều target
     </targets>
     <params gain decay threshold_k saturation epsilon_ratio/>
   </tag>
```

- **`polarity`**: dấu của quan hệ *"tăng composite này thì outcome kia lên hay
  xuống"*. `-1` = hiệu chỉnh (mặc định), `+1` = khuếch đại, `0` = **chỉ theo
  dõi** (vẫn phát tag, vẫn ghi log, nhưng không sinh X'').
- Polarity có thể khai **riêng cho từng target**, vì cùng một outcome nhưng
  quan hệ với mỗi composite có thể ngược dấu nhau.
- **`weight` của target**: toàn bộ deviation được nhân với weight cho *mỗi*
  target — **không** chia nhỏ deviation ra cho các target.
- Địa chỉ target được **phân giải ngay lúc parse**, không phải lúc chạy.

### 2.7 Gate — có **hai loại gate khác nhau**, đừng vẽ lẫn

| | **Gate nội bộ (validation gate)** | **Gate màng (channel gate)** |
|---|---|---|
| Nằm ở | trong một lamina, khối `<gates>` của lamina XML | trên hai đầu một channel giữa hai lamina |
| Canh gì | một **attribute** vừa được tính | một **composite state value** đi qua màng |
| Loại | `range`, `positive`, `consistency`, `soft_range` | `auto_gate`, `key_gate` |
| Khi hỏng | rollback X' về giá trị trước + gắn cờ | không cho giá trị qua, và nói rõ lý do |

**Gate màng — hai giống loài:**

```
   AUTO GATE  (van an toàn / van nội bộ)
       đọc: composite của CHÍNH lamina mà nó đứng trên
       không bao giờ nhìn sang bên kia
       trigger: <threshold>  (ngưỡng trên state / delta / deviation)
             hoặc <pattern>  (khớp hình dạng với composite của chính mình)
       khi bật, được phép "flood": ép rate = 1, bỏ qua weight của PHÍA MÌNH
       (flood KHÔNG ép được phía bên kia mở - nếu không thì van an toàn của
        bên gửi sẽ trở thành lệnh ghi cưỡng bức vào lamina khác)

   KEY GATE   (thụ thể / ổ khoá)
       đọc: cái đang được TRÌNH RA tại channel
            - ở phía nhận: là mặt của bên gửi (giá trị đang được mời)
            - ở phía gửi : là mặt của bên nhận (tức là "nhu cầu" của bên kia)
       metric: identity          - khớp NHÃN (tên composite). Đúng/sai, không có dải
               weighted_distance - khớp HÌNH DẠNG: SUM(w_i*|v_i-ref_i|) / SUM(w_i)
               cosine            - khớp HƯỚNG
       mang theo: weight, rate, on_close, confidence, band_min/band_max
```

**Máy trạng thái chung của mọi gate ngưỡng (vẽ dạng state machine):**

```
        +-------- open_above -------->+
   [ĐÓNG]                          [MỞ]        <- sinh ra ở trạng thái ĐÓNG
        <-------- close_below -------+
              ^ vùng chết (deadband): không có gì xảy ra
              ^ refractory_cycles: giữ nguyên N chu kỳ sau mỗi lần chuyển

   open_fraction = 0.0  khi đóng
                 = 1.0  khi mở (chế độ binary)
                 = sigmoid(k*(v - open_above))  khi mở (chế độ proportional)
```

Hai ngưỡng là **bắt buộc** (không được khai một ngưỡng): dữ liệu có nhiễu,
một ngưỡng duy nhất sẽ bị vượt qua vượt lại mỗi chu kỳ.

**Ba chế độ `aggregate` — con số mà ngưỡng đem ra so:**

```
   state      giá trị hiện tại của composite
   delta      nó đã dịch chuyển bao nhiêu so với chu kỳ trước (None ở chu kỳ 1)
   deviation  |state - reference|  <- HAI CHIỀU: bắt được cả "quá cao" lẫn
                                      "quá thấp" bằng cùng một cặp ngưỡng
```

### 2.8 Channel — sợi dây giữa hai lamina

```
   <channel id from="laminaA:composite" to="laminaB:attribute" time_delay="n">
     <extract mode="state | state_delta"/>       <- chở gì
     <transmit>  ... 1..4 gate ...  </transmit>  <- màng bên gửi
     <receive>   ... 1..4 gate ...  </receive>   <- màng bên nhận
     <backprop from="outcome_id" polarity="+/-1"/>  <- đường về (tuỳ chọn)
   </channel>
```

- **Nguồn luôn là một COMPOSITE**, đích **luôn là một attribute
  `INTER_LAMINA`**. Không có ngoại lệ.
- Dây chở **một con số duy nhất trong [0,1]**: state value, hoặc độ dịch
  chuyển của nó. Trên dây **không có tên attribute nào cả**.
- `time_delay` thuộc về **dây**, không thuộc về lamina nào — nó là thuộc
  tính của đường truyền.

### 2.9 Ba (bốn) túi trạng thái runtime — tách rời có chủ đích

Đây là chi tiết dễ vẽ sai nhất, nên vẽ rõ **các hộp riêng, chủ sở hữu riêng**:

```
   [ FeedbackController._kernel_state ]  key = (tag_id, attribute_id)
     bộ nhớ kernel của vòng nhanh         bị dead-zone snap xoá

   [ Organism._gate_state ]              key = gate_id
     trạng thái mỗi cổng                  controller TRẢ VỀ nguyên trạng thái mới,
                                          container thay thế toàn bộ mỗi chu kỳ

   [ Organism._channel_state ]           key = channel_id
     hàng đợi trễ, cái đang được mời,     PHẢI tách khỏi _gate_state: nếu chung
     tuổi của lời mời, lambda đã dùng     một dict thì controller sẽ xoá mất hàng
                                          đợi trễ giữa lúc nạp và lúc đọc

   [ UniversalTwin._meta_state ]         key = outcome_id
     trạng thái học của vòng CHẬM         SỐNG SÓT qua snap và qua reset
```

Nguyên tắc: **bản khai báo (declaration) không bao giờ là túi trạng thái.**
`Channel`, `AutoGate`, `KeyGate`, `Tag` là khai báo bất biến — trạng thái
chạy nằm ở container.

---

## 3. XML -> runtime (đường nạp mô hình)

```
   lamina_*.xml --> UniversalTwin.__init__
                      |- đăng ký 6 registry kernel mặc định
                      |- _parse_xml   : attributes, functions, composites,
                      |                 gates, segments + outcomes, tags,
                      |                 coupling, behaviour_solver, adaptation
                      |- _parse_tags  : PHÂN GIẢI ĐỊA CHỈ NGAY LÚC NẠP
                      +- _register_functions (lớp con gắn code vào)

   organism*.xml --> parse_organism_v2       : rule 1, 4-13 (tự kiểm tra được)
                 --> load từng lamina
                 --> validate_against_laminae: rule 2, 3, 14
                                               (cần cả hai file mới trả lời được)
                 --> Organism(twins, channels, controllers, gate registry)
```

**Triết lý: mọi lỗi cấu trúc phải nổ lúc PARSE, không phải lúc chạy.**
Một topology sai là một *phát biểu sai về mô hình*, và thời điểm rẻ nhất
để nói ra là trước khi bất cứ thứ gì chạy.

---

## 4. Vòng đời — phần cần vẽ thành sơ đồ tuần tự

### 4.1 Vòng NHANH của một lamina (`FeedbackController.step()`)

```
 1  ĐÁNH GIÁ      duyệt TỪNG SEGMENT -> từng outcome trong nó -> deviation,
                  within_tolerance.  Kết quả có hình dạng
                  { segment_id: [feedback_object, ...] } và đây là dữ liệu
                  gốc mà mọi bước sau đều đọc lại.
    (1b) nạp EWMA hiệu năng cho vòng chậm (nếu bật)

 2  PHÁT TAG      quét TOÀN BỘ outcome mỗi chu kỳ (poll, không phải event)
                  emitter quyết định có phát không (mặc định: |dev| > tol)

 3  CHẠY KERNEL   với mỗi (tag x attribute PRELIMINARY trong composite đích):
                     d   = deviation / tolerance
                     w   = distribution_weight(attr) * target_weight
                     x'' = gate_kernel(prev_state, d, w, params)
                  * attribute không phải PRELIMINARY thì BỎ QUA (X' thiêng liêng)
                  * tag còn trạng thái cũ vẫn chạy dù chu kỳ này không phát,
                    để X'' còn suy giảm về 0 thay vì đóng băng

 4  CỘNG DỒN      tổng x'' của mọi tag, gom theo từng attribute

    (4b) VÒNG CHẬM: mỗi N chu kỳ - chỉnh gain + operating point (chuyển giao êm)

 5  ÁP DỤNG       attr.apply_feedback(tổng) -> ghi X'', có kẹp biên an toàn
                  bị kẹp thì cảnh báo (thường là dấu polarity bị ngược)

 6  DEAD-ZONE SNAP  |X''| < epsilon (tỷ lệ với dải của attribute) -> X'' = 0
                    và XOÁ mọi kernel state chạm tới attribute đó
    CẦU DAO MỀM     feedback_norm > max_norm -> hoàn tác toàn bộ X'' chu kỳ này,
                    xoá sạch kernel state, đánh dấu diverged

 7  GIẢI LẠI       chạy behaviour_solver ĐÚNG MỘT LẦN
                     algebraic_chain : chạy chuỗi hàm một lượt (mặc định)
                     fixed_point     : lặp tới khi hội tụ (cho mô hình có vòng kín);
                                       không hội tụ thì KHÔNG ném lỗi nhưng ghi
                                       tên từng attribute còn dao động + độ dư

 8  HỌC HẤP THỤ    composite nào khai báo learns_from thì cập nhật
                   absorption_vector - CUỐI CÙNG, để không cổng nào thấy ý nghĩa
                   của composite đổi giữa chừng chu kỳ nó đang quyết định
```

**Kernel mặc định `sigmoid_leaky_tanh`** (vẽ thành 3 khối nối tiếp):

```
    G   = 1 / (1 + exp(-k*(|d| - 1)))          <- cổng sigmoid: dập nhiễu
                                                  trong vùng tolerance
    raw = polarity * gain * w * G * d * tol    <- độ lớn thô, trả về đơn vị gốc

    x'' = a_max * tanh( ((1-lambda)*x''_prev + raw) / a_max )
                          \__________/                <- tích phân rò rỉ:
                          tự suy giảm về 0               có ký ức, nhưng quên dần
                                                       <- tanh: bão hoà, không nổ
```

Điểm bất động: khi d = 0 thì raw = 0, số hạng rò rỉ kéo x'' về 0.
Sự suy giảm nằm **bên trong kernel**, khung không suy giảm lần thứ hai ở ngoài.

### 4.2 Vòng của cơ thể (`Organism.tick()`)

**THỨ TỰ LÀ TOÀN BỘ Ý NGHĨA CỦA HÀM NÀY.** Vẽ đúng thứ tự này:

```
  (1) GHI CẢM BIẾN   vào từng lamina

  (2) TÍNH CHUỖI     compute_all() trên MỌI lamina
                     ^ gate phải đọc giá trị SAU khi tính, nếu không nó chở
                       số của chu kỳ trước mà tưởng là chu kỳ này

  (3) LƯỢT CỔNG      chạy từng channel theo thứ tự khai báo (chi tiết §4.3)
                     ^ đặt TRƯỚC vòng phản hồi, vì giá trị liên lamina là X' -
                       nó là ĐẦU VÀO của chu kỳ bên nhận, không phải phản hồi

  (4) VÒNG PHẢN HỒI  controller.step() trên MỌI lamina  (§4.1)

  (5) LƯỢT NGƯỢC     back pass - chở sai số của bên nhận quay về  (§4.4)
                     ^ đặt SAU (4), vì outcome chưa được đánh giá trước khi
                       vòng phản hồi chạy. Đặt ở (3) thì sẽ chở sai số của
                       chu kỳ TRƯỚC -> phạt bên gửi hai lần cho một lỗi.

  (6) CẦU DAO CƠ THỂ tổng feedback_norm > max_total_norm
                     -> gates_locked: MỌI cổng đóng, nhưng các lamina vẫn tự
                        chạy. Cái hỏng là sự ghép nối, không phải lamina.
```

Hai hệ quả cần chú thích trên hình:
- **Bên nhận thấy giá trị NGAY trong tick đó**, vì bước (4) kết thúc bằng một
  lần giải lại. `time_delay = 0` nghĩa là 0 thật, không có độ trễ ngầm nào để
  dựa vào; bộ lọc EWMA là toàn bộ phòng tuyến chống dao động.
- **Đóng góp của bên gửi trễ một chu kỳ phản hồi**: gate đọc giữa (2) và (4),
  nên nó mang X' của chu kỳ này và X'' của chu kỳ trước.

### 4.3 Một lần vượt màng (`_run_channel`) — sơ đồ quan trọng nhất

```
  LAMINA GỬI                     DÂY (CHANNEL)                     LAMINA NHẬN
  ----------                     -------------                     -----------

  composite nguồn
   a1 v1 --+
   a2 v2 --+--> (x) absorption vector A --> s trong [0,1]
   a3 v3 --+        BƯỚC HẤP THỤ            |
                                            |  carry = state | state_delta
                                            v
                            === MÀNG GỬI (transmit) ===
                            auto gate xét TRƯỚC, key sau
                            song song: bất kỳ cổng nào mở
                            thì phía đó mở (tối đa 4/mặt)
                            flood => chỉ ép PHÍA NÀY
                                        |
                                  tx.fraction > 0 ?
                            có --> ĐẶT LỜI MỜI (offered, age = 0)
                            không -> lời mời cũ nằm đó và GIÀ ĐI (age++)
                                        |
                                        v
                            === MÀNG NHẬN (receive) ===
                            key gate khớp cái đang được mời
                            (theo nhãn hoặc theo hình dạng)
                                        |
             open_fraction = tx.fraction * rx.fraction
             lambda = open_fraction * tx.weight * rx.weight  <- GHI NHỚ LẠI,
                                                                đường về sẽ dùng
                                        v
                   +------- BA (BỐN) CHẶNG HẤP THỤ -------+
                   | 1. TRỄ      ring buffer n chu kỳ     | chưa đầy => chưa
                   |             (thuộc về DÂY)           | giao gì, đó là
                   |                                      | trạng thái thật
                   | 2. ĐỔI ĐƠN VỊ - do bên NHẬN làm      | state: min + s*span
                   |    band? ngoài dải => TỪ CHỐI,       | delta: baseline+s*span
                   |    KHÔNG kẹp                         |
                   | 3. TRỌNG SỐ                          | target = base
                   |    nhân vào ĐỘ LỆCH so với giả định  |   + w*(x - base)
                   |    hiện có, KHÔNG nhân vào giá trị   |
                   | 4. EWMA thông thấp                   | x <- x + rate*open
                   |    rate do bên NHẬN quyết định       |     *(target - x)
                   +--------------------+-----------------+
                                        v
                     attribute INTER_LAMINA của bên nhận
                     + provenance: channel, gate, độ mở, tuổi, rate, weight, ...
```

**Khi cổng đóng — bên nhận cầm gì?** (`on_close`)

```
   hold                giữ nguyên giá trị cuối, nhưng ĐẾM TUỔI (age++)
   decay_to_baseline   trôi dần về baseline đã khai báo
```

**Một từ mô tả trạng thái channel** (dùng cho màu sắc trong hình):

```
   crossing   hai màng mở VÀ thật sự có số vượt qua
   waiting    bên gửi đã đặt lời mời, bên nhận chưa lấy   <- trạng thái mà
                                                             thiết kế một-van
                                                             không diễn tả được
   held       bên nhận đang giữ giá trị cũ, đang già đi
   decaying   đang trôi về baseline
   shut       không có gì
```

Ngoài ra channel còn báo `saturated`: **tên** những attribute đã vượt khỏi dải
tự khai của chúng. State value sống trong [0,1] *theo cấu tạo*, nên giá trị
vượt trần bị chuẩn hoá thành 1.0 và phần dư không đi qua dây được — chuyện đó
phải được **gọi tên**, không được im lặng.

### 4.4 Lượt ngược — back pass

```
        outcome của LAMINA NHẬN sai
              E = sign(dev) * max(0, |dev| - tol) / tol
                    |
                    v
        delta  =  polarity  x  lambda  x  E
                     |            |
                     |            +-- ĐÚNG con số lambda mà lượt đi đã dùng
                     |                trong chu kỳ NÀY:
                     |                cổng đóng   => lambda = 0 => không quy trách
                     |                cổng mở nửa => trả về một nửa
                     +--------------- dấu của quan hệ ghép nối trên chính dây này
                    v
        composite NGUỒN học lại absorption vector của mình
```

**Cái làm cho nó phổ quát là những gì nó KHÔNG làm:**
không có ma trận chuyển vị, không có chain rule, không có gì biết hình dạng
của lamina nào. Sai số của bên nhận là **một số vô hướng**, cổng nó đi qua
là **một số vô hướng**, tích của chúng là **một số vô hướng** mà composite
gửi học trên đó. Cơ thể 10 lamina định tuyến sai số y hệt cơ thể 2 lamina.

**Khẩu hiệu nên ghi lên hình: "sai số cũng là hàng hoá, và hàng hoá phải qua cổng."**

Các trạng thái đường về cần vẽ (vì một đường về im lặng trông y hệt một
đường về đang hoạt động): `idle · breaker · unevaluated · no-scale ·
in-tolerance · shut · unreadable · learned · refused`.

### 4.5 Bước học của absorption vector

```
    s = SUM(v_i*w_i) / SUM(w)     =>     ds/dw_i = (v_i - s) / SUM(w)

    dw_i = rate * deviation * (v_i - v_trung_binh)   <- gradient được CHIẾU lên
                              \_______________/         mặt phẳng giữ nguyên SUM(w)

    rồi clamp mỗi w_i vào [clamp_min, clamp_max]; phần dư bị clamp cắt được
    TRẢ LẠI cho các trọng số còn tự do  =>  SUM(w) sống sót cả qua clamp
```

- Attribute nằm đúng trung bình của composite thì **không** đổi trọng số —
  đúng, vì nó không mang thông tin về hướng nào cần đi.
- Chiếu để **SUM(w) không trôi**: SUM(w) chính là bất biến khiến state value
  còn là tích trong A·X. Nếu SUM(w) trôi, sau vài bước học hai đại lượng đó
  **đi ngược hướng nhau** — tức là đổi dấu ngay trên con số đang vượt màng.
- Giữ nguyên **tổng đã khai báo**, không phải giữ tổng bằng 1.
- Muốn học thì XML phải khai đủ **bốn** thứ: `learns_from`, `learning_rate`,
  `clamp_min`, `clamp_max`. Thiếu một cái là lỗi parse.

### 4.6 Vòng CHẬM (adaptive) — hai thang thời gian

```
   VÒNG NHANH (mỗi chu kỳ)          VÒNG CHẬM (mỗi N chu kỳ, N = cadence)
   ------------------------         ------------------------------------
   kernel state, tạm thời           MetaState, bền vững
   bị dead-zone snap xoá sạch       SỐNG SÓT qua snap và qua reset
   sinh ra X'' ngay lập tức         KHÔNG tự phát ra hiệu chỉnh nào

                                    đọc:   perf_ewma = EWMA(|deviation chuẩn hoá|)
                                    chỉnh: gain  (quy tắc MIT: hướng nào vừa làm
                                                  tốt lên thì đi tiếp, xấu đi thì
                                                  đảo chiều)
                                           operating_point (dịch điểm làm việc;
                                                  chuyển giao êm: trừ đúng lượng
                                                  đó khỏi tích phân của vòng nhanh
                                                  để tổng tác động không nhảy)

   cadence = 0  =>  vòng chậm TẮT HOÀN TOÀN, hành vi y hệt như chưa từng có nó
```

---

## 5. Bảng công thức (để ghi chú thích trên hình)

| Tên | Công thức | Ở đâu |
|---|---|---|
| Ghép kênh | `X = X' + X''` | mọi attribute |
| Chuẩn hoá | `v = clamp01((X - min)/(max - min))` | mọi attribute |
| State value | `s = SUM(v_i*A_i) / SUM(A_i)` | composite (hấp thụ) |
| Sai số chuẩn hoá | `E = sign(d)*max(0,|d|-tol)/tol` | outcome |
| Cổng sigmoid | `G = 1/(1+exp(-k*(|d|-1)))` | gate kernel |
| Tín hiệu thô | `raw = polarity*gain*w_i*G*d*tol` | gate kernel |
| Tích phân rò rỉ | `x'' = a*tanh(((1-lam)*x''_prev + raw)/a)` | gate kernel |
| Độ mở tổng | `open = tx_fraction * rx_fraction` | channel |
| Độ dẫn | `lambda = open * tx_weight * rx_weight` | channel |
| Trọng số nhận | `target = base + w*(x - base)` | absorb chặng 3 |
| Thông thấp | `x <- x + rate*open*(target - x)` | absorb chặng 4 |
| Đường về | `delta = polarity * lambda * E` | back pass |
| Học hấp thụ | `dw_i = rate*delta*(v_i - v_tb)` | composite |
| Khoảng cách khoá | `SUM(w_i*|v_i-ref_i|) / SUM(w_i)` | key gate |

---

## 6. Các điểm cắm mở rộng (registry)

Vẽ thành một dãy ổ cắm — đây là lý do engine được gọi là "universal":

```
   UniversalTwin (6 registry)
     |- coupling           additive                       X' + X'' ghép thế nào
     |- deviation          absolute                       tính deviation thế nào
     |- emitter            binary                         khi nào tag phát
     |- gate_kernel        sigmoid_leaky_tanh             sinh X'' thế nào
     |- solver             algebraic_chain | fixed_point  giải chuỗi thế nào
     +- adaptation_kernel  model_free (MIT) | rls (stub)  vòng chậm học thế nào

   Organism (1 registry)
     +- gate_controller    threshold | key                cổng quyết định thế nào
```

Thêm một cơ chế mới = đăng ký một hàm vào registry + khai tên nó trong XML.
**Không sửa engine.** Chữ ký của mỗi loại kernel đã bị đóng băng. Một gate
gọi tên controller chưa tồn tại thì đơn giản là **không mở được** — đúng
bằng trạng thái nó sinh ra, chứ không phải một lỗi.

---

## 7. Bộ luật (invariant) — nên vẽ thành một bảng bên lề

| # | Luật | Vì sao |
|---|---|---|
| 1 | Cổng **sinh ra ở trạng thái đóng**; khai `open="true"` là lỗi parse | đóng là trạng thái ổn định; van có thể sinh ra mở thì không phải van |
| 2 | Nguồn của channel phải là **composite** | composite là đơn vị mà mô hình tự cho là thuộc về nhau |
| 3 | Đích phải là attribute **INTER_LAMINA** | ghi vào SENSOR = nguỵ tạo phép đo; ghi vào PRELIMINARY = đè lên thứ người ta tự tính |
| 4 | Ngưỡng phải có **hai biên** đúng thứ tự (trừ `identity`) | một ngưỡng sẽ rung liên tục vì nhiễu |
| 5 | Cái gì **được học** phải khai **clamp** | vòng học không cận nằm trong vòng kín = mô hình tự đi khỏi chính nó |
| 6 | Một attribute đích chỉ nhận **một** channel | hai dây ghi cùng chỗ thì không ai biết ai thắng |
| 7 | Chỉ nối hai lamina **kề nhau** (level lệch 1) | nhảy tầng là bỏ qua lớp ở giữa |
| 8 | Tối đa **4 cổng trên mỗi mặt** của một lamina (2 mặt = 8) | giới hạn độ phức tạp của màng |
| 9 | Một lamina trình ra **đúng một** composite làm mặt tiếp xúc | mặt tiếp xúc là thứ suy ra được, không phải khai hai lần |
| 10 | `<backprop>` phải **nêu tên outcome** | đường về không chở gì là một lời khai không đúng sự thật |
| 11 | Schema cũ bị **từ chối theo tên**, không diễn giải lại | mô hình sai mà parse sạch là loại sai tệ nhất |
| 12 | Mỗi phía channel phải có **ít nhất một cổng** | phía không cổng = dây ghi thẳng vào lamina kia |
| 13 | Cổng **không được nêu tên attribute** (`watch=` bị cấm) | cổng phải mù với ruột composite — cả chiều đi lẫn chiều về |
| 14 | Đường về chỉ được trỏ vào composite có **>= 2 attribute** và **có luật học** | 1 attribute thì state = chính nó, mọi bước học đúng bằng 0 -> đường về trông như chạy mà không bao giờ chạy |

---

## 8. Danh sách sơ đồ đề xuất

Ưu tiên theo thứ tự; mỗi cái nên đứng độc lập được.

**Sơ đồ 1 — Toàn cảnh hai tầng.**
Node: các file XML lamina -> UniversalTwin; file XML organism -> Organism.
Mũi tên: XML *nạp vào* runtime. Nhấn mạnh ranh giới "chuyên gia miền / lập trình viên".

**Sơ đồ 2 — Giải phẫu một Attribute.**
Vẽ X' và X'' là **hai kênh riêng** chảy vào một khối cộng, ra thành X, rồi
qua khối chuẩn hoá thành v trong [0,1]. Ghi rõ ai được ghi vào kênh nào.
Ba loại source vẽ thành ba màu, hai loại có biểu tượng "khoá" (thiêng liêng).

**Sơ đồ 3 — Composite và hai vector.**
N attribute ở giữa; **mũi tên đi ra bên phải** qua absorption vector -> một số s;
**mũi tên đi vào từ bên trái** qua distribution vector -> chia tín hiệu hiệu
chỉnh về từng attribute. Ghi chú: một vector chỉ đọc, một vector được học.

**Sơ đồ 4 — Chu trình vòng nhanh 8 bước.**
Vòng tròn khép kín, đánh số 1 đến 8, có nhánh rẽ cho dead-zone snap và cầu dao mềm.

**Sơ đồ 5 — Chi tiết gate kernel.**
Ba khối nối tiếp: sigmoid G -> nhân thành raw -> tích phân rò rỉ + tanh.
Kèm hai đồ thị nhỏ: G(d) gần 0 khi |d| < 1, và tanh bão hoà ở +/- a_max.

**Sơ đồ 6 — Một lần vượt màng (quan trọng nhất).**
Đúng theo §4.3. Bắt buộc thể hiện: composite -> absorption -> **một con số**
-> màng gửi -> *khoảng chờ có lời mời đang nằm đó* -> màng nhận -> trễ ->
đổi đơn vị -> trọng số -> EWMA -> attribute nhận. Ghi `lambda` ngay chỗ hai
fraction nhân nhau.

**Sơ đồ 7 — Thứ tự tick của Organism.**
Sơ đồ swimlane 5 làn: cảm biến / tính chuỗi / lượt cổng / vòng phản hồi /
lượt ngược. Chú thích tại sao (3) nằm giữa (2) và (4), và tại sao (5) nằm sau (4).

**Sơ đồ 8 — Đường đi và đường về trên cùng một sợi dây.**
Một channel, mũi tên xuôi mang `s`, mũi tên ngược mang `delta = polarity*lambda*E`,
và **cùng một ký hiệu lambda ở cả hai chiều** để thấy đường về không bao giờ
rộng hơn đường đi.

**Sơ đồ 9 — Hai thang thời gian.**
Trục thời gian; vòng nhanh mỗi tick, vòng chậm mỗi N tick; đường "bị snap xoá"
so với đường "sống sót".

**Sơ đồ 10 — Bản đồ registry.**
Ổ cắm và phích cắm: 6 registry của lamina + 1 của organism, mỗi cái ghi tên
kernel mặc định.

**Sơ đồ 11 — Segment và composite: hai cách cắt cùng một tập attribute.**
Một lưới attribute; **cột** = composite (gộp dọc thành state value đi ra
ngoài), **hàng** = segment (chấm điểm ngang bằng behavioural outcome).
Cho thấy một attribute có thể thuộc cả hàng lẫn cột, và hai cách chia
không lồng vào nhau.

**Sơ đồ 12 — Đường đi của một mục tiêu (segment là điểm khởi đầu).**
Chuỗi: `segment -> outcome (target, tolerance) -> deviation -> E chuẩn hoá`
rồi rẽ **hai nhánh**:
- nhánh trong nhà: `-> tag -> gate kernel -> X'' -> attribute PRELIMINARY`
- nhánh xuyên màng: `-> backprop -> delta = polarity*lambda*E -> absorption
  vector của composite bên lamina GỬI`

Đây là hình cho thấy rõ nhất vì sao segment không phải thứ trang trí.

---

## 9. Quy ước ký hiệu đề xuất

| Ý | Ký hiệu |
|---|---|
| Khai báo (XML, bất biến khi chạy) | hộp viền nét đứt |
| Trạng thái runtime | hộp viền đậm, góc bo |
| Cổng | hình van / cửa, có nhãn `open_fraction` |
| Con số trong [0,1] | mũi tên nét liền, ghi `[0,1]` |
| Con số có đơn vị gốc | mũi tên nét đậm, ghi đơn vị |
| Tín hiệu sai số | mũi tên nét đứt, màu khác |
| Giá trị "thiêng liêng" | biểu tượng khoá |
| Cái được phép học | biểu tượng bánh răng + dải clamp |

---

## 10. Những chỗ tuyệt đối đừng vẽ sai

1. **Đừng vẽ cổng đọc thẳng attribute.** Cổng chỉ nhận được đúng một gói:
   `{nhãn, state, delta, vector}`. Absorption vector **luôn đứng trước cổng**.
2. **Đừng vẽ absorption vector và distribution vector là cùng một thứ.**
   Một cái gộp đi ra và được học; một cái tán đi vào và chỉ đọc.
3. **Đừng vẽ đường về là một mũi tên gradient qua ma trận.** Nó là một số
   vô hướng đi qua **đúng những cái cổng** mà giá trị đã đi qua.
4. **Đừng vẽ trọng số channel nhân vào giá trị.** Nó nhân vào **độ lệch so
   với giả định hiện có** của bên nhận.
5. **Đừng vẽ ghép nối một chiều kiểu "gửi là xong".** Phải có trạng thái
   *waiting*: bên gửi đã mời, bên nhận chưa lấy.
6. **Đừng vẽ vòng phản hồi chạm vào cảm biến hay giá trị liên lamina.**
   Chỉ PRELIMINARY mới nhận X''.
7. **Đừng vẽ giá trị ngoài dải bị kẹp im lặng.** Hệ thống kẹp *và gắn nhãn*
   (`saturated`), hoặc *từ chối* (band) — không bao giờ lặng lẽ kéo về bình thường.
8. **Đừng vẽ vòng chậm phát ra hiệu chỉnh.** Nó chỉ chỉnh `gain` và
   `operating_point` của vòng nhanh.
9. **Đừng vẽ segment lồng trong composite (hoặc ngược lại).** Chúng là hai
   cách cắt song song của cùng một tập attribute: composite gộp *đi ra*,
   segment chấm điểm *tại chỗ*.
10. **Đừng vẽ outcome đứng một mình.** Mọi outcome đều nằm trong một segment,
    và mọi lần tra `tolerance` đều đi qua đó.
