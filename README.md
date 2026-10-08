# HRMi: Mini HRM trên Raspberry Pi

![tests](../../actions/workflows/tests.yml/badge.svg)

Hệ thống quản lý nhân sự nhỏ chạy trực tiếp trên Raspberry Pi, chấm công bằng **thẻ RFID (PN532)** và **vân tay (AS608)**. Web quản trị, cổng tự phục vụ cho nhân viên và màn hình kiosk đều chạy trên cùng một máy, không cần Internet.

Gồm: chấm công theo ca, ngày lễ và OT theo luật Việt Nam, nghỉ phép và đơn từ có duyệt, chốt bảng công hằng tháng, hồ sơ nhân sự, hợp đồng lao động, quá trình công tác, thủ tục nghỉ việc, thông báo email và **trợ lý hướng dẫn sử dụng** (chat ở góc màn hình, chạy offline). Lộ trình phát triển tiếp theo xem [ROADMAP.md](ROADMAP.md).

## Chạy nhanh

```bash
python3 -m venv env                       # nếu chưa có
env/bin/pip install -r requirements.txt
env/bin/python run.py                     # tự nạp lại khi sửa code
```

Mở `http://<ip-của-pi>:5000` và đăng nhập **admin / admin**. Hãy đổi mật khẩu ngay: bấm tên tài khoản ở góc dưới bên trái. Kiosk nằm ở `http://<ip-của-pi>:5000/kiosk` và không cần đăng nhập.

Chưa cắm phần cứng thì chạy `HRM_HARDWARE_ENABLED=0 env/bin/python run.py`, rồi dùng **Thiết bị → Mô phỏng quét** để giả lập lượt quẹt thẻ hoặc vân tay.

## Phát triển: tự nạp lại khi sửa code

`python run.py` mặc định bật chế độ tự nạp lại (`HRM_RELOAD=1`):

| Sửa gì | Cần làm gì |
|---|---|
| File `.py` (`hrm/`, `run.py`…) | Không cần làm gì. Server tự khởi động lại sau khoảng 1–2 giây (log hiện `Detected change … reloading`); sau đó bấm F5 trên trình duyệt. |
| Template HTML (`hrm/templates/`) | Chỉ cần bấm F5, template được đọc lại ngay. |
| CSS (`hrm/static/style.css`) | Chỉ cần bấm F5. |

- Werkzeug chạy **2 tiến trình**: tiến trình cha chỉ theo dõi file, tiến trình con mới phục vụ web. **Chỉ tiến trình con mở đầu đọc RFID và cảm biến vân tay**, nên hai tiến trình không tranh nhau thiết bị. Mỗi lần nạp lại, tiến trình con cũ thoát và nhả thiết bị, tiến trình mới mở lại.
- Chỉ theo dõi code của dự án; thư viện trong `env/` được bỏ qua cho nhẹ CPU.
- Khi chạy thật (systemd) chế độ này **tắt** (`HRM_RELOAD=0` trong `deploy/hrmi.service`).

## Tính năng theo vai trò

Đăng nhập xong, menu chỉ hiện những gì người đó có quyền làm.

| | Quản trị (admin) | Trưởng phòng | Nhân viên |
|---|---|---|---|
| Phạm vi | Toàn công ty | **Cả nhánh** phòng ban mình quản lý | Bản thân |
| Hồ sơ của mình (`/me`), bảng công & giải trình, tự tạo đơn nghỉ / công tác | ✓ | ✓ | ✓ |
| Tự tạo đơn trong ngày (đi muộn, về sớm, quên chấm, ra ngoài, đăng ký OT) | ✓ | ✓ | ✓ |
| Trợ lý hướng dẫn (chat) và trang Hướng dẫn, nội dung lọc theo vai trò | ✓ | ✓ | ✓ |
| Xem nhân viên, chấm công, báo cáo tháng | ✓ | ✓ (nhánh) | |
| Thêm / xoá chấm công thủ công | ✓ | ✓ (nhánh) | |
| Duyệt đơn nghỉ / công tác, đơn trong ngày | ✓ | ✓ (nhánh) | |
| Duyệt, trả lại, chốt bảng công | ✓ | ✓ (nhánh) | |
| Sửa hồ sơ nhân viên | ✓ | tắt (bật được) | |
| Xem & sửa thông tin nhạy cảm (CCCD, tài khoản ngân hàng, lương, hợp đồng, người phụ thuộc, giấy tờ) | ✓ | tắt (bật được) | chỉ xem của mình |
| Tổng quan, phòng ban, phân quyền, **cài đặt** (ngày lễ & OT, giờ làm & ca, nghỉ phép, email, công ty), thiết bị, thêm/xoá nhân viên, đăng ký thẻ/vân tay, tài khoản | ✓ | | |
| Hợp đồng lao động, quyết định nhân sự, thủ tục nghỉ việc / nhận lại | ✓ | | |

Quyền của Trưởng phòng và Nhân viên bật/tắt được ở trang **Phân quyền**. Không ai có quyền nhóm với chính mình, nên không ai tự duyệt được cho mình.

## Tính năng

### Nhân viên & tổ chức
- **Danh sách nhân viên:**
  - 2 chế độ xem: danh sách hoặc biểu tượng lớn.
  - **Tìm kiếm tức thì** khi gõ, không phân biệt dấu ("nguyen" khớp "Nguyễn").
  - Lọc theo phòng ban hoặc trạng thái.
  - Phòng ban hiện bằng nhãn màu.
  - Chấm trạng thái trên ảnh: 🟢 đang ở công ty, ⚪ đã checkout, 🔵 đi công tác, 🟣 nghỉ phép, 🔴 chưa đến (theo quy ước màu của Microsoft Teams).
- **Hồ sơ nhân viên:**
  - ảnh đại diện (tự cắt vuông, thu nhỏ còn 512px), thông tin cá nhân, công việc, định mức phép năm;
  - lịch công tháng dạng heatmap, vòng hiển thị số phép còn lại;
  - đăng ký và gỡ thẻ RFID / vân tay, tài khoản đăng nhập.
