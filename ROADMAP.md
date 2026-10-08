# Kế hoạch phát triển HRMi

Lộ trình đưa HRMi từ **chấm công + nghỉ phép** lên thành **mini HRM dùng thật được** cho doanh nghiệp nhỏ ở Việt Nam. Mỗi giai đoạn có thể phát hành độc lập; giai đoạn sau dựa trên dữ liệu của giai đoạn trước.

| Giai đoạn | Chủ đề | Trạng thái | Còn lại / Ước lượng |
|---|---|---|---|
| **0** | Bảo mật & an toàn dữ liệu | ☐ Chưa làm | **Ưu tiên kế tiếp**, ~1 tuần |
| **1** | Chấm công đúng luật VN | ✅ Xong | Đơn "ra ngoài" chưa trừ giờ công |
| **2** | Ca làm việc | ◐ Một phần | Lịch phân ca theo ngày, trang Xếp ca, ca qua đêm: 1–2 tuần |
| **3** | Hồ sơ & hợp đồng | ✅ Xong | Mã hoá giấy tờ, nhật ký xem (cùng giai đoạn 0) |
| **4** | Phép nâng cao | ✅ Xong | Sổ biến động phép (`leave_ledger`) để sau |
| **5** | Lương | ☐ Chưa làm | 3–4 tuần; đầu vào hợp đồng, người phụ thuộc đã có |
| **6** | Thông báo & tích hợp | ◐ Một phần | Telegram/Zalo, nhắc quên chấm ra, Excel, API: 1–2 tuần |
| **7** | Phần cứng & độ tin cậy | ☐ Chưa làm | 1–2 tuần |
| **8** | Trợ lý AI (chat hướng dẫn, mở trang) | ◐ Tầng offline xong | Tầng Claude API (B3–B5); xem [AI_ASSISTANT.md](AI_ASSISTANT.md) |

### Hiện trạng (cập nhật 08/10/2026)

- Đã có: chấm công RFID + vân tay, kiosk, nhân viên/phòng ban nhiều cấp, phân quyền theo ma trận, nghỉ phép nhiều loại có duyệt, bảng công tháng có chốt/xác nhận/mở lại, ngày lễ & nghỉ bù/làm bù, OT theo hệ số (thường/nghỉ tuần/lễ/đêm) có trần tháng/năm và tuỳ chọn bắt buộc đơn OT, đơn trong ngày (đi muộn, về sớm, quên chấm, ra ngoài, đăng ký OT), ca riêng theo phòng ban/nhân viên, quy tắc phép (tỉ lệ, thâm niên, cộng dồn, chuyển phép), thông báo email qua hàng đợi; hồ sơ mở rộng có quyền xem thông tin nhạy cảm riêng, hợp đồng lao động (in, nhắc hết hạn), quá trình công tác, người phụ thuộc, giấy tờ, thủ tục nghỉ việc.
- Mã nguồn: ~6.900 dòng Python trong `hrm/` và `tests/`; module mới `calendar_vn.py`, `workrules.py`, `day_requests.py`, `notify.py`, `navigation.py`, `views_rules.py`, `profiles.py`, `views_profile.py`; 78 test (`unittest`) chạy trên GitHub Actions.
- **Lỗ hổng lớn nhất hiện nay là giai đoạn 0**: chưa có CSRF, chưa khoá đăng nhập sai, chưa có audit log và sao lưu tự động. Từ giai đoạn 3 hệ thống lưu cả CCCD, tài khoản ngân hàng, lương và scan giấy tờ, nên rủi ro khi lộ dữ liệu cao hơn hẳn: cần làm giai đoạn 0 trước khi nhập dữ liệu thật.

### Thứ tự đề xuất

1. **Giai đoạn 0** (toàn bộ), kèm `PRAGMA user_version` cho migration vì lược đồ sắp tăng nhanh.
2. **Phần còn lại của giai đoạn 2** (phân ca theo ngày, ca qua đêm): sửa sâu `summarize_day()`, nên làm khi bộ test chấm công còn đang mới.
3. **Giai đoạn 5** (lương): lương hợp đồng, phụ cấp, lương đóng BH, người phụ thuộc đã có từ giai đoạn 3; còn cần audit log (0.3).
4. Giai đoạn 6 và 7 chen vào khi có nhu cầu cụ thể (vd. khách cần Zalo, cần nhiều máy chấm công).

### Nguyên tắc chung

