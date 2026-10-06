# HRMi: Mini HRM trên Raspberry Pi

![tests](../../actions/workflows/tests.yml/badge.svg)

Hệ thống quản lý nhân sự nhỏ chạy trực tiếp trên Raspberry Pi, chấm công bằng **thẻ RFID (PN532)** và **vân tay (AS608)**. Web quản trị, cổng tự phục vụ cho nhân viên và màn hình kiosk đều chạy trên cùng một máy, không cần Internet.

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
| Xem nhân viên, chấm công, báo cáo tháng | ✓ | ✓ (nhánh) | |
| Thêm / xoá chấm công thủ công | ✓ | ✓ (nhánh) | |
| Duyệt đơn nghỉ / công tác | ✓ | ✓ (nhánh) | |
| Duyệt, trả lại, chốt bảng công | ✓ | ✓ (nhánh) | |
| Sửa hồ sơ nhân viên | ✓ | tắt (bật được) | |
| Tổng quan, phòng ban, phân quyền, thiết bị, thêm/xoá nhân viên, đăng ký thẻ/vân tay, tài khoản | ✓ | | |

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
- **Phòng ban:** có phòng ban cấp trên và trưởng phòng; 2 chế độ xem: **sơ đồ cây** hoặc **danh sách** sửa trực tiếp trên bảng.
- **Tài khoản:**
  - tên đăng nhập là mã NV viết thường (ví dụ `nv004`);
  - admin tạo, đặt lại mật khẩu (sinh ngẫu nhiên), xoá, hoặc **cấp quyền quản trị** cho tài khoản nhân viên;
  - nhân viên đã nghỉ việc không đăng nhập được.

### Chấm công
- Quẹt thẻ hoặc đặt ngón tay: lượt đầu trong ngày là **giờ vào**, lượt cuối là **giờ ra**. Lượt quét lặp lại trong 60 giây bị bỏ qua.
- Tự tính phút đi muộn (có thời gian ân hạn), về sớm và giờ công (đã trừ nghỉ trưa).
- **Làm thêm (OT):** chấm công vào thứ 7, CN được tính là OT, không tính muộn/sớm, giờ OT đếm riêng.
- Có chấm công thủ công khi nhân viên quên thẻ. Báo cáo tháng xuất được CSV (mở được bằng Excel).
- **Kiosk:** đồng hồ lớn, vòng quét đổi màu theo kết quả (đúng giờ, đi muộn, OT, không nhận diện) kèm lời chào.

### Nghỉ phép & công tác
- Các loại đơn: phép năm, nghỉ ốm, không lương, **công tác**, khác; có thể nghỉ nửa ngày.
- Chỉ tính ngày làm việc; kiểm tra trùng đơn và số phép còn lại.
- Ngày công tác được tính là có làm và không trừ phép năm.
- Nhân viên tự tạo đơn; trưởng phòng (cả nhánh) hoặc admin duyệt. Nhân viên tự huỷ được đơn của mình khi đơn còn chờ duyệt.

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

**Công tính lương** = đi làm + công tác + nghỉ có lương (phép năm, khác); mỗi ngày tối đa 1 công. Nghỉ ốm / không lương và OT tính riêng. Admin chốt hàng loạt và xuất CSV ở trang **Chốt công**.

### Tổng quan (admin)
- Các chỉ số trong ngày: có mặt, đi muộn, nghỉ phép, công tác, vắng, đơn chờ duyệt.
- Biểu đồ **2 tuần** (tuần trước / tuần này, T2→CN, nét đứt chia tuần), có tooltip khi rê chuột và bảng số liệu đi kèm.
- Tỉ lệ có mặt hôm nay, xếp hạng đi muộn trong tháng, lượt chấm gần nhất, đơn chờ duyệt.

## Giao diện