- **Sơ đồ tổ chức quanh nhân viên** (trong hồ sơ):
  - chuỗi cấp trên tới cấp cao nhất, cấp trên trực tiếp được đánh dấu;
  - các cấp dưới trực thuộc;
  - ô của **chính người đang xem** được làm nổi bật (nhãn "BẠN", đường nối lên tới gốc được tô màu).
- **Hồ sơ mở rộng:** quê quán, hôn nhân, trình độ, liên hệ khẩn cấp; phần **nhạy cảm** (CCCD, mã số thuế, sổ BHXH, tài khoản ngân hàng) chỉ hiện với admin, chính nhân viên và trưởng phòng được bật quyền riêng. Người sửa hồ sơ không có quyền này lưu form cũng không làm mất các trường đó.
- **Người phụ thuộc** (cho giảm trừ gia cảnh): quan hệ, ngày sinh, MST, thời gian giảm trừ.
- **Giấy tờ đính kèm:** scan CCCD, bằng cấp, giấy khám sức khoẻ, hợp đồng đã ký… (PDF, ảnh, Word, Excel ≤ 8 MB), lưu trong `instance/documents/<mã nhân viên>/` với tên file ngẫu nhiên; tải xuống phải qua kiểm tra quyền.
- **Phòng ban:** có phòng ban cấp trên và trưởng phòng; 2 chế độ xem: **sơ đồ cây** hoặc **danh sách** sửa trực tiếp trên bảng.
- **Tài khoản:**
  - tên đăng nhập là mã NV viết thường (ví dụ `nv004`);
  - admin tạo, đặt lại mật khẩu (sinh ngẫu nhiên), xoá, hoặc **cấp quyền quản trị** cho tài khoản nhân viên;
  - nhân viên đã nghỉ việc không đăng nhập được.

### Giờ làm việc & ca (Cài đặt › Giờ làm & ca)
- **Giờ làm mặc định** sửa trên web: giờ vào / ra, nghỉ trưa, phút ân hạn đi muộn, các ngày làm việc trong tuần. Biến môi trường `HRM_WORK_*` chỉ là giá trị ban đầu khi chưa lưu trên web.
- **Ca làm việc** (ca sáng, ca chiều, hành chính có thứ 7...): mỗi ca có giờ làm, nghỉ trưa, ân hạn, ngày làm việc riêng.
- Gán ca cho **phòng ban** (áp dụng cho cả các phòng con chưa có ca riêng) ở trang Phòng ban, hoặc cho **từng nhân viên** ở trang sửa hồ sơ. Thứ tự áp dụng: ca của nhân viên → ca của phòng ban / phòng cấp trên → giờ mặc định.
- Đi muộn, về sớm, giờ công, OT, công chuẩn, ngày nghỉ hằng tuần và số ngày của đơn nghỉ đều tính theo ca của từng người. Hồ sơ nhân viên ghi rõ đang dùng ca nào.
- Chưa hỗ trợ ca qua đêm (giờ ra phải sau giờ vào trong cùng ngày) và lịch xoay ca theo ngày.

### Chấm công
- Quẹt thẻ hoặc đặt ngón tay: lượt đầu trong ngày là **giờ vào**, lượt cuối là **giờ ra**. Lượt quét lặp lại trong 60 giây bị bỏ qua.
- Tự tính phút đi muộn (có thời gian ân hạn), về sớm và giờ công trong ca (đã trừ nghỉ trưa).
- Có chấm công thủ công khi nhân viên quên thẻ. Báo cáo tháng xuất được CSV (mở được bằng Excel).

### Ngày lễ & làm thêm giờ (Cài đặt › Ngày lễ & OT, admin)
- **Lịch ngày lễ theo năm**, 3 loại ngày:
  - *Nghỉ lễ*: không tính vắng, được 1 công hưởng lương; đi làm thì tính OT ngày lễ.
  - *Nghỉ hoán đổi*: ngày làm việc được đổi thành ngày nghỉ.
  - *Làm bù*: thứ 7 / CN phải đi làm, tính như ngày làm việc (có đi muộn, vắng).
- Nút **Nạp ngày lễ theo luật** (Điều 112 BLLĐ 2019): Tết Dương lịch, Tết Âm lịch (cuối năm + mùng 1–4), Giỗ Tổ 10/3 âm lịch, 30/4, 1/5, Quốc khánh 1–2/9, kèm **ngày nghỉ bù** khi lễ trùng ngày nghỉ hằng tuần. Ngày âm lịch được tính sẵn trong máy (`hrm/calendar_vn.py`), không cần Internet. Lịch nghỉ Tết do Thủ tướng quyết định mỗi năm, nên sau khi nạp hãy kiểm tra lại, thêm ngày hoán đổi / làm bù nếu có.
- Đơn nghỉ không trừ phép vào ngày lễ; thêm hay xoá ngày lễ thì số ngày của các đơn liên quan được tính lại. Tháng đã chốt công thì không sửa lịch được.
- **Làm thêm giờ (OT)** được chia 3 loại, mỗi loại có hệ số riêng (mặc định theo luật):

  | Loại | Cách tính | Hệ số |
  |---|---|---|
  | Ngày thường | Phần sau giờ tan ca, khi ở lại ít nhất 30 phút | 150% |
  | Ngày nghỉ hằng tuần | Toàn bộ thời gian làm (trừ nghỉ trưa) | 200% |
  | Ngày lễ | Toàn bộ thời gian làm (trừ nghỉ trưa) | 300% |

  Giờ làm trong khoảng 22:00–06:00 được cộng thêm 30%. **Giờ OT quy đổi** = giờ × hệ số + giờ đêm × phần cộng thêm, dùng để tính lương OT.
- **Đăng ký OT:** mặc định OT ngày thường phải có đơn đăng ký được duyệt, chỉ phần nằm trong khung giờ đăng ký mới được tính. Phần làm thêm chưa có đơn hiện là "OT chưa duyệt" ở báo cáo và bảng công. Có thể chọn không cần đăng ký, hoặc bắt đăng ký cả OT ngày nghỉ / lễ.
- **Trần OT** tháng (mặc định 40 giờ) và năm (200 giờ): báo cáo tháng gắn nhãn đỏ cho người vượt trần.
- Mọi hệ số và ngưỡng sửa được trên trang, có kiểm tra giá trị hợp lệ.

