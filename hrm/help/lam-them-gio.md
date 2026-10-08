---
title: Đăng ký và tính làm thêm giờ (OT)
group: Chấm công
order: 4
roles: all
pages: [main.request_new, main.my_timesheet]
keywords: [ot, tăng ca, làm thêm, overtime, hệ số, 150, 200, 300, làm đêm, cuối tuần, ngày lễ, OT chưa duyệt]
ask: [Đăng ký OT thế nào?, OT được tính hệ số bao nhiêu?]
---
Tạo **đơn đăng ký OT** ở [[main.request_new]] với khung giờ dự kiến làm thêm. Mặc định OT ngày thường chỉ được tính khi có đơn được duyệt, và chỉ phần nằm trong khung giờ đăng ký. Làm thêm chưa có đơn hiện là "OT chưa duyệt".

## Hệ số mặc định (theo luật)
- Ngày thường: **150%**, tính phần sau giờ tan ca khi ở lại ít nhất 30 phút.
- Ngày nghỉ hằng tuần: **200%**, toàn bộ thời gian làm.
- Ngày lễ: **300%**, toàn bộ thời gian làm.
- Giờ trong khoảng 22:00–06:00 cộng thêm **30%**.

Trần OT mặc định 40 giờ/tháng, 200 giờ/năm. Quản trị chỉnh hệ số và ngưỡng ở [[main.work_rules]].
