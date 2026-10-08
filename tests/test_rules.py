"""Ngày lễ, hệ số làm thêm giờ, đơn trong ngày. Chạy: env/bin/python -m unittest discover tests"""
import re
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from hrm import create_app, day_requests, services, timesheet, workrules
from hrm.calendar_vn import lunar_to_solar, suggested_holidays
from hrm.services import ServiceError
from hrm.workrules import RuleError

from test_hrm import Base


def set_rule(conn, key, value):
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE "
                 "SET value = excluded.value", (f"rule.{key}", str(value)))
    conn.commit()


def scan(conn, emp, cfg, *stamps):
    for ts in stamps:
        services.record_scan(conn, emp, "rfid", cfg, now=ts)


class LunarTest(unittest.TestCase):
    def test_known_dates(self):
        self.assertEqual(lunar_to_solar(1, 1, 2024), date(2024, 2, 10))
        self.assertEqual(lunar_to_solar(1, 1, 2025), date(2025, 1, 29))
        self.assertEqual(lunar_to_solar(1, 1, 2026), date(2026, 2, 17))
        self.assertEqual(lunar_to_solar(10, 3, 2025), date(2025, 4, 7))   # Giỗ Tổ
        self.assertEqual(lunar_to_solar(10, 3, 2026), date(2026, 4, 26))

    def test_suggested_with_compensation(self):
        days = dict(suggested_holidays(2026, [0, 1, 2, 3, 4]))
        self.assertEqual(len(days), 12)  # 11 ngày lễ + 1 ngày nghỉ bù
        self.assertIn("Giỗ Tổ", days[date(2026, 4, 26)])          # Chủ nhật
        self.assertIn("Nghỉ bù", days[date(2026, 4, 27)])         # -> nghỉ bù thứ Hai
        self.assertIn(date(2026, 2, 16), days)                     # 30 Tết
        self.assertIn(date(2026, 9, 1), days)


class HolidayTest(Base):
    def holiday(self, day, name="Lễ", kind="holiday"):
        workrules.save_holiday(self.conn, day, name, kind, self.cfg)

    def test_national_day_is_paid_not_absent(self):
        self.holiday("2026-09-01")
        self.holiday("2026-09-02")
        row = services.monthly_report(self.conn, 2026, 9, self.cfg)[0]
        self.assertEqual((row["workdays"], row["holidays"]), (22, 2))  # công chuẩn gồm ngày lễ
        self.assertEqual((row["absent"], row["payable_days"]), (20, 2))
        info = services.employee_period(self.conn, self.emp["id"], "2026-09-02", "2026-09-02", self.cfg)[0]
        self.assertEqual((info["status"], info["holiday"]["name"]), ("holiday", "Lễ"))

    def test_work_on_holiday_is_ot_300(self):
        self.holiday("2026-09-02")
        scan(self.conn, self.emp, self.cfg, datetime(2026, 9, 2, 8, 0), datetime(2026, 9, 2, 12, 0))
        info = services.employee_period(self.conn, self.emp["id"], "2026-09-02", "2026-09-02", self.cfg)[0]
        self.assertEqual((info["status"], info["ot_kind"], info["ot_hours"], info["ot_weighted"]),
                         ("ot", "holiday", 4, 12))
        row = services.monthly_report(self.conn, 2026, 9, self.cfg)[0]
        self.assertEqual((row["ot_holiday_hours"], row["holidays"], row["present"]), (4, 1, 0))
        self.assertEqual(row["payable_days"], 1)  # vẫn hưởng lương ngày lễ, OT tính riêng

    def test_leave_skips_holiday_and_is_recounted(self):
        self.holiday("2026-09-02")
        lid = services.create_leave(self.conn, self.emp["id"], "annual", "2026-08-31", "2026-09-02",
                                    False, None, self.cfg)  # T2 -> T4, T4 là lễ
        days = lambda: self.conn.execute("SELECT days FROM leave_requests WHERE id = ?", (lid,)).fetchone()[0]
        self.assertEqual(days(), 2)
        self.holiday("2026-09-01")  # thêm lễ sau khi đã có đơn -> đơn được tính lại
        self.assertEqual(days(), 1)
        workrules.delete_holiday(self.conn, "2026-09-01", self.cfg)
        self.assertEqual(days(), 2)

    def test_makeup_and_swapped_day(self):
        self.holiday("2026-10-10", "Làm bù", "makeup")      # thứ 7 đi làm
        self.holiday("2026-10-16", "Nghỉ đổi", "off")       # thứ 6 được nghỉ
        row = services.monthly_report(self.conn, 2026, 10, self.cfg)[0]
        self.assertEqual(row["workdays"], 22)                # 22 + 1 - 1
        scan(self.conn, self.emp, self.cfg, datetime(2026, 10, 10, 8, 20), datetime(2026, 10, 10, 17, 0))
        info = services.employee_period(self.conn, self.emp["id"], "2026-10-10", "2026-10-10", self.cfg)[0]
        self.assertEqual((info["status"], info["late_minutes"], info["ot_hours"]), ("late", 20, 0))
        with self.assertRaises(RuleError):  # làm bù phải là ngày nghỉ hằng tuần
            self.holiday("2026-10-12", "x", "makeup")

    def test_suggest_and_locked_month(self):
        self.conn.execute("INSERT INTO timesheets (employee_id, month, status) VALUES (?, '2026-09', 'confirmed')",
                          (self.emp["id"],))
        self.conn.commit()
        added, skipped = workrules.load_suggested(self.conn, 2026, self.cfg)
        self.assertEqual((added, skipped), (10, [date(2026, 9, 1), date(2026, 9, 2)]))  # tháng 9 đã chốt
        self.assertEqual(workrules.load_suggested(self.conn, 2026, self.cfg)[0], 0)
        with self.assertRaises(RuleError):
            workrules.save_holiday(self.conn, "2026-09-02", "Quốc khánh", "holiday", self.cfg)
        with self.assertRaises(RuleError):
            workrules.delete_holiday(self.conn, "2026-09-15", self.cfg)


