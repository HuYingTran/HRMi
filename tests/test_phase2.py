"""Giờ làm & ca, phép nâng cao, thông báo email. Chạy: env/bin/python -m unittest discover tests"""
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from werkzeug.datastructures import MultiDict

from hrm import create_app, notify, services, workrules
from hrm.services import ServiceError
from hrm.workrules import RuleError

from test_hrm import Base
from test_rules import scan, set_rule


def shift_form(name, start, end, days, lunch=("12:00", "13:00"), grace=5):
    return MultiDict([("name", name), ("work_start", start), ("work_end", end), ("lunch_start", lunch[0]),
                      ("lunch_end", lunch[1]), ("grace_minutes", str(grace))]
                     + [("work_days", str(d)) for d in days])


class ScheduleTest(Base):
    def setUp(self):
        super().setUp()
        self.conn.execute("INSERT INTO departments (id, name) VALUES (1, 'Kho'), (2, 'Kho lạnh')")
        self.conn.execute("UPDATE departments SET parent_id = 1 WHERE id = 2")
        self.conn.execute("UPDATE employees SET department_id = 2")
        self.conn.commit()

    def cur(self):
        return self.conn.execute("SELECT * FROM employees").fetchone()

    def day(self, iso):
        return services.employee_period(self.conn, self.cur()["id"], iso, iso, self.cfg)[0]

    def test_default_schedule_from_web(self):
        workrules.save_default_schedule(self.conn, shift_form("", "07:30", "16:30", [0, 1, 2, 3, 4, 5]))
        r = services.record_scan(self.conn, self.cur(), "rfid", self.cfg, now=datetime(2026, 10, 5, 7, 45))
        self.assertEqual(r["late_minutes"], 15)
        scan(self.conn, self.cur(), self.cfg, datetime(2026, 10, 3, 7, 30))  # thứ 7 là ngày làm việc
        self.assertEqual(self.day("2026-10-03")["status"], "missing_out")
        self.assertEqual(services.monthly_report(self.conn, 2026, 10, self.cfg)[0]["workdays"], 27)

    def test_department_shift_inherited_and_employee_override(self):
        workrules.save_shift(self.conn, shift_form("Ca chiều", "13:00", "21:00", [0, 1, 2, 3, 4],
                                                   lunch=("17:00", "17:30"), grace=0))
        workrules.save_shift(self.conn, shift_form("Cuối tuần", "08:00", "17:00", [5, 6]))
        afternoon, weekend = [r["id"] for r in self.conn.execute("SELECT id FROM shifts ORDER BY id")]
        self.conn.execute("UPDATE departments SET shift_id = ? WHERE id = 1", (afternoon,))  # phòng cha
        self.conn.commit()
        scan(self.conn, self.cur(), self.cfg, datetime(2026, 10, 5, 13, 10), datetime(2026, 10, 5, 21, 0))
        d = self.day("2026-10-05")
        self.assertEqual((d["status"], d["late_minutes"], d["hours"]), ("late", 10, 7.33))
        # gán ca riêng cho nhân viên: thứ 2 thành ngày nghỉ -> làm là OT
        self.conn.execute("UPDATE employees SET shift_id = ?", (weekend,))
        self.conn.commit()
        self.assertEqual(self.day("2026-10-05")["status"], "ot")
        self.assertEqual(self.day("2026-10-06")["status"], "off")
        workrules.delete_shift(self.conn, weekend)  # xoá ca -> về ca phòng ban
        self.assertEqual(self.day("2026-10-05")["status"], "late")

    def test_invalid_schedule(self):
        for form in (shift_form("A", "17:00", "08:00", [0]),                 # ra trước vào
                     shift_form("A", "08:00", "17:00", []),                  # không có ngày làm
                     shift_form("A", "08:00", "17:00", [0], lunch=("07:00", "08:00")),  # trưa ngoài giờ
                     shift_form("A", "8h", "17:00", [0])):
            with self.assertRaises(RuleError):
                workrules.save_shift(self.conn, form)
        workrules.save_shift(self.conn, shift_form("A", "08:00", "17:00", [0]))
        with self.assertRaises(RuleError):
            workrules.save_shift(self.conn, shift_form("A", "09:00", "18:00", [0]))  # trùng tên