### Đơn trong ngày
| Loại đơn | Khi được duyệt |
|---|---|
| Đi muộn / Về sớm | Ngày đó không tính phút muộn / về sớm. Có thể giới hạn số đơn mỗi tháng. |
| Quên chấm công | Tự thêm lượt chấm thủ công theo giờ vào / ra trong đơn; huỷ đơn thì gỡ lại các lượt đó. |
| Ra ngoài | Chỉ ghi nhận, không ảnh hưởng số liệu công. |
| Đăng ký OT | Giờ làm thêm trong khung giờ đăng ký được tính OT. |

Nhân viên tự tạo đơn, trưởng phòng (cả nhánh) hoặc admin duyệt, giống đơn nghỉ. Đơn rơi vào tháng đã chốt công thì không tạo, duyệt hay huỷ được. Ở "Bảng công của tôi", ngày đi muộn / thiếu giờ ra có nút tạo đơn nhanh.
- **Kiosk:** đồng hồ lớn, vòng quét đổi màu theo kết quả (đúng giờ, đi muộn, OT, không nhận diện) kèm lời chào.

### Nghỉ phép & công tác
- Các loại đơn: phép năm, nghỉ ốm, không lương, **công tác**, kết hôn, con kết hôn, tang chế, thai sản, khác; có thể nghỉ nửa ngày. Đơn được kéo dài qua năm, mỗi phần trừ vào phép của năm đó.
- Chỉ tính ngày làm việc (theo ca của nhân viên, bỏ ngày lễ); kiểm tra trùng đơn và số phép còn lại.
- **Phép năm nâng cao** (Cài đặt › Nghỉ phép):
  - **Theo tỉ lệ** cho người vào làm trong năm: định mức × số tháng ÷ 12, làm tròn theo NĐ 145/2020 (vào làm sau ngày 15 thì tính từ tháng sau).
  - **Thâm niên**: cứ đủ 5 năm làm việc (tính tới 1/1, theo ngày vào làm) được cộng 1 ngày.
  - **Cấp đủ đầu năm** hoặc **cộng dồn mỗi tháng** 1/12 định mức (chỉ dùng được phần đã cộng).
  - **Chuyển phép tồn** sang năm sau, tối đa N ngày, phải dùng trước một ngày hạn (mặc định 31/3); nghỉ trong năm dùng phần chuyển sang trước, phần còn lại hết hạn. Chỉ chuyển khi năm trước nhân viên đã có dữ liệu chấm công.
  - **Điều chỉnh thủ công**: admin cộng / trừ ngày phép kèm lý do ở hồ sơ nhân viên (thưởng phép, chuyển số dư từ hệ thống cũ...).
  - Hồ sơ nhân viên hiện chi tiết: định mức, thâm niên, phần theo tỉ lệ / cộng dồn, phép chuyển sang và hạn, điều chỉnh, đã nghỉ, chờ duyệt.
- **Các loại nghỉ theo luật** (Điều 115 BLLĐ 2019): mỗi loại cấu hình được có **hưởng lương** hay không và **số ngày tối đa mỗi đơn**. Mặc định kết hôn 3 ngày, con kết hôn 1 ngày, tang 3 ngày hưởng lương; nghỉ ốm, thai sản do BHXH chi trả nên không tính vào công tính lương.
- Ngày công tác được tính là có làm và không trừ phép năm.
- Nhân viên tự tạo đơn; trưởng phòng (cả nhánh) hoặc admin duyệt. Nhân viên tự huỷ được đơn của mình khi đơn còn chờ duyệt.

### Thông báo email (Cài đặt › Email)
- Cấu hình SMTP trên web (Gmail, Microsoft 365, máy chủ thư nội bộ...), có nút **Gửi thử**.
- Gửi email tự động khi: có đơn nghỉ / đơn trong ngày mới (tới cấp trên trực tiếp), đơn được duyệt / từ chối (tới nhân viên), bảng công được gửi xác nhận, gửi duyệt, bị trả lại, đã chốt. Bật / tắt riêng từng loại.
- Không có cấp trên (hoặc cấp trên chưa có email) thì gửi tới **email quản trị** và các tài khoản admin có email.
- Thư nằm trong **hàng đợi** (`email_outbox`), luồng nền gửi dần nên web không phải chờ; mất mạng thì tự thử lại (tối đa 5 lần, giãn dần), sau đó có nút "Gửi lại thư lỗi". Trang cấu hình hiện 30 thư gần nhất và lỗi nếu có.
- Nhân viên cần có **email trong hồ sơ** để nhận thư; trang cấu hình đếm số người còn thiếu email.
- Mật khẩu SMTP lưu trong CSDL trên máy, hoặc đặt bằng biến môi trường `HRM_SMTP_PASSWORD` (được ưu tiên).

### Xác nhận & chốt công (tiền đề tính lương)

```
Chưa gửi ─(admin gửi)→ Chờ NV xác nhận ─(NV giải trình, gửi duyệt)→ Chờ cấp trên duyệt ─(chốt)→ Đã chốt 🔒
                             ↑                                          │
                             └──────────── Bị trả lại ←─(trả lại)───────┘
```

1. **Admin** gửi bảng công tháng (đã kết thúc) cho từng người hoặc cả công ty.
2. **Nhân viên** mở "Bảng công của tôi". Các ngày có vấn đề (đi muộn, thiếu giờ ra, vắng) được tô vàng. Nhân viên **giải trình** từng ngày (lý do, có thể kèm giờ vào/ra đúng), rồi bấm "Xác nhận & gửi duyệt".
3. **Cấp trên** (trưởng phòng; trưởng phòng do cấp trên của nhánh duyệt; không có ai thì admin duyệt):
   - **chấp nhận** giải trình (nếu có giờ đề nghị, hệ thống tự thêm chấm công) hoặc **từ chối** kèm phản hồi;
   - sau đó **chốt công** hoặc **trả lại** cho nhân viên.