class OvertimeTest(Base):
    def day(self, iso):
        return services.employee_period(self.conn, self.emp["id"], iso, iso, self.cfg)[0]

    def test_weekday_ot_needs_approved_request_by_default(self):
        scan(self.conn, self.emp, self.cfg, datetime(2026, 10, 5, 8, 0), datetime(2026, 10, 5, 19, 0))
        d = self.day("2026-10-05")
        self.assertEqual((d["hours"], d["ot_hours"], d["ot_pending_hours"]), (8, 0, 2))  # giờ công trong ca
        self.assertIn("OT chưa duyệt 2h",
                      services.issues_of(services.monthly_report(self.conn, 2026, 10, self.cfg)[0]))
        rid = day_requests.create(self.conn, self.emp["id"], "overtime", "2026-10-05", "17:00", "18:30",
                                  "Chạy dự án", self.cfg)
        day_requests.review(self.conn, rid, True, None, self.cfg)
        d = self.day("2026-10-05")
        self.assertEqual((d["ot_hours"], d["ot_pending_hours"], d["ot_weighted"]), (1.5, 0, 2.25))
        row = services.monthly_report(self.conn, 2026, 10, self.cfg)[0]
        self.assertEqual((row["ot_weekday_hours"], row["ot_days"], row["present"]), (1.5, 1, 1))

    def test_auto_ot_threshold(self):
        set_rule(self.conn, "ot_approval", "none")
        scan(self.conn, self.emp, self.cfg, datetime(2026, 10, 5, 8, 0), datetime(2026, 10, 5, 17, 20))
        self.assertEqual(self.day("2026-10-05")["ot_hours"], 0)       # ở lại 20 phút < 30
        scan(self.conn, self.emp, self.cfg, datetime(2026, 10, 6, 8, 0), datetime(2026, 10, 6, 17, 45))
        self.assertEqual(self.day("2026-10-06")["ot_hours"], 0.75)

    def test_weekend_night_hours_and_rates(self):
        set_rule(self.conn, "ot_weekend", 210)
        scan(self.conn, self.emp, self.cfg, datetime(2026, 10, 3, 18, 0), datetime(2026, 10, 3, 23, 30))
        d = self.day("2026-10-03")
        self.assertEqual((d["status"], d["ot_hours"], d["ot_night_hours"]), ("ot", 5.5, 1.5))
        self.assertEqual(d["ot_weighted"], round((5.5 * 210 + 1.5 * 30) / 100, 2))

    def test_weekend_needs_request_when_rule_all(self):
        set_rule(self.conn, "ot_approval", "all")
        scan(self.conn, self.emp, self.cfg, datetime(2026, 10, 3, 8, 0), datetime(2026, 10, 3, 17, 0))
        d = self.day("2026-10-03")
        self.assertEqual((d["ot_hours"], d["ot_pending_hours"]), (0, 8))
        rid = day_requests.create(self.conn, self.emp["id"], "overtime", "2026-10-03", "08:00", "12:00",
                                  "Trực", self.cfg)
        day_requests.review(self.conn, rid, True, None, self.cfg)
        self.assertEqual(self.day("2026-10-03")["ot_hours"], 4)

    def test_limits(self):
        set_rule(self.conn, "ot_limit_month", 3)
        scan(self.conn, self.emp, self.cfg, datetime(2026, 10, 3, 8, 0), datetime(2026, 10, 3, 12, 0))
        rows = services.monthly_report(self.conn, 2026, 10, self.cfg)
        msgs = services.ot_limits(self.conn, 2026, 10, rows, self.cfg)[self.emp["id"]]
        self.assertEqual(msgs, ["Vượt trần OT tháng (4/3h)"])

    def test_invalid_rule_rejected(self):
        form = {k: str(v[1]) for k, v in workrules.RULES.items()}
        workrules.save_rules(self.conn, form)
        with self.assertRaises(RuleError):
            workrules.save_rules(self.conn, {**form, "ot_weekday": "90"})
        with self.assertRaises(RuleError):
            workrules.save_rules(self.conn, {**form, "ot_approval": "x"})