class LeaveAdvancedTest(Base):
    def set_emp(self, **cols):
        sets = ", ".join(f"{k} = ?" for k in cols)
        self.conn.execute(f"UPDATE employees SET {sets}", tuple(cols.values()))
        self.conn.commit()
        return self.conn.execute("SELECT * FROM employees").fetchone()

    def bal(self, emp, year=2026, today=date(2026, 10, 6)):
        return services.leave_balance(self.conn, emp, year, self.cfg, today=today)

    def test_prorate_and_seniority(self):
        emp = self.set_emp(annual_leave_days=12, hire_date="2026-07-20")  # sau ngày 15 -> từ tháng 8
        self.assertEqual((self.bal(emp)["months"], self.bal(emp)["earned"]), (5, 5))
        set_rule(self.conn, "leave_prorate", 0)
        self.assertEqual(self.bal(emp)["earned"], 12)
        emp = self.set_emp(hire_date="2016-03-01")  # 9 năm tròn tới 1/1/2026 -> +1
        self.assertEqual((self.bal(emp)["seniority"], self.bal(emp)["quota"]), (1, 13))
        emp = self.set_emp(hire_date="2016-01-01")  # 10 năm tròn -> +2
        self.assertEqual(self.bal(emp)["seniority"], 2)

    def test_monthly_accrual(self):
        set_rule(self.conn, "leave_accrual", "month")
        emp = self.set_emp(annual_leave_days=12, hire_date="2020-06-01")
        b = self.bal(emp)
        self.assertEqual((b["seniority"], b["earned"]), (1, 10.83))  # 13 × 10/12
        self.assertEqual(self.bal(emp, 2025)["earned"], 12)          # năm đã qua: đủ cả năm (4 năm, chưa +1)

    def test_carry_over_with_expiry(self):
        set_rule(self.conn, "leave_carry_max", 5)
        emp = self.set_emp(annual_leave_days=12, hire_date="2024-01-01")
        scan(self.conn, emp, self.cfg, datetime(2025, 3, 3, 8, 0))  # có dữ liệu năm 2025
        lid = services.create_leave(self.conn, emp["id"], "annual", "2025-12-01", "2025-12-05", False, None,
                                    self.cfg, today=date(2025, 11, 1))
        services.review_leave(self.conn, lid, True)  # năm 2025 dùng 5/12 -> tồn 7, chuyển tối đa 5
        b = self.bal(emp, today=date(2026, 2, 1))
        self.assertEqual((b["carry_in"], b["quota"], b["remaining"]), (5, 17, 17))
        lid = services.create_leave(self.conn, emp["id"], "annual", "2026-03-02", "2026-03-03", False, None,
                                    self.cfg, today=date(2026, 2, 1))
        services.review_leave(self.conn, lid, True)
        b = self.bal(emp, today=date(2026, 4, 1))  # dùng 2 ngày từ phép chuyển, 3 ngày còn lại hết hạn
        self.assertEqual((b["carry_expired"], b["remaining"]), (3, 12))

    def test_cross_year_leave_and_adjustment(self):
        emp = self.set_emp(annual_leave_days=2)
        workrules.save_holiday(self.conn, "2027-01-01", "Tết Dương lịch", "holiday", self.cfg)
        lid = services.create_leave(self.conn, emp["id"], "annual", "2026-12-31", "2027-01-04", False, None,
                                    self.cfg)  # T5 31/12 + (T6 1/1 nghỉ lễ) + T2 4/1
        self.assertEqual(self.conn.execute("SELECT days FROM leave_requests WHERE id = ?", (lid,)).fetchone()[0], 2)
        self.assertEqual((self.bal(emp)["pending"], self.bal(emp, 2027)["pending"]), (1, 1))
        with self.assertRaises(ServiceError):  # 2026 chỉ còn 1 ngày khả dụng
            services.create_leave(self.conn, emp["id"], "annual", "2026-11-02", "2026-11-03", False, None, self.cfg)
        services.adjust_leave(self.conn, emp["id"], 2026, "+1.5", "Thưởng phép")
        self.assertEqual(self.bal(emp)["available"], 2.5)
        with self.assertRaises(ServiceError):
            services.adjust_leave(self.conn, emp["id"], 2026, "1", "")

    def test_statutory_leave_types(self):
        with self.assertRaises(ServiceError):  # kết hôn tối đa 3 ngày
            services.create_leave(self.conn, self.emp["id"], "wedding", "2026-09-07", "2026-09-10", False, None,
                                  self.cfg)
        lid = services.create_leave(self.conn, self.emp["id"], "wedding", "2026-09-07", "2026-09-09", False, None,
                                    self.cfg)
        services.review_leave(self.conn, lid, True)
        mid = services.create_leave(self.conn, self.emp["id"], "maternity", "2026-09-14", "2026-09-18", False,
                                    None, self.cfg)
        services.review_leave(self.conn, mid, True)
        row = services.monthly_report(self.conn, 2026, 9, self.cfg)[0]
        self.assertEqual((row["paid_leave"], row["unpaid_leave"], row["payable_days"]), (3, 5, 3))
        set_rule(self.conn, "leave_paid_maternity", 1)
        self.assertEqual(services.monthly_report(self.conn, 2026, 9, self.cfg)[0]["payable_days"], 8)