- Giữ kiến trúc hiện tại: Flask + SQLite, chạy offline, không CDN.
- Mọi thay đổi lược đồ đi qua `_migrate()` trong `hrm/db.py`; CSDL cũ phải nâng cấp được mà không mất dữ liệu. Bảng có `CHECK` (như `leave_requests`) phải dựng lại bằng bảng tạm, đã có sẵn mẫu `LEAVE_TABLE.format(name=...)`.
- Nghiệp vụ nằm ở `services.py` / module mới, view chỉ gọi; quyền mới thêm vào ma trận trong `permissions.py`.
- Mỗi tính năng có test trong `tests/` (tách dần `test_hrm.py` thành nhiều file theo mảng) và cập nhật README.
- Số liệu công vẫn **tính từ log khi xem**; chỉ bản chốt mới lưu cố định.

---

## Giai đoạn 0: Bảo mật & an toàn dữ liệu ☐

> Ưu tiên cao nhất, ít việc nhưng giảm rủi ro nhiều nhất. Chưa bắt đầu; nên làm ngay vì các giai đoạn 1, 2, 4, 6
> đã đưa hệ thống tới mức dùng được với dữ liệu thật.

### 0.1 Chống CSRF
- Thêm token CSRF cho mọi form POST và các API gọi từ JS (header `X-CSRFToken`). Có thể dùng `Flask-WTF` (`CSRFProtect`) hoặc tự viết ~30 dòng (token trong session, kiểm tra ở `before_request`) để không thêm phụ thuộc.
- Kiosk chỉ đọc, không cần token.
- **Xong khi:** POST thiếu/sai token trả 400; test bao phủ một form và một API.

### 0.2 Đăng nhập
- Giới hạn đăng nhập sai: khoá tài khoản 15 phút sau 5 lần sai liên tiếp (lưu `failed_logins`, `locked_until` trong `users`).
- **Buộc đổi mật khẩu** ở lần đăng nhập đầu với `admin/admin` và với mật khẩu do admin đặt lại (cột `must_change_password`).
- Yêu cầu độ dài tối thiểu 8 ký tự.
- Cookie phiên: `SESSION_COOKIE_HTTPONLY`, `SAMESITE=Lax`; `SECURE` khi chạy sau HTTPS; hết hạn phiên sau thời gian không hoạt động.

### 0.3 Nhật ký thao tác (audit log)
- Bảng mới:
  ```sql
  CREATE TABLE audit_logs (
      id         INTEGER PRIMARY KEY,
      ts         TEXT NOT NULL DEFAULT (datetime('now','localtime')),
      user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
      action     TEXT NOT NULL,      -- vd. attendance.add, timesheet.reopen
      target     TEXT,               -- vd. employee:12, timesheet:2026-09:12
      detail     TEXT                -- JSON trước/sau
  );
  ```
- Ghi lại tối thiểu: thêm/xoá chấm công thủ công, duyệt/huỷ đơn nghỉ và đơn trong ngày, sửa quy tắc công/phép, sửa ca, điều chỉnh phép (`leave_adjustments`), đổi cấu hình email, chốt/mở lại bảng công, sửa hồ sơ, đổi quyền, cấp quyền admin, đặt lại mật khẩu, đăng ký/gỡ thẻ & vân tay, đăng nhập sai.
- Trang **Nhật ký** cho admin: lọc theo người, hành động, khoảng ngày; hồ sơ nhân viên có tab lịch sử thay đổi.
- **Xong khi:** mọi thao tác trong danh sách trên tạo đúng 1 dòng log; log không sửa/xoá được qua web.

### 0.4 Sao lưu & khôi phục
- Script `deploy/backup.sh` dùng `sqlite3 instance/hrm.db ".backup ..."` (an toàn khi đang chạy WAL) + nén thư mục `photos/`; giữ 7 bản ngày, 4 bản tuần, 12 bản tháng.
- `deploy/hrmi-backup.service` + `.timer` chạy hằng đêm; đích có thể là USB / thư mục NAS (biến `HRM_BACKUP_DIR`).
- Trang **Thiết bị** hiện thời điểm sao lưu gần nhất, cảnh báo nếu quá 48 giờ; nút "Tải bản sao lưu" cho admin.
- Hướng dẫn khôi phục trong README; có test khôi phục từ bản sao lưu.