4. **Đã chốt:** số liệu được lưu thành bản chụp cố định, kèm người chốt và thời điểm chốt. Tháng đó bị **khoá**: không thêm hay xoá lượt chấm, không tạo, duyệt hay huỷ đơn rơi vào tháng đó, cho tới khi "Mở lại".

**Công tính lương** = đi làm + công tác + nghỉ có lương (phép năm, khác) + ngày lễ; mỗi ngày tối đa 1 công (đi làm ngày lễ vẫn được 1 công lễ, giờ làm tính OT 300%). Nghỉ ốm / không lương và OT tính riêng. Bản chốt lưu cả giờ OT theo từng loại và giờ OT quy đổi. Admin chốt hàng loạt và xuất CSV ở trang **Chốt công**.

### Hợp đồng & quá trình công tác (admin)
- **Hợp đồng lao động:** thử việc, xác định thời hạn, không xác định thời hạn, thời vụ; số HĐ tự đánh (`01/2026/HĐLĐ`, `HĐTV` cho thử việc), lương, lương đóng BHXH, phụ cấp (mỗi dòng "tên: số tiền"), bản đã ký đính kèm.
  - Kiểm tra theo BLLĐ 2019: xác định thời hạn tối đa 36 tháng, thử việc tối đa 180 ngày, hai hợp đồng không được chồng thời gian; cảnh báo khi ký xác định thời hạn lần thứ 3.
  - Trạng thái **tính theo ngày** khi xem: chưa hiệu lực, đang hiệu lực, sắp hết hạn (≤ 30 ngày), hết hạn, đã chấm dứt (chấm dứt trước hạn được ghi ngày).
  - Ký hợp đồng mới tự điền nối tiếp hợp đồng trước (ngày bắt đầu, lương, phụ cấp); đổi mức lương được tự ghi vào quá trình công tác.
  - **In hợp đồng** (A4, in hoặc lưu PDF từ trình duyệt) với thông tin công ty ở **Cài đặt › Công ty**, giờ làm theo ca, lương **bằng chữ**.
  - Trang **Nhân sự › Hợp đồng** lọc theo trạng thái, nút "Ký tiếp" cho hợp đồng sắp / đã hết hạn.
- **Quá trình công tác:** vào làm, điều chuyển, đổi chức danh, thăng chức, thay đổi lương, nghỉ việc, nhận lại; kèm ngày hiệu lực, số quyết định, người quyết định. Sửa phòng ban / chức danh trong hồ sơ cũng tự ghi lại. Quyết định điều chuyển có hiệu lực từ hôm nay trở về trước được áp dụng luôn vào hồ sơ.
- **Thủ tục nghỉ việc** (checklist): ngày nghỉ, lý do; thu hồi thẻ RFID, xoá vân tay trên AS608, chấm dứt hợp đồng, huỷ đơn chờ duyệt, khoá hoặc xoá tài khoản; bỏ vị trí trưởng phòng; đánh dấu các việc bàn giao. Sau ngày nghỉ việc không tính vắng, không hưởng ngày lễ; phép năm tính theo tỉ lệ tới tháng nghỉ (nghỉ trước ngày 15 thì không tính tháng đó). **Nhận lại làm** với ngày vào mới.
- **Nhắc việc trên Tổng quan:** hợp đồng / thử việc sắp hết hạn chưa ký tiếp, hợp đồng đã hết hạn, nhân viên chưa có hợp đồng, sinh nhật trong tháng. Email nhắc quản trị mỗi ngày một lần (mỗi hợp đồng nhắc một lần), bật/tắt ở trang Email.

### Trợ lý HRMi & hướng dẫn sử dụng
- **Nút chat ở góc phải dưới** mọi trang (phím tắt `?`, `Esc` để đóng): hỏi bằng tiếng Việt, có dấu hay không dấu đều được ("xin nghi nua ngay", "quên quẹt thẻ lúc về", "mở trang hợp đồng"). Trợ lý trả lời ngắn theo từng bước, kèm **nút mở đúng trang** và gợi ý câu hỏi theo trang đang mở.
- Chạy **offline hoàn toàn**, không cần Internet hay mô hình AI: tra cứu kho hướng dẫn `hrm/help/*.md` bằng tìm kiếm không dấu (BM25, khớp cả cụm hai âm tiết như "chấm công", "nghỉ phép").
- **Theo vai trò và quyền:** chỉ đưa link tới trang người hỏi vào được; hỏi việc của vai trò khác (nhân viên hỏi "thêm nhân viên") thì trợ lý nói rõ việc đó do ai làm.
- Hội thoại giữ trong tab trình duyệt (sang trang khác vẫn còn, đóng tab thì mất), không lưu trên server.
- Trang **Hướng dẫn** (`/help`, biểu tượng ? ở chân thanh bên): toàn bộ hướng dẫn theo nhóm, có ô lọc không dấu.
- Thêm / sửa hướng dẫn: viết file `.md` trong `hrm/help/` (khai báo `title`, `group`, `roles`, `pages`, `keywords`, `ask` ở đầu file; đoạn trước `## ` đầu tiên là câu trả lời ngắn trong khung chat; `[[main.endpoint]]` chèn liên kết trang). Không cần khởi động lại; test kiểm tra mọi trang được nhắc tới đều tồn tại.
- Kế hoạch tầng AI (Claude API) xem [AI_ASSISTANT.md](AI_ASSISTANT.md).

### Tổng quan (admin)
- Các chỉ số trong ngày: có mặt, đi muộn, nghỉ phép, công tác, vắng, đơn chờ duyệt.
- Biểu đồ **2 tuần** (tuần trước / tuần này, T2→CN, nét đứt chia tuần), có tooltip khi rê chuột và bảng số liệu đi kèm.
- Tỉ lệ có mặt hôm nay, xếp hạng đi muộn trong tháng, lượt chấm gần nhất, đơn chờ duyệt.
- Nhắc việc nhân sự: hợp đồng sắp / đã hết hạn, nhân viên chưa có hợp đồng, sinh nhật trong tháng.

## Giao diện

