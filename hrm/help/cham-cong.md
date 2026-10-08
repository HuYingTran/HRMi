---
title: Chấm công bằng thẻ và vân tay
group: Chấm công
order: 1
roles: all
pages: [main.my_timesheet, main.kiosk]
keywords: [quẹt thẻ, vân tay, giờ vào, giờ ra, check in, check out, đi muộn, về sớm, kiosk, máy chấm công, ân hạn]
ask: [Chấm công thế nào?, Sao tôi bị tính đi muộn?]
---
Quẹt thẻ RFID hoặc đặt ngón tay lên máy mỗi khi **đến** và **về**. Lượt đầu tiên trong ngày là giờ vào, lượt cuối là giờ ra; quét lặp lại trong 60 giây bị bỏ qua. Màn hình kiosk đổi màu và chào theo kết quả (đúng giờ, đi muộn, OT, không nhận diện).

Xem kết quả của mình ở [[main.my_timesheet]].

## Cách tính
- **Đi muộn:** vào sau giờ bắt đầu ca quá số phút ân hạn (mặc định 5 phút).
- **Về sớm:** ra trước giờ kết thúc ca.
- **Giờ công:** tính trong ca, đã trừ nghỉ trưa.
- Giờ ca theo ca được gán cho bạn hoặc phòng ban; hồ sơ của bạn ghi rõ đang dùng ca nào.
- Có lý do chính đáng thì tạo **đơn đi muộn / về sớm** để ngày đó không bị tính.