### 0.5 Khác
- Thay web server tích hợp bằng `waitress` (thuần Python, chạy tốt trên Pi) trong `hrmi.service`.
- Mẫu cấu hình nginx/Caddy + HTTPS trong `deploy/` cho trường hợp mở ra ngoài mạng nội bộ.

---

## Giai đoạn 1: Chấm công đúng luật Việt Nam ✅

> Đã làm xong. Khác với dự kiến ban đầu: ngày nghỉ bù được lưu như một ngày lễ riêng; thay cho cột
> `paid` / `compensatory_for` là 3 loại ngày `holiday` / `off` (nghỉ hoán đổi) / `makeup` (làm bù).
> Đơn trong ngày nằm ở bảng riêng `attendance_requests`; đơn "ra ngoài" chỉ để ghi nhận, chưa trừ giờ công.
> Chi tiết xem README, mục "Ngày lễ & làm thêm giờ" và "Đơn trong ngày".
>
> **Còn treo:** đơn "ra ngoài" được duyệt có trừ vào giờ công hay không (cấu hình được). Làm cùng giai đoạn 5.

### 1.1 Ngày lễ
- Bảng `holidays (day TEXT PRIMARY KEY, name TEXT, paid INTEGER DEFAULT 1, compensatory_for TEXT)`; hỗ trợ **ngày nghỉ bù** và **ngày làm bù** (thứ 7 đi làm thay).
- Trang quản lý ngày lễ, nút "Nạp ngày lễ năm X" với các ngày cố định (1/1, 30/4, 1/5, 2/9 + 1 ngày liền kề) và nhập tay Tết Âm lịch, Giỗ Tổ (thay đổi theo năm).
- Sửa `is_workday()` / `workdays_between()` trong `services.py` dùng lịch này: ngày lễ không tính vắng, được tính **công có lương**, không trừ phép; đơn nghỉ không đếm ngày lễ.
- Lịch, heatmap, kiosk, báo cáo hiện ngày lễ bằng màu/nhãn riêng.

### 1.2 Làm thêm giờ (OT) theo hệ số
- Phân loại OT: ngày thường sau giờ (150%), ngày nghỉ tuần (200%), ngày lễ (300%), cộng phụ cấp ca đêm 22:00–06:00 (+30%). Hệ số để trong `settings`, sửa được.
- Ngưỡng tính OT ngày thường: ra sau giờ kết thúc ca ≥ N phút (mặc định 30).
- **Đơn đăng ký OT** (tuỳ chọn bật trong cấu hình): chỉ tính OT khi có đơn được duyệt; không có đơn thì giờ làm thêm hiện là "chờ xác nhận".
- Cảnh báo vượt trần OT: 40 giờ/tháng, 200 (hoặc 300) giờ/năm.
- Báo cáo tháng và bản chốt tách cột theo từng loại OT.

### 1.3 Đơn trong ngày
- Thêm loại đơn: **đi muộn**, **về sớm**, **quên chấm công**, **ra ngoài**. Dựng lại `leave_requests` để mở rộng `CHECK` hoặc tách bảng `attendance_requests`.
- Đơn "quên chấm công" được duyệt sẽ tự thêm lượt `manual`, như giải trình hiện nay.
- Giới hạn số lần đi muộn có đơn mỗi tháng (cấu hình).

**Xong khi:** bảng công tháng 9/2026 (có 2/9) và tháng có Tết tính đúng ngày công chuẩn; test cho từng loại OT và ngày làm bù.

---

## Giai đoạn 2: Ca làm việc ◐

> **Đã làm:** giờ làm mặc định sửa trên web (trang "Giờ làm & ca"), bảng `shifts`, gán ca cho phòng ban
> (kế thừa xuống phòng con) hoặc nhân viên (`shift_id`); mọi phép tính công, muộn, OT theo ca của từng người.
>
> **Còn lại** (theo thứ tự):
> 1. Viết test cho ca qua đêm trước (vào 22:00 ngày D, ra 06:00 ngày D+1; quên chấm ra; OT đêm).
> 2. Gán lượt quét vào "ngày công" theo ca trong `summarize_day()` / `_logs_by_employee()`.
> 3. Bảng `shift_assignments` + trang Xếp ca.
> 4. Lịch ca ở `/me`, kiosk chào theo ca.