- **Menu gọn theo module.** Thanh bên chỉ có vài mục lớn, bấm vào mở trang đầu tiên; các trang con hiện thành hàng tab phía trên nội dung. Số việc cần xử lý được cộng dồn lên mục cha.

  | Mục | Trang con | Ai thấy |
  |---|---|---|
  | Của tôi | Bảng công của tôi · Hồ sơ của tôi | Nhân viên, trưởng phòng |
  | Tổng quan | — | Admin |
  | Đơn từ | Nghỉ phép · công tác · Đơn trong ngày | Mọi người (theo quyền) |
  | Nhân sự | Nhân viên · Hợp đồng · Phòng ban · Phân quyền | Admin; trưởng phòng thấy Nhân viên |
  | Chấm công | Theo ngày · Báo cáo tháng · Chốt công (Duyệt bảng công) | Admin, trưởng phòng |
  | Cài đặt | Ngày lễ & OT · Giờ làm & ca · Nghỉ phép · Email · Công ty · Thiết bị | Admin |

  Nút mở **Kiosk** nằm ở chân thanh bên, cạnh nút sáng/tối. Thêm trang mới: khai báo vào `MODULES` trong `hrm/navigation.py`.
- **Giao diện sáng mặc định.** Nút ☾/☀ ở chân thanh bên trái chuyển sáng/tối, lựa chọn được trình duyệt ghi nhớ. Bấm tên tài khoản bên cạnh để mở hồ sơ của mình.
- **Màu trạng thái** dùng thống nhất ở mọi nơi: xanh lá là đúng giờ, vàng là đi muộn, xanh dương là công tác, tím là nghỉ phép, xanh bạc hà là OT, đỏ là vắng. Bộ màu đã được kiểm tra bằng công cụ đo khoảng cách màu, có mô phỏng người mù màu. Màu luôn đi kèm nhãn chữ.
- **Trợ lý & Hướng dẫn:** nút chat tròn gradient cyan ở góc phải dưới, biểu tượng ? ở chân thanh bên mở trang Hướng dẫn.
- **Viền cyan theo màu nhấn:** thẻ, ô số liệu, bộ lọc dạng nút và đường kẻ bảng dùng viền cyan nhạt (biến `--border-accent` trong `style.css`, mỗi theme sáng/tối một giá trị); ô số liệu bấm được sáng viền khi rê chuột. Thẻ chính (đầu hồ sơ, các form hồ sơ / hợp đồng / nghỉ việc / công ty, nhắc việc trên Tổng quan) có thêm vạch gradient cyan → tím ở mép trên (class `card accent`); biểu mẫu mở ra trong thẻ được đóng khung cyan nét đứt.
- **Hoạt động offline:** không dùng CDN, icon là SVG nội tuyến.

## Kiến trúc

```
                ┌──────────────────── run.py ───────────────────────────────────┐
 Trình duyệt ──►│  Flask web (views*.py) ─► permissions.py ─► services.py ─► SQLite│
 (admin, NV,    │        ▲                   timesheet.py         instance/hrm.db│
  kiosk)        │        │ đăng ký / trạng thái      ▲                           │
                │  HardwareManager (luồng nền) ──────┘ ghi lượt chấm công        │
                │     ├── PN532  (I2C)   hrm/hardware/rfid.py                    │
                │     └── AS608  (UART)  hrm/hardware/fingerprint.py             │
                └────────────────────────────────────────────────────────────────┘
```

- **Phần cứng:** một luồng duy nhất sở hữu cả hai thiết bị và luân phiên hỏi từng cái. Khi đăng ký thẻ/vân tay, luồng chuyển sang chế độ đăng ký; trang hồ sơ hiện từng bước. Thiết bị chưa cắm thì web vẫn chạy, trang **Thiết bị** ghi rõ lý do. Mẫu vân tay lưu trong bộ nhớ AS608; CSDL chỉ lưu số vị trí (`fingerprint_id`).
- **Phân quyền:** mỗi trang kiểm tra quyền **trên đúng nhân viên** đang thao tác (`permissions.can(quyền, nhân_viên)`). Danh sách và báo cáo tự lọc theo phạm vi.
- **Số liệu công không lưu sẵn** mà được tính từ `attendance_logs` mỗi khi xem, nên đổi giờ làm việc thì báo cáo cũ cũng được tính lại. Riêng bảng công đã chốt dùng bản chụp cố định.
- **Nâng cấp CSDL tự động:** CSDL cũ được tự thêm bảng/cột khi khởi động, dữ liệu giữ nguyên.

## Cấu trúc thư mục