class EmailTest(Base):
    def setUp(self):
        super().setUp()
        c = self.conn
        c.execute("INSERT INTO departments (id, name) VALUES (1, 'KT')")
        c.execute("INSERT INTO employees (id, code, full_name, department_id, email) "
                  "VALUES (2, 'NV02', 'Trưởng', 1, 'boss@x.vn')")
        c.execute("UPDATE departments SET manager_id = 2")
        c.execute("UPDATE employees SET department_id = 1, email = 'nv@x.vn' WHERE id = 1")
        c.execute("INSERT INTO users (id, username, password_hash) VALUES (10, 'admin', 'x')")
        c.commit()
        notify.save_settings(c, {"enabled": "1", "host": "smtp.x.vn", "port": "587", "security": "starttls",
                                 "sender": "hrm@x.vn", "admin_email": "hr@x.vn",
                                 "base_url": "http://pi:5000/", **{f"event.{e}": "1" for e in notify.EVENTS}})
        self.sent = []

    def outbox(self):
        return self.conn.execute("SELECT * FROM email_outbox ORDER BY id").fetchall()

    def fake_send(self, settings, to, subject, body):
        self.sent.append((to, subject, body))

    def test_leave_flow_emails(self):
        lid = services.create_leave(self.conn, 1, "annual", "2026-10-12", "2026-10-12", False, "Việc nhà", self.cfg)
        self.assertEqual(notify.leave_created(self.conn, lid), 1)
        services.review_leave(self.conn, lid, True, "OK")
        notify.leave_reviewed(self.conn, lid)
        rows = self.outbox()
        self.assertEqual([r["recipient"] for r in rows], ["boss@x.vn", "nv@x.vn"])
        self.assertIn("http://pi:5000/leaves", rows[0]["body"])
        self.assertIn("được duyệt", rows[1]["subject"])
        # trưởng phòng gửi đơn -> không có cấp trên -> email quản trị
        lid = services.create_leave(self.conn, 2, "annual", "2026-10-13", "2026-10-13", False, None, self.cfg)
        notify.leave_created(self.conn, lid)
        self.assertEqual(self.outbox()[-1]["recipient"], "hr@x.vn")

    def test_outbox_retry_and_disabled_events(self):
        notify.timesheet_event(self.conn, "timesheet_sent", 1, "2026-09")
        sent, failed = notify.process_outbox(self.conn, sender=self.fake_send)
        self.assertEqual((sent, failed, self.outbox()[0]["status"]), (1, 0, "sent"))

        def broken(*_a):
            raise notify.MailError("timeout")
        notify.timesheet_event(self.conn, "timesheet_returned", 1, "2026-09", "Thiếu giờ ra")
        now = datetime(2030, 1, 1)
        for i in range(notify.MAX_ATTEMPTS):
            notify.process_outbox(self.conn, now=now.replace(hour=i * 2), sender=broken)
        row = self.outbox()[1]
        self.assertEqual((row["status"], row["attempts"], row["error"]), ("failed", 5, "timeout"))
        notify.retry_failed(self.conn)
        self.assertEqual(self.outbox()[1]["status"], "pending")

        s = {**notify.load_settings(self.conn), "event.timesheet_sent": ""}
        notify.save_settings(self.conn, s)
        self.assertEqual(notify.timesheet_event(self.conn, "timesheet_sent", 1, "2026-10"), 0)
        notify.save_settings(self.conn, {**s, "enabled": ""})
        self.assertEqual(notify.leave_created(self.conn, services.create_leave(
            self.conn, 1, "sick", "2026-10-14", "2026-10-14", False, None, self.cfg)), 0)

    def test_invalid_settings(self):
        base = notify.load_settings(self.conn)
        for bad in ({"port": "abc"}, {"sender": "khong-phai-email"}, {"security": "x"},
                    {"enabled": "1", "host": ""}, {"base_url": "pi:5000"}):
            with self.assertRaises(notify.MailError):
                notify.save_settings(self.conn, {**base, **bad})
        notify.save_settings(self.conn, {**base, "password": "bimat"})
        notify.save_settings(self.conn, {**base, "password": ""})  # để trống: giữ mật khẩu cũ
        self.assertEqual(notify.load_settings(self.conn)["password"], "bimat")