- Bảng `shifts (id, name, start, end, lunch_start, lunch_end, grace_minutes, overnight, color)`; cấu hình `HRM_WORK_*` hiện tại trở thành **ca mặc định** (migration tạo sẵn).
- Gán ca theo **phòng ban** hoặc **nhân viên**, và **lịch phân ca** theo ngày (`shift_assignments (employee_id, day, shift_id)`) cho ca xoay.
- Trang **Xếp ca**: lưới nhân viên × ngày, kéo thả hoặc chọn hàng loạt, sao chép tuần trước.
- **Ca qua đêm:** lượt quét được gán vào "ngày công" theo ca chứ không theo ngày dương lịch. Đây là thay đổi lớn nhất trong `summarize_day()` / `_logs_by_employee()`; cần viết test trước khi sửa.
- Nhân viên xem lịch ca của mình ở `/me`; kiosk chào theo ca.

**Xong khi:** ca 22:00–06:00 tính đúng giờ vào/ra, muộn, OT đêm; báo cáo cũ không đổi với nhân viên dùng ca mặc định.

---

## Giai đoạn 3: Hồ sơ nhân sự & hợp đồng ✅

> Đã làm xong (module `profiles.py`, `views_profile.py`, test `tests/test_profiles.py`). Khác dự kiến:
> - Trạng thái hợp đồng (hiệu lực / sắp hết hạn / hết hạn) **không lưu** mà tính theo ngày khi xem; chỉ lưu
>   `status = signed | terminated` và `terminated_on` khi chấm dứt sớm.
> - Thêm quyền `employees.sensitive` (mặc định tắt cho trưởng phòng); nhân viên luôn xem được thông tin của mình.
>   Hợp đồng, quyết định, nghỉ việc chỉ admin làm; người phụ thuộc và giấy tờ thì người có cả quyền sửa hồ sơ lẫn
>   quyền nhạy cảm cũng làm được.
> - Nghỉ việc chỉ ghi nhận được vào hoặc sau ngày làm việc cuối (không hẹn trước); trạng thái nhân viên không còn
>   sửa trực tiếp trong form hồ sơ mà đi qua thủ tục nghỉ việc / nhận lại.
> - `termination_date` được dùng luôn trong tính công (sau ngày nghỉ không tính vắng, không hưởng lễ) và phép
>   theo tỉ lệ (phần "người ra giữa năm" còn thiếu ở giai đoạn 4).
> - Thêm trang **Cài đặt › Công ty** (thông tin bên A khi in hợp đồng) và số tiền bằng chữ.
>
> **Còn treo:** file giấy tờ chưa mã hoá khi lưu; chưa ghi nhật ký ai đã xem / tải giấy tờ, xem lương
> (làm cùng audit log 0.3); chưa có phụ lục hợp đồng (hiện ký hợp đồng mới hoặc ghi quyết định thay đổi lương).

### 3.1 Mở rộng hồ sơ ✅
- CCCD (số, ngày cấp, nơi cấp), mã số thuế, sổ BHXH, tài khoản ngân hàng, quê quán, hôn nhân, trình độ, liên hệ khẩn cấp.
- Bảng `dependents` (người phụ thuộc, có thời gian giảm trừ; `profiles.active_dependents()` dùng cho thuế ở giai đoạn 5).
- Bảng `documents`, file trong `instance/documents/<id>/` tên ngẫu nhiên, chỉ nhận PDF / ảnh / Office ≤ 8 MB, tải qua kiểm tra quyền.

### 3.2 Hợp đồng lao động ✅
- Bảng `contracts`: số (tự đánh), loại, ngày ký / bắt đầu / kết thúc, chức danh, lương, lương đóng BH, phụ cấp JSON, bản đã ký.
- Kiểm tra theo BLLĐ 2019: xác định thời hạn ≤ 36 tháng, thử việc ≤ 180 ngày, không chồng thời gian, cảnh báo ký xác định thời hạn lần 3.
- Tổng quan & trang **Hợp đồng**: sắp hết hạn trong 30 ngày, đã hết hạn chưa ký tiếp, chưa có hợp đồng, sinh nhật trong tháng.
  Email nhắc quản trị mỗi ngày một lần qua `notify` (sự kiện `contract_expiring`).
- In hợp đồng / hợp đồng thử việc dạng A4 (in / lưu PDF từ trình duyệt).

### 3.3 Lịch sử công tác ✅
- Bảng `employment_history`: vào làm, điều chuyển, đổi chức danh, thăng chức, thay đổi lương, nghỉ việc, nhận lại;
  ngày hiệu lực, số quyết định, người quyết định. Tự ghi khi sửa phòng ban / chức danh và khi lương hợp đồng mới khác hợp đồng trước.