class DayRequestTest(Base):
    def test_late_request_excuses_late_minutes(self):
        scan(self.conn, self.emp, self.cfg, datetime(2026, 10, 5, 8, 30), datetime(2026, 10, 5, 17, 0))
        rid = day_requests.create(self.conn, self.emp["id"], "late", "2026-10-05", "08:30", None,
                                  "Đưa con đi khám", self.cfg)
        self.assertEqual(services.monthly_report(self.conn, 2026, 10, self.cfg)[0]["late"], 1)  # chưa duyệt
        day_requests.review(self.conn, rid, True, None, self.cfg)
        row = services.monthly_report(self.conn, 2026, 10, self.cfg)[0]
        self.assertEqual((row["late"], row["late_minutes"], row["excused"]), (0, 0, 1))
        d = services.employee_period(self.conn, self.emp["id"], "2026-10-05", "2026-10-05", self.cfg)[0]
        self.assertEqual((d["status"], d["excused"]), ("present", ["late"]))

    def test_forgot_adds_and_cancel_removes_logs(self):
        today = date(2026, 10, 6)
        rid = day_requests.create(self.conn, self.emp["id"], "forgot", "2026-10-05", "08:00", "17:30",
                                  "Quên thẻ", self.cfg, today=today)
        day_requests.review(self.conn, rid, True, None, self.cfg)
        d = services.employee_period(self.conn, self.emp["id"], "2026-10-05", "2026-10-05", self.cfg)[0]
        self.assertEqual((d["first_in"].hour, d["last_out"].hour, d["status"]), (8, 17, "present"))
        day_requests.cancel(self.conn, rid)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM attendance_logs").fetchone()[0], 0)

    def test_validation(self):
        create = lambda *a, **k: day_requests.create(self.conn, self.emp["id"], *a, cfg=self.cfg, **k)
        with self.assertRaises(ServiceError):
            create("overtime", "2026-10-05", "18:00", None, "x")             # thiếu giờ kết thúc
        with self.assertRaises(ServiceError):
            create("overtime", "2026-10-05", "18:00", "17:00", "x")          # kết thúc trước bắt đầu
        with self.assertRaises(ServiceError):
            create("forgot", "2026-10-05", None, None, "x")                  # thiếu giờ
        with self.assertRaises(ServiceError):
            create("forgot", "2026-10-09", "08:00", None, "x", today=date(2026, 10, 6))  # ngày tương lai
        with self.assertRaises(ServiceError):
            create("late", "2026-10-05", None, None, "")                     # thiếu lý do
        create("late", "2026-10-05", None, None, "x")
        with self.assertRaises(ServiceError):
            create("late", "2026-10-05", None, None, "x")                    # trùng
        set_rule(self.conn, "req_limit_month", 2)
        create("early", "2026-10-06", None, "16:00", "x")
        with self.assertRaises(ServiceError):
            create("late", "2026-10-07", None, None, "x")                    # hết lượt trong tháng
        create("late", "2026-11-02", None, None, "x")                        # tháng khác vẫn được

    def test_locked_month(self):
        self.conn.execute("INSERT INTO users (id, username, password_hash) VALUES (10, 'a', 'x')")
        self.conn.commit()
        admin = self.conn.execute("SELECT * FROM users WHERE id = 10").fetchone()
        rid = day_requests.create(self.conn, self.emp["id"], "late", "2026-09-01", None, None, "x", self.cfg)
        timesheet.confirm(self.conn, self.emp["id"], "2026-09", admin, self.cfg,
                          today=date(2026, 10, 6), force=True)
        for action in (lambda: day_requests.review(self.conn, rid, True, admin, self.cfg),
                       lambda: day_requests.cancel(self.conn, rid),
                       lambda: day_requests.create(self.conn, self.emp["id"], "early", "2026-09-02",
                                                   None, None, "x", self.cfg)):
            with self.assertRaises(ServiceError):
                action()


class RulesWebTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({"DATABASE": str(Path(self.tmp.name) / "w.db"), "TESTING": True,
                               "HARDWARE_ENABLED": False, "PHOTO_DIR": str(Path(self.tmp.name) / "p")},
                              start_hardware=False)
        self.c = self.app.test_client()
        self.c.post("/login", data={"username": "admin", "password": "admin"})

    def tearDown(self):
        self.tmp.cleanup()

    def test_admin_pages(self):
        c = self.c
        self.assertEqual(c.get("/work-rules").status_code, 200)
        r = c.post("/work-rules/holidays/suggest", data={"year": "2026"}, follow_redirects=True)
        self.assertIn("Giỗ Tổ Hùng Vương", r.data.decode())
        r = c.post("/work-rules/holidays", data={"year": "2026", "day": "2026-12-24", "name": "Noel",
                                                 "kind": "holiday"}, follow_redirects=True)
        self.assertIn("Noel", r.data.decode())
        r = c.post("/work-rules/holidays/2026-12-24/delete", data={"year": "2026"}, follow_redirects=True)
        self.assertNotIn("Noel", r.data.decode())
        form = {k: str(v[1]) for k, v in workrules.RULES.items()}
        r = c.post("/work-rules/ot", data={**form, "ot_holiday": "abc"}, follow_redirects=True)
        self.assertIn("hãy nhập số nguyên", r.data.decode())
        r = c.post("/work-rules/ot", data={**form, "ot_holiday": "400"}, follow_redirects=True)
        self.assertIn('value="400"', r.data.decode())
        for url in ("/requests", "/requests?status=all", "/requests/new", "/report?month=2026-09",
                    "/report.csv?month=2026-09", "/employees", "/"):
            self.assertEqual(c.get(url).status_code, 200, url)

    def test_employee_creates_request_manager_approves(self):
        c = self.c
        c.post("/departments", data={"name": "Kỹ thuật"})
        for code, name in (("NV01", "Nhân viên"), ("NV02", "Trưởng phòng")):
            c.post("/employees/new", data={"code": code, "full_name": name, "department_id": "1",
                                           "status": "active", "hire_date": "2026-01-01"})
        c.post("/departments", data={"id": "1", "name": "Kỹ thuật", "manager_id": "2"})
        clients = {}
        for emp_id, user in ((1, "nv01"), (2, "nv02")):
            r = c.post(f"/employees/{emp_id}/account", data={"action": "create"}, follow_redirects=True)
            pw = re.search(r"mật khẩu: (\S+)</span>", r.data.decode()).group(1)
            clients[user] = self.app.test_client()
            clients[user].post("/login", data={"username": user, "password": pw})
        emp, mgr = clients["nv01"], clients["nv02"]
        self.assertEqual(emp.get("/requests/new").status_code, 200)
        r = emp.post("/requests/new", data={"employee_id": "1", "req_type": "overtime", "day": "2026-10-05",
                                            "time_from": "17:00", "time_to": "19:00", "reason": "Dự án"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(emp.post("/requests/new", data={"employee_id": "2", "req_type": "late",
                                                         "day": "2026-10-05", "reason": "x"}).status_code, 403)
        self.assertEqual(emp.post("/requests/1/approve").status_code, 403)  # không tự duyệt
        self.assertIn("Dự án", mgr.get("/requests").data.decode())
        mgr.post("/requests/1/approve", data={"note": "OK"})
        with self.app.app_context():
            from hrm.db import get_db
            status = get_db().execute("SELECT status FROM attendance_requests WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "approved")
        self.assertEqual(emp.get("/work-rules").status_code, 302)  # chỉ admin


if __name__ == "__main__":
    unittest.main()