```
HRMi/
├── run.py                     # Điểm khởi động (tự nạp lại khi sửa code)
├── seed.py                    # Tạo dữ liệu mô phỏng
├── demo_avatars.py            # Vẽ avatar hoạt hình con vật cho dữ liệu mô phỏng
├── requirements.txt
├── LICENSE                    # GPL-3.0
├── hrm/
│   ├── __init__.py            # create_app(), tạo admin lần đầu, filter template
│   ├── config.py              # Cấu hình (ghi đè bằng biến môi trường HRM_*)
│   ├── db.py                  # Lược đồ SQLite + nâng cấp tự động
│   ├── services.py            # Nghiệp vụ chấm công, OT, nghỉ phép, báo cáo, khoá tháng
│   ├── timesheet.py           # Quy trình bảng công, cấp trên, sơ đồ quanh nhân viên
│   ├── workrules.py           # Giờ làm & ca, lịch làm việc (ngày lễ, hoán đổi, làm bù), quy định OT, phép
│   ├── notify.py              # Thông báo email: cấu hình SMTP, hàng đợi, luồng gửi nền
│   ├── calendar_vn.py         # Âm lịch Việt Nam, ngày lễ gợi ý theo luật
│   ├── day_requests.py        # Đơn trong ngày: muộn, sớm, quên chấm, ra ngoài, đăng ký OT
│   ├── permissions.py         # Cây phân quyền theo phòng ban, ma trận quyền
│   ├── photos.py              # Xử lý ảnh nhân viên
│   ├── profiles.py            # Hợp đồng, quá trình công tác, người phụ thuộc, giấy tờ, nghỉ việc
│   ├── views.py               # Trang web chính + API
│   ├── views_timesheet.py     # Bảng công, tài khoản nhân viên, trang phân quyền
│   ├── navigation.py          # Menu: gom trang thành module, tab trang con theo quyền
│   ├── views_rules.py         # Trang cài đặt (lễ & OT, giờ làm & ca, phép, email), đơn trong ngày
│   ├── views_profile.py       # Hợp đồng, quyết định, người phụ thuộc, giấy tờ, nghỉ việc, thông tin công ty
│   ├── views_assistant.py     # Trợ lý (API /api/assistant), trang Hướng dẫn /help
│   ├── assistant/             # Trợ lý offline: search.py (tìm không dấu, BM25), knowledge.py (kho hướng dẫn, trang theo quyền)
│   ├── help/                  # Kho hướng dẫn sử dụng, mỗi chủ đề một file .md
│   ├── hardware/              # manager.py (luồng nền), rfid.py, fingerprint.py
│   ├── templates/             # Giao diện (Jinja2)
│   └── static/style.css
├── tests/test_hrm.py          # Test nghiệp vụ, quy trình, phân quyền, phần cứng giả, web
├── tests/test_rules.py        # Test âm lịch, ngày lễ, OT, đơn trong ngày
├── tests/test_phase2.py       # Test giờ làm & ca, phép nâng cao, thông báo email
├── tests/test_profiles.py     # Test hợp đồng, quá trình công tác, nghỉ việc, giấy tờ, quyền nhạy cảm
├── tests/test_assistant.py    # Test trợ lý: tìm kiếm, bộ câu hỏi mẫu theo vai trò, quyền, kho hướng dẫn
├── deploy/hrmi.service       # Chạy tự động bằng systemd
├── .github/workflows/tests.yml # CI: chạy test trên GitHub mỗi lần push / PR
└── instance/                  # Tạo khi chạy: hrm.db, secret_key, photos/, documents/ (không commit)
```

## Dữ liệu

| Bảng | Nội dung |
|---|---|
| `employees` | Hồ sơ nhân viên, `rfid_uid`, `fingerprint_id` (đều duy nhất), `photo`; hồ sơ mở rộng (CCCD, MST, BHXH, ngân hàng, liên hệ khẩn cấp…), `termination_date` / `termination_reason` khi nghỉ việc |
| `contracts` | Hợp đồng lao động: số, loại, ngày ký / bắt đầu / kết thúc, chức danh, lương, lương đóng BH, phụ cấp (JSON), bản đã ký (`document_id`), chấm dứt sớm (`terminated_on`), lần nhắc email |
| `employment_history` | Quá trình công tác: loại, ngày hiệu lực, giá trị cũ → mới, số quyết định, người quyết định, ghi chú |
| `dependents` | Người phụ thuộc: họ tên, quan hệ, ngày sinh, CCCD, MST, thời gian giảm trừ |
| `documents` | Giấy tờ đính kèm: loại, tên, tên file gốc, tên file lưu, dung lượng, người tải lên |
| `departments` | Phòng ban, `parent_id` (cấp trên), `manager_id` (trưởng phòng) |
| `attendance_logs` | Từng lượt quét: nhân viên, thời điểm, phương thức (`rfid` / `fingerprint` / `manual`), ghi chú |
| `leave_requests` | Đơn nghỉ / công tác: loại (`annual`, `sick`, `unpaid`, `business`, `other`), khoảng ngày, nửa ngày, trạng thái duyệt |
| `timesheets` | Bảng công tháng: trạng thái quy trình, ghi chú NV / cấp trên, bản chụp số liệu khi chốt (JSON), người chốt |
| `timesheet_explanations` | Giải trình theo ngày: lý do, giờ vào/ra đề nghị, trạng thái xử lý, phản hồi |
| `shifts` | Ca làm việc: tên, giờ vào / ra, nghỉ trưa, phút ân hạn, ngày làm việc trong tuần. `departments.shift_id`, `employees.shift_id` trỏ tới ca được gán |
| `leave_adjustments` | Điều chỉnh phép năm thủ công: nhân viên, năm, số ngày (+/−), lý do, người điều chỉnh |
| `email_outbox` | Hàng đợi email: người nhận, tiêu đề, nội dung, sự kiện, trạng thái gửi, số lần thử, lỗi |
| `holidays` | Lịch làm việc: ngày, tên, loại (`holiday` nghỉ lễ / `off` nghỉ hoán đổi / `makeup` làm bù) |
| `attendance_requests` | Đơn trong ngày: loại (`late`, `early`, `forgot`, `out`, `overtime`), ngày, khung giờ, trạng thái duyệt, người duyệt |
| `users` | Tài khoản: `role` = `admin` / `employee`, gắn với `employee_id` |
| `settings` | Cấu hình key/value: ma trận quyền `perm.<vai trò>.<quyền>`, quy định OT / phép `rule.<tên>`, giờ làm mặc định `sched.<KHOÁ>`, email `mail.<tên>`, thông tin công ty `company.<tên>` |

## Đấu nối phần cứng

**PN532** (gạt công tắc trên module sang chế độ **I2C**):

| PN532 | Raspberry Pi |
|---|---|
| VCC | 3.3V (chân 1) |
| GND | GND (chân 6) |
| SDA | GPIO2 / SDA (chân 3) |
| SCL | GPIO3 / SCL (chân 5) |

**AS608**:

| AS608 | Raspberry Pi |
|---|---|
| VCC (đỏ) | 3.3V (chân 17). Xem nhãn module, một số loại cần 5V |
| GND (đen) | GND (chân 9) |
| TX | GPIO15 / RXD (chân 10) |
| RX | GPIO14 / TXD (chân 8) |

**Bật I2C và UART:**

```bash
sudo raspi-config
#   Interface Options → I2C → Yes
#   Interface Options → Serial Port → login shell: No, serial hardware: Yes
```

Trên Pi 4, nên dành UART chính (PL011) cho cảm biến. Thêm vào `/boot/firmware/config.txt`:

```
enable_uart=1
dtoverlay=disable-bt
```

Khởi động lại máy rồi kiểm tra: `ls -l /dev/serial0` (phải tồn tại) và `i2cdetect -y 1` (PN532 hiện ở địa chỉ `0x24`).