- Thủ tục **nghỉ việc** theo checklist (thu hồi thẻ, xoá vân tay AS608, chấm dứt hợp đồng, huỷ đơn chờ, khoá / xoá tài khoản,
  bỏ vị trí trưởng phòng, việc bàn giao) và **nhận lại làm**.

---

## Giai đoạn 4: Nghỉ phép nâng cao ✅

> Đã làm hết, trừ bảng `leave_ledger`: số dư được tính lại từ đơn nghỉ + bảng `leave_adjustments`
> (điều chỉnh thủ công) mỗi khi xem, nên luôn khớp với đơn. Thâm niên tính tới 1/1 của năm.
> Quy tắc phép sửa trên web (trang cấu hình "Nghỉ phép"). `leave_ledger` chỉ làm nếu cần giải trình số dư
> theo từng biến động; nếu không, trang chi tiết số dư tính từ đơn + điều chỉnh là đủ.

- Phép năm tính **theo tỉ lệ** cho người vào/ra giữa năm; **+1 ngày mỗi 5 năm** thâm niên (theo `hire_date`).
- Tuỳ chọn **cộng dồn theo tháng** (1 ngày/tháng) thay vì cấp đủ đầu năm.
- **Chuyển phép tồn** sang năm sau, có hạn dùng (vd. hết 31/3) và số ngày tối đa.
- Cho phép đơn kéo dài qua năm (tự tách khi tính số dư), bỏ giới hạn hiện tại.
- Thêm loại nghỉ theo luật: kết hôn (3 ngày), con kết hôn (1), tang (3), thai sản; mỗi loại cấu hình có lương / không lương / BHXH chi trả (thay hằng `PAID_LEAVE` cứng trong `services.py`).
- Bảng `leave_ledger` ghi từng biến động số dư (cấp, dùng, chuyển, hết hạn) để giải thích được số phép còn lại.

---

## Giai đoạn 5: Lương ☐

> Đầu vào là **bảng công đã chốt** (bản chụp JSON), nên lương không bị thay đổi khi sửa log sau khi chốt.
> Bản chốt hiện đã có sẵn các cột OT theo loại (`ot_weekday/weekend/holiday/night_hours`, `ot_weighted_hours`)
> và `payable_days`, đủ làm đầu vào. Cần giai đoạn 3 (lương hợp đồng, người phụ thuộc) và audit log (0.3).

- **Cấu hình:** lương cơ bản/lương đóng BH, phụ cấp cố định (đã có trong `contracts`, lấy hợp đồng hiệu lực trong tháng; tháng có hai hợp đồng thì chia theo ngày), phụ cấp cố định & theo ngày công, thưởng/phạt, tạm ứng; tỉ lệ BHXH/BHYT/BHTN phần NLĐ và DN, lương tối thiểu vùng, trần đóng BH; biểu thuế TNCN lũy tiến 7 bậc, giảm trừ bản thân và người phụ thuộc. Mọi tham số lưu theo **ngày hiệu lực** để đổi luật không ảnh hưởng kỳ cũ.
- **Công thức:** lương theo ngày công = lương / công chuẩn × công tính lương; cộng OT theo hệ số ở giai đoạn 1; trừ BH, thuế, tạm ứng → thực lĩnh.
- **Bảng lương tháng:** quy trình *Nháp → Đã duyệt → Đã chi*, khoá giống bảng công; điều chỉnh tay từng dòng có lý do (ghi audit log).
- **Phiếu lương:** nhân viên xem ở `/me` (chỉ của mình), in/PDF; admin xuất bảng lương `.xlsx` và file chuyển khoản ngân hàng.
- Test với các tình huống mẫu: lương dưới mức chịu thuế, có người phụ thuộc, vượt trần BH, vào giữa tháng.

---

## Giai đoạn 6: Thông báo & tích hợp ◐

> **Đã làm:** email SMTP qua hàng đợi `email_outbox` + luồng nền (`Mailer`), thử lại khi lỗi, bật/tắt
> từng sự kiện trên trang cấu hình "Email". Sự kiện đã nối: đơn nghỉ / đơn trong ngày mới và kết quả duyệt,
> bảng công cần xác nhận / bị trả lại.
>
> Đã có thêm việc nhắc hằng ngày trong luồng `Mailer` (chạy một lần mỗi ngày): hợp đồng sắp hết hạn.
>
> **Còn lại:** tách `notify` thành lớp kênh chung rồi thêm Telegram / Zalo; nhắc quên chấm ra, sao lưu lỗi
> (cắm thêm vào việc hằng ngày của `Mailer`); Excel; API; PWA.