- **Giao diện sáng mặc định.** Nút ☾/☀ ở chân thanh bên trái chuyển sáng/tối, lựa chọn được trình duyệt ghi nhớ. Bấm tên tài khoản bên cạnh để mở hồ sơ của mình.
- **Màu trạng thái** dùng thống nhất ở mọi nơi: xanh lá là đúng giờ, vàng là đi muộn, xanh dương là công tác, tím là nghỉ phép, xanh bạc hà là OT, đỏ là vắng. Bộ màu đã được kiểm tra bằng công cụ đo khoảng cách màu, có mô phỏng người mù màu. Màu luôn đi kèm nhãn chữ.
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
│   ├── permissions.py         # Cây phân quyền theo phòng ban, ma trận quyền
│   ├── photos.py              # Xử lý ảnh nhân viên
│   ├── views.py               # Trang web chính + API
│   ├── views_timesheet.py     # Bảng công, tài khoản nhân viên, trang phân quyền
│   ├── hardware/              # manager.py (luồng nền), rfid.py, fingerprint.py
│   ├── templates/             # Giao diện (Jinja2)
│   └── static/style.css
├── tests/test_hrm.py          # Test nghiệp vụ, quy trình, phân quyền, phần cứng giả, web
├── deploy/hrmi.service       # Chạy tự động bằng systemd
├── .github/workflows/tests.yml # CI: chạy test trên GitHub mỗi lần push / PR
└── instance/                  # Tạo khi chạy: hrm.db, secret_key, photos/ (không commit)
```

## Dữ liệu

| Bảng | Nội dung |
|---|---|
| `employees` | Hồ sơ nhân viên, `rfid_uid`, `fingerprint_id` (đều duy nhất), `photo` |
| `departments` | Phòng ban, `parent_id` (cấp trên), `manager_id` (trưởng phòng) |
| `attendance_logs` | Từng lượt quét: nhân viên, thời điểm, phương thức (`rfid` / `fingerprint` / `manual`), ghi chú |
| `leave_requests` | Đơn nghỉ / công tác: loại (`annual`, `sick`, `unpaid`, `business`, `other`), khoảng ngày, nửa ngày, trạng thái duyệt |
| `timesheets` | Bảng công tháng: trạng thái quy trình, ghi chú NV / cấp trên, bản chụp số liệu khi chốt (JSON), người chốt |
| `timesheet_explanations` | Giải trình theo ngày: lý do, giờ vào/ra đề nghị, trạng thái xử lý, phản hồi |
| `users` | Tài khoản: `role` = `admin` / `employee`, gắn với `employee_id` |
| `settings` | Cấu hình key/value, gồm ma trận quyền `perm.<vai trò>.<quyền>` |

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
2. **Nhân viên → Thêm:** điền hồ sơ, tải ảnh. Trong hồ sơ: **Quét** thẻ / **Đăng ký** vân tay (đặt ngón tay 2 lần), **Tạo tài khoản** đăng nhập.
3. Nhân viên quẹt thẻ hoặc đặt ngón tay mỗi khi đến và về; xem kết quả trên kiosk.
4. Nhân viên tự tạo **đơn nghỉ / công tác**; trưởng phòng hoặc admin duyệt.
5. Cuối tháng: **Chốt công → Gửi bảng công** → nhân viên giải trình và gửi duyệt → trưởng phòng duyệt và chốt → admin **xuất CSV** chuyển sang tính lương.
6. **Phân quyền:** điều chỉnh quyền của Trưởng phòng / Nhân viên nếu cần.

## Dữ liệu mô phỏng

```bash
env/bin/python seed.py                   # chỉ chạy khi CSDL chưa có nhân viên
env/bin/python seed.py --reset           # XOÁ nhân viên / chấm công / nghỉ phép rồi tạo lại
env/bin/python seed.py --days 90         # số ngày lịch sử (mặc định 60)
env/bin/python seed.py --no-photos       # không tạo avatar
env/bin/python seed.py --add-ot          # chỉ THÊM lượt OT thứ 7, CN vào CSDL đang có
env/bin/python seed.py --demo-workflow   # chỉ THÊM tài khoản NV + mô phỏng quy trình bảng công tháng trước
```

Script tạo:
- 6 phòng ban có cấp bậc và trưởng phòng;
- 20 nhân viên, mỗi người một avatar hoạt hình con vật (vẽ bằng Pillow; chạy `python demo_avatars.py` để xem trước);
- khoảng 1.600 lượt chấm công 60 ngày (đi muộn, vắng, quên quét ra, OT cuối tuần);
- khoảng 30 đơn nghỉ / công tác ở đủ các trạng thái;
- tài khoản nhân viên với mật khẩu demo **`123456`**;
- bảng công tháng trước ở đủ các bước của quy trình.

Kết quả cố định theo `--seed`, nên mỗi lần chạy đều ra cùng một bộ dữ liệu. Các tuỳ chọn `--add-ot` và `--demo-workflow` **chỉ thêm**, bỏ qua người đã có dữ liệu.

> Trước khi dùng thật, hãy xoá `instance/hrm.db` (và `instance/photos/`) để bắt đầu với CSDL trống; tài khoản admin được tạo lại ở lần chạy sau. Mật khẩu `123456` chỉ để demo: hãy dùng "Đặt lại MK" trong hồ sơ để sinh mật khẩu ngẫu nhiên.

## Cấu hình

Biến môi trường (trong file service: thêm dòng `Environment=...`):

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `HRM_RELOAD` | `1` | Tự nạp lại khi sửa code; đặt `0` khi chạy thật |
| `HRM_WORK_START` / `HRM_WORK_END` | `08:00` / `17:00` | Giờ bắt đầu và kết thúc ca |
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
| `HRM_PHOTO_DIR` | `instance/photos` | Thư mục lưu ảnh nhân viên |
| `HRM_HOST` / `HRM_PORT` | `0.0.0.0` / `5000` | Địa chỉ và cổng web |

Nghỉ có lương được định nghĩa ở `PAID_LEAVE` trong `hrm/services.py`; mặc định nghỉ ốm **không** tính vào công tính lương vì do BHXH chi trả.

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
- báo cáo tháng và biểu đồ;
- nghỉ phép / công tác;
- quy trình bảng công (giải trình, trả lại, chốt, khoá tháng, mở lại);
- cây phân quyền: phạm vi theo nhánh, không tự duyệt, ma trận quyền, hồ sơ của mình;
- ảnh nhân viên, luồng phần cứng với đầu đọc thẻ giả, các trang web.

Phần giao tiếp với PN532 và AS608 thật cần kiểm tra trên thiết bị.

## Giới hạn hiện tại

- Một ca làm việc cố định cho mọi người, chưa có ca xoay.
- Chưa có danh sách ngày lễ: ngày công chuẩn chỉ tính theo thứ trong tuần.
- Một đơn nghỉ không được kéo dài sang năm sau (cần tách thành hai đơn).
- Chưa có thông báo qua email hay tin nhắn; việc cần làm hiện bằng số đếm trên menu.
- Không có còi / LED tại máy chấm công; kết quả hiển thị trên kiosk.
- Dùng web server tích hợp của Flask, đủ cho mạng nội bộ nhỏ. Nếu mở ra ngoài, nên đặt sau một reverse proxy có HTTPS.

## Giấy phép

Phát hành theo giấy phép **GNU General Public License v3.0**, xem [LICENSE](LICENSE). Bạn được dùng, sửa và phân phối lại; nếu phát hành bản đã sửa đổi thì cũng phải công khai mã nguồn theo GPL-3.0.