class Phase2WebTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({"DATABASE": str(Path(self.tmp.name) / "w.db"), "TESTING": True,
                               "HARDWARE_ENABLED": False, "PHOTO_DIR": str(Path(self.tmp.name) / "p")},
                              start_hardware=False)
        self.c = self.app.test_client()
        self.c.post("/login", data={"username": "admin", "password": "admin"})

    def tearDown(self):
        self.tmp.cleanup()

    def test_pages_and_forms(self):
        c = self.c
        r = c.post("/work-time/shifts", data=shift_form("Ca sáng", "06:00", "14:00", [0, 1, 2, 3, 4, 5],
                                                         lunch=("10:00", "10:30")), follow_redirects=True)
        self.assertIn("Ca sáng", r.data.decode())
        r = c.post("/work-time/default", data=shift_form("", "17:00", "08:00", [0]), follow_redirects=True)
        self.assertIn("Giờ ra phải sau giờ vào", r.data.decode())
        c.post("/departments", data={"name": "Kho", "shift_id": "1"})
        c.post("/departments", data={"id": "1", "name": "Kho"})  # form không có ô ca: giữ nguyên ca
        c.post("/employees/new", data={"code": "NV01", "full_name": "A", "department_id": "1", "status": "active"})
        page = c.get("/employees/1").data.decode()
        self.assertIn("Ca sáng · 06:00–14:00 · T2–T7", page)
        r = c.post("/employees/1/leave-adjust", data={"days": "2", "note": "Thưởng"}, follow_redirects=True)
        self.assertIn("Thưởng", r.data.decode())
        r = c.post("/leave-rules", data={"leave_accrual": "month", "leave_carry_max": "5",
                                         "leave_carry_expiry": "13-45"}, follow_redirects=True)
        self.assertIn("tháng-ngày", r.data.decode())
        r = c.post("/settings/email", data={"enabled": "1", "host": "", "port": "587", "security": "starttls"},
                   follow_redirects=True)
        self.assertIn("Cần nhập máy chủ SMTP", r.data.decode())
        r = c.post("/settings/email/test", data={"to": "x"}, follow_redirects=True)
        self.assertIn("Gửi thử thất bại", r.data.decode())
        for url in ("/work-time", "/work-time?edit=1", "/leave-rules", "/settings/email", "/departments",
                    "/employees/1/edit", "/leaves/new", "/report"):
            self.assertEqual(c.get(url).status_code, 200, url)


if __name__ == "__main__":
    unittest.main()