## Chạy thật bằng systemd

```bash
sudo cp deploy/hrmi.service /etc/systemd/system/
sudo systemctl enable --now hrmi
journalctl -u hrmi -f   # xem log
```

File service đặt `HRM_RELOAD=0` (không tự nạp lại). Sau khi cập nhật code hoặc cắm thêm thiết bị, chạy `sudo systemctl restart hrmi`.

## Quy trình sử dụng

1. **Phòng ban:** tạo phòng ban, chọn phòng cấp trên và trưởng phòng. Đây cũng chính là cây phân quyền.
2. **Cài đặt:** đặt giờ làm mặc định và tạo ca (nếu có nhiều giờ làm); nạp ngày lễ của năm, đối chiếu lịch nghỉ Tết chính phủ công bố; chỉnh hệ số OT, quy định phép; cấu hình email (nhập email trong hồ sơ nhân viên để họ nhận thông báo); điền thông tin công ty để in hợp đồng.
3. **Nhân viên → Thêm:** điền hồ sơ, tải ảnh. Trong hồ sơ: **Quét** thẻ / **Đăng ký** vân tay (đặt ngón tay 2 lần), **Tạo tài khoản** đăng nhập, **Hợp đồng mới** (điền **Cài đặt › Công ty** trước để in hợp đồng), tải giấy tờ.
4. Nhân viên quẹt thẻ hoặc đặt ngón tay mỗi khi đến và về; xem kết quả trên kiosk.
5. Nhân viên tự tạo **đơn nghỉ / công tác** và **đơn trong ngày** (đi muộn, quên chấm, đăng ký OT…); trưởng phòng hoặc admin duyệt.
6. Cuối tháng: **Chốt công → Gửi bảng công** → nhân viên giải trình và gửi duyệt → trưởng phòng duyệt và chốt → admin **xuất CSV** chuyển sang tính lương.
7. **Phân quyền:** điều chỉnh quyền của Trưởng phòng / Nhân viên nếu cần.
8. Không nhớ thao tác: bấm nút chat ở góc phải dưới (hoặc phím `?`) để hỏi trợ lý, hoặc xem trang **Hướng dẫn**.
9. Khi nhân viên nghỉ: hồ sơ → **Làm thủ tục nghỉ việc** vào ngày làm việc cuối; theo dõi hợp đồng sắp hết hạn ở Tổng quan hoặc **Nhân sự › Hợp đồng**.

## Dữ liệu mô phỏng

```bash
env/bin/python seed.py                   # chỉ chạy khi CSDL chưa có nhân viên
env/bin/python seed.py --reset           # XOÁ nhân viên / chấm công / nghỉ phép rồi tạo lại
env/bin/python seed.py --days 90         # số ngày lịch sử (mặc định 60)
env/bin/python seed.py --no-photos       # không tạo avatar
env/bin/python seed.py --add-ot          # chỉ THÊM lượt OT thứ 7, CN vào CSDL đang có
env/bin/python seed.py --demo-workflow   # chỉ THÊM tài khoản NV + mô phỏng quy trình bảng công tháng trước
env/bin/python seed.py --add-contracts   # chỉ THÊM hợp đồng mẫu cho người chưa có hợp đồng
```

Script tạo:
- 6 phòng ban có cấp bậc và trưởng phòng;
- 20 nhân viên, mỗi người một avatar hoạt hình con vật (vẽ bằng Pillow; chạy `python demo_avatars.py` để xem trước);
- khoảng 1.600 lượt chấm công 60 ngày (đi muộn, vắng, quên quét ra, OT cuối tuần);
- khoảng 30 đơn nghỉ / công tác ở đủ các trạng thái;
- tài khoản nhân viên với mật khẩu demo **`123456`**;
- bảng công tháng trước ở đủ các bước của quy trình;
- chuỗi hợp đồng thử việc → 12 tháng → 24 tháng → không thời hạn cho mỗi người, có người sắp hết hạn, một người chưa có hợp đồng, một người đã nghỉ việc.

Kết quả cố định theo `--seed`, nên mỗi lần chạy đều ra cùng một bộ dữ liệu. Các tuỳ chọn `--add-ot`, `--demo-workflow` và `--add-contracts` **chỉ thêm**, bỏ qua người đã có dữ liệu.

> Trước khi dùng thật, hãy xoá `instance/hrm.db` (và `instance/photos/`, `instance/documents/`) để bắt đầu với CSDL trống; tài khoản admin được tạo lại ở lần chạy sau. Mật khẩu `123456` chỉ để demo: hãy dùng "Đặt lại MK" trong hồ sơ để sinh mật khẩu ngẫu nhiên.

## Cấu hình

Biến môi trường (trong file service: thêm dòng `Environment=...`):

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `HRM_RELOAD` | `1` | Tự nạp lại khi sửa code; đặt `0` khi chạy thật |
| `HRM_WORK_START` / `HRM_WORK_END` | `08:00` / `17:00` | Giờ bắt đầu và kết thúc ca (giá trị ban đầu; sửa trên web ở Cài đặt › Giờ làm & ca thì web được ưu tiên, áp dụng cho cả 4 biến dưới) |
| `HRM_LUNCH_START` / `HRM_LUNCH_END` | `12:00` / `13:00` | Giờ nghỉ trưa (không tính vào giờ công) |
| `HRM_LATE_GRACE_MINUTES` | `5` | Số phút đến muộn vẫn chưa tính là đi muộn |
| `HRM_WORK_DAYS` | `0,1,2,3,4` | Ngày làm việc (0 = thứ Hai); ngày khác có chấm công được tính là OT |
| `HRM_SCAN_COOLDOWN_SECONDS` | `60` | Bỏ qua các lần quét lặp lại trong khoảng này |
| `HRM_DEFAULT_ANNUAL_LEAVE_DAYS` | `12` | Số ngày phép năm mặc định cho nhân viên mới |
| `HRM_HARDWARE_ENABLED` | `1` | `0` để tắt toàn bộ phần cứng |
| `HRM_RFID_ENABLED` / `HRM_FINGERPRINT_ENABLED` | `1` | Bật hoặc tắt từng thiết bị |
| `HRM_FINGERPRINT_PORT` / `HRM_FINGERPRINT_BAUDRATE` | `/dev/serial0` / `57600` | Cổng UART của AS608 |
| `HRM_ADMIN_USERNAME` / `HRM_ADMIN_PASSWORD` | `admin` / `admin` | Tài khoản tạo ở lần chạy đầu tiên |
| `HRM_DATABASE` | `instance/hrm.db` | Đường dẫn cơ sở dữ liệu |
| `HRM_SMTP_PASSWORD` | (trống) | Mật khẩu SMTP, được ưu tiên hơn mật khẩu lưu trên web |
| `HRM_PHOTO_DIR` | `instance/photos` | Thư mục lưu ảnh nhân viên |
| `HRM_DOCUMENT_DIR` | `instance/documents` | Thư mục lưu giấy tờ, hợp đồng đã ký (dữ liệu nhạy cảm: nhớ sao lưu và giới hạn quyền đọc) |
| `HRM_HOST` / `HRM_PORT` | `0.0.0.0` / `5000` | Địa chỉ và cổng web |