- **Thông báo** qua lớp `notify` dùng chung, kênh cắm thêm được:
  - Telegram bot (dễ nhất, chỉ cần token), Zalo OA (phổ biến hơn ở VN), email SMTP.
  - Sự kiện: đơn mới cần duyệt, đơn được duyệt/từ chối, bảng công cần xác nhận/bị trả lại, quên chấm ra, hợp đồng sắp hết hạn, sao lưu lỗi.
  - Gửi qua hàng đợi trong SQLite + luồng nền, để mất mạng không làm chậm web.
- **Excel:** xuất báo cáo/bảng công/bảng lương `.xlsx` có định dạng (`openpyxl`); nhập nhân viên hàng loạt từ mẫu Excel, có bước xem trước và báo lỗi từng dòng.
- **API:** REST đọc chỉ có token (nhân viên, bảng công đã chốt) và webhook khi chốt công, để nối sang phần mềm kế toán.
- **PWA** cho trang nhân viên: thêm vào màn hình chính điện thoại, xem công/đơn nhanh.

---

## Giai đoạn 7: Phần cứng & độ tin cậy ☐

- **Còi + LED RGB** (GPIO) báo kết quả quét: 1 tiếng đúng giờ, 2 tiếng đi muộn, tiếng dài khi không nhận diện.
- **RTC DS3231** (I2C, dùng chung bus với PN532): giữ giờ khi mất mạng; trang Thiết bị cảnh báo khi NTP chưa đồng bộ và chặn ghi lượt quét nếu năm < 2025.
- **Hàng đợi lượt quét:** ghi lượt quét vào file append-only trước, đồng bộ vào DB sau, để không mất lượt khi DB bận hoặc app đang khởi động lại.
- **Sao lưu mẫu vân tay:** tải template từ AS608 lưu vào `instance/`, nạp lại khi thay cảm biến.
- **Chống chấm hộ** (tuỳ chọn): chế độ bắt buộc thẻ + vân tay; hoặc camera Pi chụp ảnh lúc quét, lưu 30 ngày, xem trong chi tiết lượt chấm.
- **Nhiều máy chấm công:** một Pi làm máy chủ, các Pi khác chạy chế độ `terminal` chỉ đọc thẻ và gửi lượt quét qua API (có hàng đợi khi mất kết nối).
- Watchdog systemd (`WatchdogSec`) và tự khởi động lại luồng phần cứng khi thiết bị treo.

---

## Ngoài phạm vi (cân nhắc sau)

Tuyển dụng, đánh giá KPI, đào tạo, quản lý tài sản cấp phát, chấm công GPS qua app di động. Đây là những mảng lớn, ít phù hợp với định hướng "chạy trên một chiếc Pi trong văn phòng". Chỉ làm khi có nhu cầu thật.

## Việc kỹ thuật làm song song

- [x] CI chạy test trên GitHub Actions (`.github/workflows/tests.yml`).
- [~] Tách test theo mảng: đã có `test_phase2.py`, `test_rules.py`; còn tách `test_hrm.py` (514 dòng) thành `test_attendance.py`, `test_leave.py`, `test_timesheet.py`, `test_permissions.py`, `test_web.py`. Đặt lại tên `test_phase2.py` theo nội dung.
- [~] Tách view: đã có `views_timesheet.py`, `views_rules.py`, menu gom về `navigation.py`; `views.py` vẫn 872 dòng, còn tách nhân viên, chấm công, nghỉ phép, đơn trong ngày, thiết bị, API thành blueprint.
- [~] `services.py` (~850 dòng) đã tách một phần ra `calendar_vn.py`, `workrules.py`, `day_requests.py`, `profiles.py`; còn tách phần nghỉ phép ra `leave.py`.
- [ ] Đánh số phiên bản lược đồ (`PRAGMA user_version`) thay cho việc dò cột trong `_migrate()`. Nên làm cùng giai đoạn 0.
- [ ] Thêm kiểm tra lint (`ruff`) vào CI.
- [ ] Ghi `CHANGELOG.md` và gắn tag phiên bản: `v0.2` cho các giai đoạn 1, 4 và phần đã làm của 2, 6 (đang nằm chưa commit), sau đó mỗi giai đoạn một tag.