Loại nghỉ nào được hưởng lương cấu hình ở Cài đặt › Nghỉ phép; mặc định nghỉ ốm, thai sản **không** tính vào công tính lương vì do BHXH chi trả.

## Đưa lên GitHub

`.gitignore` đã loại `env/` và `instance/` (CSDL, bản sao lưu, `secret_key`, ảnh nhân viên), nên dữ liệu thật **không** bị đẩy lên. Mỗi lần push, GitHub Actions tự chạy bộ test.

```bash
git remote add origin git@github.com:<tài-khoản>/HRMi.git
git push -u origin main
```

Khi cài trên máy khác, nhớ sửa `WorkingDirectory`, `ExecStart` (đường dẫn tới thư mục dự án) và `User=pi` trong `deploy/hrmi.service` cho đúng máy đó.

## Kiểm thử

```bash
env/bin/python -m unittest discover tests -v
```

Bộ test gồm:
- nghiệp vụ chấm công: vào/ra, quét lặp, muộn, nghỉ trưa, OT, trạng thái có mặt;
- âm lịch (Tết, Giỗ Tổ), ngày lễ / nghỉ bù / hoán đổi / làm bù, công chuẩn và công tính lương có ngày lễ;
- OT theo loại ngày, ngưỡng tính, đăng ký OT, giờ đêm, giờ quy đổi, trần OT;
- đơn trong ngày: miễn muộn/sớm, quên chấm thêm/gỡ lượt chấm, kiểm tra hợp lệ, giới hạn, khoá tháng;
- giờ làm mặc định trên web, ca theo phòng ban (kế thừa phòng cha) / nhân viên, kiểm tra ca hợp lệ;
- phép theo tỉ lệ, thâm niên, cộng dồn tháng, chuyển phép có hạn, đơn qua năm, điều chỉnh, loại nghỉ theo luật;
- email: người nhận theo sơ đồ, hàng đợi, thử lại khi lỗi, bật/tắt sự kiện, kiểm tra cấu hình;
- báo cáo tháng và biểu đồ;
- nghỉ phép / công tác;
- quy trình bảng công (giải trình, trả lại, chốt, khoá tháng, mở lại);
- cây phân quyền: phạm vi theo nhánh, không tự duyệt, ma trận quyền, hồ sơ của mình;
- hợp đồng: kiểm tra thời hạn theo luật, chồng thời gian, trạng thái theo ngày, nhắc hết hạn (trang & email), lương bằng chữ, in hợp đồng;
- quá trình công tác, thủ tục nghỉ việc (thẻ, vân tay, hợp đồng, đơn chờ, tài khoản, công và phép sau ngày nghỉ), nhận lại;
- giấy tờ và quyền xem thông tin nhạy cảm (admin, chính mình, trưởng phòng có / không có quyền);
- trợ lý: tìm kiếm không dấu, bộ câu hỏi mẫu cho quản trị và nhân viên (đúng chủ đề, mở trang, việc của vai trò khác, câu lạc đề), không lộ link trang không có quyền, hiển thị markdown an toàn, kho hướng dẫn hợp lệ;
- ảnh nhân viên, luồng phần cứng với đầu đọc thẻ giả, các trang web.

Phần giao tiếp với PN532 và AS608 thật cần kiểm tra trên thiết bị.

## Giới hạn hiện tại

- **Bảo mật chưa đủ để mở ra Internet:** chưa có chống CSRF, chưa khoá tài khoản khi đăng nhập sai nhiều lần, chưa có nhật ký thao tác và sao lưu tự động (giai đoạn 0 trong [ROADMAP.md](ROADMAP.md)). Chỉ nên chạy trong mạng nội bộ tin cậy và đổi mật khẩu `admin` ngay.
- Trợ lý mới có tầng offline (tra cứu hướng dẫn); chưa hiểu câu hỏi tự do như mô hình AI và chưa trả lời số liệu cá nhân ("tôi còn mấy ngày phép" sẽ chỉ tới trang xem).
- Chưa có ca qua đêm và lịch xoay ca theo ngày (mỗi người một ca cố định).
- Thông báo mới chỉ có email, chưa có Telegram / Zalo; email nhắc định kỳ mới có hợp đồng sắp hết hạn (chưa có quên chấm ra).
- Giấy tờ nhạy cảm lưu dạng file thường trên thẻ nhớ, chưa mã hoá; chưa có nhật ký ai đã xem / tải (sẽ làm cùng audit log ở giai đoạn 0).
- Không có còi / LED tại máy chấm công; kết quả hiển thị trên kiosk.
- Dùng web server tích hợp của Flask, đủ cho mạng nội bộ nhỏ. Nếu mở ra ngoài, nên đặt sau một reverse proxy có HTTPS.

## Giấy phép

Phát hành theo giấy phép **GNU General Public License v3.0**, xem [LICENSE](LICENSE). Bạn được dùng, sửa và phân phối lại; nếu phát hành bản đã sửa đổi thì cũng phải công khai mã nguồn theo GPL-3.0.
