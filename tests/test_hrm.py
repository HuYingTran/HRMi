"""Chạy: env/bin/python -m unittest discover tests"""
import tempfile
import time
import unittest
from datetime import date, datetime
from pathlib import Path

from hrm import create_app, services, timesheet
from hrm.db import connect, init_db
from hrm.config import Config

CFG = {k: getattr(Config, k) for k in dir(Config) if k.isupper()}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "t.db")
        self.cfg = {**CFG, "DATABASE": self.db_path}
        self.conn = init_db(self.db_path)
        self.conn.execute("INSERT INTO employees (code, full_name, annual_leave_days, rfid_uid, "
                          "fingerprint_id) VALUES ('NV01', 'Nguyễn Văn A', 2, 'AABBCCDD', 1)")
        self.conn.commit()
        self.emp = self.conn.execute("SELECT * FROM employees").fetchone()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()


class AttendanceTest(Base):
    def test_check_in_out_and_duplicate(self):
        r1 = services.record_scan(self.conn, self.emp, "rfid", self.cfg, now=datetime(2026, 10, 5, 8, 12))
        self.assertEqual(r1["type"], "check_in")
        self.assertEqual(r1["late_minutes"], 12)
        r2 = services.record_scan(self.conn, self.emp, "rfid", self.cfg, now=datetime(2026, 10, 5, 8, 12, 30))
        self.assertEqual(r2["type"], "duplicate")
        r3 = services.record_scan(self.conn, self.emp, "fingerprint", self.cfg, now=datetime(2026, 10, 5, 17, 30))
        self.assertEqual(r3["type"], "check_out")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM attendance_logs").fetchone()[0], 2)

    def test_manual_entry_later_in_day_does_not_block_real_scan(self):
        # quản lý nhập trước lượt thủ công 17:30; nhân viên quẹt thẻ lúc 07:55 vẫn phải được ghi
        services.record_scan(self.conn, self.emp, "manual", self.cfg, now=datetime(2026, 10, 5, 17, 30))
        r = services.record_scan(self.conn, self.emp, "rfid", self.cfg, now=datetime(2026, 10, 5, 7, 55))
        self.assertEqual(r["type"], "check_in")
        info = services.employee_period(self.conn, self.emp["id"], "2026-10-05", "2026-10-05", self.cfg)[0]
        self.assertEqual((info["first_in"].hour, info["last_out"].hour), (7, 17))

    def test_grace_period_not_late(self):
        r = services.record_scan(self.conn, self.emp, "rfid", self.cfg, now=datetime(2026, 10, 5, 8, 4))
        self.assertNotIn("late_minutes", r)

    def test_day_summary_excludes_lunch(self):
        info = services.summarize_day(
            date(2026, 10, 5), [datetime(2026, 10, 5, 8, 0), datetime(2026, 10, 5, 16, 30)],
            None, self.cfg, today=date(2026, 10, 6))
        self.assertEqual(info["hours"], 7.5)
        self.assertEqual(info["early_minutes"], 30)
        self.assertEqual(info["status"], "present")

    def test_missing_out_and_absent(self):
        past = date(2026, 10, 5)  # thứ Hai
        info = services.summarize_day(past, [datetime(2026, 10, 5, 8, 0)], None, self.cfg,
                                      today=date(2026, 10, 6))
        self.assertEqual(info["status"], "missing_out")
        self.assertEqual(services.summarize_day(past, [], None, self.cfg, today=date(2026, 10, 6))["status"], "absent")
        self.assertEqual(services.summarize_day(date(2026, 10, 4), [], None, self.cfg)["status"], "off")

    def test_monthly_report(self):
        services.record_scan(self.conn, self.emp, "rfid", self.cfg, now=datetime(2026, 9, 1, 8, 20))
        services.record_scan(self.conn, self.emp, "rfid", self.cfg, now=datetime(2026, 9, 1, 17, 0))
        row = services.monthly_report(self.conn, 2026, 9, self.cfg)[0]
        self.assertEqual(row["workdays"], 22)
        self.assertEqual(row["present"], 1)
        self.assertEqual(row["late"], 1)
        self.assertEqual(row["absent"], 21)
        self.assertEqual(row["hours"], 7.67)


    def test_presence_states(self):
        day = date(2026, 10, 5)
        pm = lambda: services.presence_map(self.conn, day).get(self.emp["id"], "absent")
        self.assertEqual(pm(), "absent")
        lid = services.create_leave(self.conn, self.emp["id"], "business", "2026-10-05", "2026-10-06",
                                    False, "gặp khách", self.cfg)
        services.review_leave(self.conn, lid, True)
        self.assertEqual(pm(), "business")
        services.record_scan(self.conn, self.emp, "rfid", self.cfg, now=datetime(2026, 10, 5, 8, 0))
        self.assertEqual(pm(), "in")  # lượt quét được ưu tiên hơn đơn
        services.record_scan(self.conn, self.emp, "rfid", self.cfg, now=datetime(2026, 10, 5, 12, 0))
        self.assertEqual(pm(), "out")
        services.record_scan(self.conn, self.emp, "rfid", self.cfg, now=datetime(2026, 10, 5, 13, 0))
        self.assertEqual(pm(), "in")

    def test_business_trip_is_not_absence(self):
        lid = services.create_leave(self.conn, self.emp["id"], "business", "2026-09-01", "2026-09-02",
                                    False, None, self.cfg)
        services.review_leave(self.conn, lid, True)
        row = services.monthly_report(self.conn, 2026, 9, self.cfg)[0]
        self.assertEqual((row["business"], row["leave_days"]), (2, 0))
        self.assertEqual(row["absent"], 20)
        self.assertEqual(services.leave_balance(self.conn, self.emp, 2026, self.cfg)["used"], 0)  # không trừ phép

    def test_weekend_work_is_ot(self):
        sat = datetime(2026, 10, 3, 8, 30)
        r = services.record_scan(self.conn, self.emp, "rfid", self.cfg, now=sat)
        self.assertTrue(r.get("ot"))
        self.assertNotIn("late_minutes", r)
        services.record_scan(self.conn, self.emp, "rfid", self.cfg, now=datetime(2026, 10, 3, 12, 30))
        info = services.employee_period(self.conn, self.emp["id"], "2026-10-03", "2026-10-03", self.cfg)[0]
        self.assertEqual((info["status"], info["hours"], info["late_minutes"]), ("ot", 3.5, 0))  # 8:30-12:30 trừ 30 phút nghỉ trưa
        row = services.monthly_report(self.conn, 2026, 10, self.cfg)[0]
        self.assertEqual((row["ot_days"], row["ot_hours"], row["present"]), (1, 3.5, 0))

    def test_days_before_hire_are_off(self):
        info = services.summarize_day(date(2026, 10, 5), [], None, self.cfg,
                                      today=date(2026, 10, 6), hire_date="2026-10-06")
        self.assertEqual(info["status"], "off")

    def test_trend_covers_calendar_days(self):
        services.record_scan(self.conn, self.emp, "rfid", self.cfg, now=datetime(2026, 10, 2, 8, 30))
        # T5 1/10 -> T2 5/10, "hôm nay" là CN 4/10
        trend = services.attendance_trend(self.conn, "2026-10-01", "2026-10-05", self.cfg,
                                          today=date(2026, 10, 4))
        self.assertEqual([t["date"][8:] for t in trend], ["01", "02", "03", "04", "05"])
        self.assertEqual([t["workday"] for t in trend], [True, True, False, False, True])
        self.assertEqual(trend[1]["late"], 1)
        self.assertEqual(trend[0]["absent"], 1)
        self.assertEqual(trend[2]["absent"], 0)  # thứ 7 không tính vắng
        self.assertTrue(trend[4]["future"])


class LeaveTest(Base):
    def test_days_skip_weekend(self):
        # Thứ Sáu 9/10 -> thứ Hai 12/10/2026 = 2 ngày làm việc
        lid = services.create_leave(self.conn, self.emp["id"], "annual", "2026-10-09", "2026-10-12",
                                    False, None, self.cfg)
        row = self.conn.execute("SELECT days FROM leave_requests WHERE id = ?", (lid,)).fetchone()
        self.assertEqual(row["days"], 2)

    def test_balance_and_overlap(self):
        services.create_leave(self.conn, self.emp["id"], "annual", "2026-10-13", "2026-10-13",
                              True, None, self.cfg)
        with self.assertRaises(services.ServiceError):  # trùng ngày
            services.create_leave(self.conn, self.emp["id"], "sick", "2026-10-13", "2026-10-14",
                                  False, None, self.cfg)
        with self.assertRaises(services.ServiceError):  # vượt định mức 2 ngày (đã giữ 0.5)
            services.create_leave(self.conn, self.emp["id"], "annual", "2026-10-19", "2026-10-20",
                                  False, None, self.cfg)
        bal = services.leave_balance(self.conn, self.emp, 2026, self.cfg)
        self.assertEqual((bal["pending"], bal["available"]), (0.5, 1.5))

    def test_approve_marks_day_as_leave(self):
        lid = services.create_leave(self.conn, self.emp["id"], "sick", "2026-10-05", "2026-10-05",
                                    False, "sốt", self.cfg)
        services.review_leave(self.conn, lid, True)
        with self.assertRaises(services.ServiceError):
            services.review_leave(self.conn, lid, False)
        rows = services.employee_period(self.conn, self.emp["id"], "2026-10-05", "2026-10-05", self.cfg)
        self.assertEqual(rows[0]["status"], "leave")


class TimesheetTest(Base):
    def setUp(self):
        super().setUp()
        c = self.conn
        c.execute("INSERT INTO departments (id, name) VALUES (1, 'Kỹ thuật')")
        c.execute("INSERT INTO employees (id, code, full_name, department_id) VALUES (2, 'NV02', 'Trưởng', 1)")
        c.execute("UPDATE employees SET department_id = 1 WHERE id = 1")
        c.execute("UPDATE departments SET manager_id = 2 WHERE id = 1")
        c.execute("INSERT INTO users (id, username, password_hash, role) VALUES (10, 'admin', 'x', 'admin')")
        c.execute("INSERT INTO users (id, username, password_hash, role, employee_id) "
                  "VALUES (11, 'nv02', 'x', 'employee', 2)")
        c.commit()
        self.emp = c.execute("SELECT * FROM employees WHERE id = 1").fetchone()
        self.manager = c.execute("SELECT * FROM users WHERE id = 11").fetchone()
        self.admin = c.execute("SELECT * FROM users WHERE id = 10").fetchone()
        self.today = date(2026, 10, 6)

    def test_reviewer_is_department_manager(self):
        self.assertEqual(timesheet.reviewer_id(self.conn, self.emp), 2)
        boss = self.conn.execute("SELECT * FROM employees WHERE id = 2").fetchone()
        self.assertIsNone(timesheet.reviewer_id(self.conn, boss))  # trưởng phòng cao nhất -> admin
        self.assertEqual(timesheet.subordinate_ids(self.conn, 2), {1})

    def test_full_workflow(self):
        c, cfg = self.conn, self.cfg
        services.record_scan(c, self.emp, "rfid", cfg, now=datetime(2026, 9, 1, 8, 0))  # quên quét ra
        timesheet.send(c, [1], "2026-09", today=self.today)
        ts = timesheet.get(c, 1, "2026-09")
        with self.assertRaises(services.ServiceError):  # cấp trên chưa chốt được khi NV chưa gửi
            timesheet.confirm(c, 1, "2026-09", self.manager, cfg, today=self.today)
        timesheet.explain(c, ts, "2026-09-01", "Quên quét khi về", None, "17:30")
        timesheet.submit(c, ts, "Nhờ anh duyệt")
        ts = timesheet.get(c, 1, "2026-09")
        with self.assertRaises(services.ServiceError):  # còn giải trình chờ xử lý
            timesheet.confirm(c, 1, "2026-09", self.manager, cfg, today=self.today)
        # trả lại -> NV sửa -> gửi lại
        timesheet.return_to_employee(c, ts, "Bổ sung giờ vào")
        ts = timesheet.get(c, 1, "2026-09")
        timesheet.explain(c, ts, "2026-09-01", "Quên quét khi về", "08:00", "17:30")
        timesheet.submit(c, ts)
        ts = timesheet.get(c, 1, "2026-09")
        timesheet.review_explanation(c, ts, "2026-09-01", True, "OK", cfg)
        day = services.employee_period(c, 1, "2026-09-01", "2026-09-01", cfg)[0]
        self.assertEqual((day["first_in"].strftime("%H:%M"), day["last_out"].strftime("%H:%M")), ("08:00", "17:30"))
        timesheet.confirm(c, 1, "2026-09", self.manager, cfg, today=self.today)
        ts = timesheet.get(c, 1, "2026-09")
        self.assertEqual((ts["status"], ts["data"]["present"], ts["confirmed_by"]), ("confirmed", 1, 11))
        with self.assertRaises(services.ServiceError):  # tháng đã chốt bị khoá
            services.create_leave(c, 1, "sick", "2026-09-03", "2026-09-03", False, None, cfg)
        timesheet.reopen(c, ts)
        services.create_leave(c, 1, "sick", "2026-09-03", "2026-09-03", False, None, cfg)

    def test_admin_can_confirm_directly_but_not_open_month(self):
        with self.assertRaises(services.ServiceError):
            timesheet.confirm(self.conn, 1, "2026-10", self.admin, self.cfg, today=self.today, force=True)
        timesheet.confirm(self.conn, 1, "2026-09", self.admin, self.cfg, today=self.today, force=True)
        self.assertEqual(timesheet.get(self.conn, 1, "2026-09")["status"], "confirmed")

    def test_half_day_leave_with_presence_not_double_counted(self):
        lid = services.create_leave(self.conn, self.emp["id"], "annual", "2026-09-01", "2026-09-01",
                                    True, None, self.cfg)
        services.review_leave(self.conn, lid, True)
        services.record_scan(self.conn, self.emp, "rfid", self.cfg, now=datetime(2026, 9, 1, 13, 0))
        services.record_scan(self.conn, self.emp, "rfid", self.cfg, now=datetime(2026, 9, 1, 17, 0))
        row = services.monthly_report(self.conn, 2026, 9, self.cfg)[0]
        self.assertEqual(row["payable_days"], 1)


class PermissionTreeTest(unittest.TestCase):
    """Giám đốc (NV01) -> Kinh doanh (NV02 trưởng) -> Kho vận (NV03 trưởng, NV04 nhân viên)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({"DATABASE": str(Path(self.tmp.name) / "p.db"), "TESTING": True,
                               "HARDWARE_ENABLED": False, "PHOTO_DIR": str(Path(self.tmp.name) / "ph")},
                              start_hardware=False)
        conn = connect(self.app.config["DATABASE"])
        from werkzeug.security import generate_password_hash
        pw = generate_password_hash("pw")
        conn.executescript("""
            INSERT INTO departments (id, name) VALUES (1, 'BGĐ'), (2, 'Kinh doanh'), (3, 'Kho vận');
            UPDATE departments SET parent_id = 1 WHERE id = 2;
            UPDATE departments SET parent_id = 2 WHERE id = 3;
            INSERT INTO employees (id, code, full_name, department_id) VALUES
              (1, 'NV01', 'Giám đốc', 1), (2, 'NV02', 'TP Kinh doanh', 2),
              (3, 'NV03', 'TP Kho', 3), (4, 'NV04', 'Thủ kho', 3), (5, 'NV05', 'Sale', 2);
            UPDATE departments SET manager_id = 1 WHERE id = 1;
            UPDATE departments SET manager_id = 2 WHERE id = 2;
            UPDATE departments SET manager_id = 3 WHERE id = 3;
        """)
        for i in range(1, 6):
            conn.execute("INSERT INTO users (username, password_hash, role, employee_id) "
                         "VALUES (?, ?, 'employee', ?)", (f"nv0{i}", pw, i))
        conn.commit()
        self.conn = conn

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def login(self, user):
        c = self.app.test_client()
        c.post("/login", data={"username": user, "password": "pw"})
        return c

    def test_scope_is_whole_subtree(self):
        from hrm.permissions import team_ids
        self.assertEqual(team_ids(self.conn, 1), {2, 3, 4, 5})  # giám đốc: cả công ty trừ mình
        self.assertEqual(team_ids(self.conn, 2), {3, 4, 5})     # TP Kinh doanh: gồm cả nhánh Kho vận
        self.assertEqual(team_ids(self.conn, 3), {4})
        self.assertEqual(team_ids(self.conn, 4), set())

    def test_org_around_employee(self):
        org = timesheet.org_around(self.conn, 3)  # TP Kho
        self.assertEqual([e["id"] for e in org["chain"]], [1, 2])  # Giám đốc -> TP Kinh doanh
        self.assertEqual([e["id"] for e in org["subs"]], [4])
        org = timesheet.org_around(self.conn, 2)  # TP Kinh doanh: trưởng phòng con xếp trước
        self.assertEqual([e["id"] for e in org["subs"]], [3, 5])
        self.assertEqual(org["sub_counts"][3], 1)
        admin = self.app.test_client()
        admin.post("/login", data={"username": "admin", "password": "admin"})
        page = admin.get("/employees/3").data.decode()
        self.assertIn("Cấp trên trực tiếp", page)
        self.assertIn('data-search="NV04 Thủ kho Kho vận"', admin.get("/employees").data.decode())

    def test_manager_sees_only_team(self):
        c = self.login("nv03")
        page = c.get("/employees").data.decode()
        self.assertIn("Thủ kho", page)
        self.assertNotIn("Sale", page)
        self.assertEqual(c.get("/employees/4").status_code, 200)
        self.assertEqual(c.get("/employees/5").status_code, 403)
        self.assertTrue(c.get("/employees/3").headers["Location"].startswith("/me"))  # hồ sơ của mình
        self.assertEqual(c.get("/device").status_code, 302)       # trang quản trị
        self.assertEqual(c.get("/permissions").status_code, 302)

    def test_everyone_sees_own_profile(self):
        emp = self.login("nv04")
        page = emp.get("/me")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Thủ kho", page.data.decode())
        self.assertIn("Đổi mật khẩu", page.data.decode())
        self.assertNotIn("Xoá nhân viên", page.data.decode())
        self.assertTrue(emp.get("/employees/4").headers["Location"].startswith("/me"))
        self.assertIn("/my/timesheet", emp.get("/employees/5").headers["Location"])  # người khác: không quyền
        admin = self.app.test_client()
        admin.post("/login", data={"username": "admin", "password": "admin"})
        self.assertIn("/account", admin.get("/me").headers["Location"])  # admin không gắn nhân viên

    def test_leave_flow_by_tree(self):
        emp = self.login("nv04")
        self.assertEqual(emp.get("/employees").status_code, 302)  # nhân viên không có quyền nhóm
        emp.post("/leaves/new", data={"employee_id": "4", "leave_type": "annual",
                                      "start_date": "2026-12-01", "end_date": "2026-12-01"})
        self.assertEqual(emp.post("/leaves/new", data={"employee_id": "5", "leave_type": "annual",
                         "start_date": "2026-12-02", "end_date": "2026-12-02"}).status_code, 403)
        lid = self.conn.execute("SELECT id FROM leave_requests").fetchone()[0]
        self.assertEqual(emp.post(f"/leaves/{lid}/approve").status_code, 403)  # không tự duyệt
        self.assertEqual(self.login("nv05").post(f"/leaves/{lid}/approve").status_code, 403)
        self.login("nv02").post(f"/leaves/{lid}/approve")  # cấp trên 2 tầng duyệt được
        self.assertEqual(self.conn.execute("SELECT status FROM leave_requests").fetchone()[0], "approved")

    def test_matrix_can_revoke_manager_permission(self):
        admin = self.app.test_client()
        admin.post("/login", data={"username": "admin", "password": "admin"})
        on = [f"manager:{k}" for k in ("employees.view", "attendance.view", "timesheets.review", "self.leave")]
        admin.post("/permissions", data={"perm": on + ["employee:self.leave"]})
        c = self.login("nv03")
        self.assertEqual(c.get("/employees/4").status_code, 200)
        self.assertEqual(c.post("/attendance/manual", data={"employee_id": "4", "date": "2026-09-01",
                                                            "time": "08:00"}).status_code, 302)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM attendance_logs").fetchone()[0], 0)
        self.assertIn("Phân quyền".encode(), admin.get("/permissions").data)


class FakeRFID:
    firmware = "fake"

    def __init__(self, uids):
        self.uids = list(uids)

    def read_uid(self, timeout=0.2):
        time.sleep(0.01)
        return self.uids.pop(0) if self.uids else None


class HardwareTest(Base):
    def _manager(self, uids):
        from hrm.hardware.manager import HardwareManager
        m = HardwareManager({**self.cfg, "HARDWARE_ENABLED": False})
        m.start()
        m.rfid = FakeRFID(uids)
        return m

    def _wait(self, cond, timeout=3):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_scan_known_and_unknown_card(self):
        m = self._manager(["AABBCCDD", "AABBCCDD", None, "11223344"])
        try:
            self.assertTrue(self._wait(lambda: len(m.events) >= 2))
            kinds = [(e["kind"], e.get("type")) for e in m.events]
            # thẻ giữ nguyên trên đầu đọc chỉ tính một lần
            self.assertEqual(kinds, [("scan", "check_in"), ("unknown", None)])
        finally:
            m.stop()

    def test_enroll_rfid(self):
        m = self._manager([])
        try:
            self.conn.execute("INSERT INTO employees (code, full_name) VALUES ('NV02', 'B')")
            self.conn.commit()
            emp_id = self.conn.execute("SELECT id FROM employees WHERE code='NV02'").fetchone()[0]
            m.request_enroll("rfid", emp_id)
            self.assertTrue(self._wait(lambda: m.task_for(emp_id)["state"] == "running"))
            m.rfid.uids = ["AABBCCDD"]  # thẻ của NV01 -> báo trùng
            self.assertTrue(self._wait(lambda: m.task_for(emp_id)["state"] == "error"))
            self.assertIn("NV01", m.task_for(emp_id)["message"])
            m.request_enroll("rfid", emp_id)
            self.assertTrue(self._wait(lambda: m.task_for(emp_id)["state"] == "running"))
            m.rfid.uids = ["DEADBEEF"]
            self.assertTrue(self._wait(lambda: m.task_for(emp_id)["state"] == "done"))
            uid = connect(self.db_path).execute("SELECT rfid_uid FROM employees WHERE id=?", (emp_id,)).fetchone()[0]
            self.assertEqual(uid, "DEADBEEF")
        finally:
            m.stop()


class WebTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.photo_dir = Path(self.tmp.name) / "photos"
        self.app = create_app({"DATABASE": str(Path(self.tmp.name) / "w.db"), "TESTING": True,
                               "HARDWARE_ENABLED": False, "PHOTO_DIR": str(self.photo_dir)},
                              start_hardware=False)
        self.c = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_flow(self):
        c = self.c
        self.assertEqual(c.get("/").status_code, 302)
        r = c.post("/login", data={"username": "admin", "password": "admin"})
        self.assertEqual(r.status_code, 302)

        c.post("/departments", data={"name": "Kỹ thuật"})
        c.post("/departments", data={"name": "Phần mềm", "parent_id": "1"})
        r = c.post("/departments", data={"id": "1", "name": "Kỹ thuật", "parent_id": "2"},
                   follow_redirects=True)  # cha không được là con của chính nó
        self.assertIn("Không thể chọn phòng ban con".encode(), r.data)
        r = c.post("/employees/new", data={"code": "NV01", "full_name": "Trần Thị B",
                                           "department_id": "1", "status": "active",
                                           "annual_leave_days": "12", "rfid_uid": "aa bb cc dd"})
        self.assertEqual(r.status_code, 302)
        r = c.post("/employees/new", data={"code": "NV01", "full_name": "Trùng mã", "status": "active"})
        self.assertIn("Mã nhân viên đã tồn tại".encode(), r.data)

        today = date.today().isoformat()
        c.post("/attendance/manual", data={"employee_id": "1", "date": today, "time": "00:00"})
        self.assertIn(b'class="presence in"', c.get("/employees").data)
        c.post("/leaves/new", data={"employee_id": "1", "leave_type": "annual",
                                    "start_date": "2026-12-01", "end_date": "2026-12-02"})
        c.post("/leaves/1/approve", data={})

        for url in ("/", "/employees", "/employees/1", "/employees/1/edit", "/employees/new",
                    "/departments", "/attendance", f"/attendance?date={today}", "/report",
                    "/report?month=2026-12", "/leaves", "/leaves?status=all", "/leaves/new",
                    "/device", "/kiosk", "/account", "/api/events"):
            r = c.get(url)
            self.assertEqual(r.status_code, 200, url)

        self.assertIn(b"AABBCCDD", c.get("/employees/1").data)
        c.post("/departments", data={"id": "1", "name": "Kỹ thuật", "manager_id": "1"})
        page = c.get("/departments").data.decode()
        self.assertIn('class="org"', page)
        self.assertIn("Trần Thị B", page)
        c.post("/device/simulate", data={"employee_id": "1", "method": "fingerprint"})
        events = c.get("/api/events").get_json()["events"]
        self.assertEqual(events[-1]["type"], "check_out")  # đã có lượt thủ công lúc 00:00
        self.assertIn("Đã duyệt".encode(), c.get("/leaves?status=approved").data)
        self.assertEqual(c.get("/timesheets").status_code, 200)
        self.assertEqual(c.get("/timesheets?month=2026-12").status_code, 200)
        self.assertEqual(c.get("/timesheets/1/2026-09").status_code, 200)
        self.assertIn("Công tính lương", c.get("/timesheets.csv").data.decode("utf-8-sig"))

        # tài khoản nhân viên: chỉ vào được trang bảng công của mình
        r = c.post("/employees/1/account", data={"action": "create"}, follow_redirects=True)
        import re
        pw = re.search(r"mật khẩu: (\S+)</span>", r.data.decode()).group(1)
        c.post("/employees/new", data={"code": "NV02", "full_name": "Người Khác", "status": "active"})
        e = self.app.test_client()
        e.post("/login", data={"username": "nv01", "password": pw})
        self.assertIn("/my/timesheet", e.get("/employees").headers["Location"])
        self.assertEqual(e.get("/my/timesheet?month=2026-09").status_code, 200)
        self.assertEqual(e.get("/timesheets/1/2026-09").status_code, 200)
        self.assertEqual(e.get("/timesheets/2/2026-09").status_code, 403)
        self.assertEqual(e.get("/api/employees/1/enroll").status_code, 403)
        csv = c.get("/report.csv?month=2026-12").data.decode("utf-8-sig")
        self.assertIn("NV01,Trần Thị B,Kỹ thuật,23,0,", csv)


class PhotoTest(WebTest):
    def test_upload_replace_remove(self):
        import io
        from PIL import Image
        c = self.c
        c.post("/login", data={"username": "admin", "password": "admin"})

        def png(w, h):
            buf = io.BytesIO()
            Image.new("RGB", (w, h), (200, 30, 30)).save(buf, "PNG")
            buf.seek(0)
            return buf

        base = {"code": "NV09", "full_name": "Ảnh Thử", "status": "active"}
        c.post("/employees/new", data={**base, "photo": (png(1200, 800), "a.png")},
               content_type="multipart/form-data")
        files = list(self.photo_dir.glob("*.jpg"))
        self.assertEqual(len(files), 1)
        self.assertEqual(Image.open(files[0]).size, (512, 512))  # đã cắt vuông + thu nhỏ
        page = c.get("/employees/1").data.decode()
        self.assertIn(f"/photos/{files[0].name}", page)
        self.assertEqual(c.get(f"/photos/{files[0].name}").status_code, 200)

        # file không phải ảnh -> báo lỗi, giữ ảnh cũ
        r = c.post("/employees/1/edit", data={**base, "photo": (io.BytesIO(b"xx"), "x.png")},
                   content_type="multipart/form-data", follow_redirects=True)
        self.assertIn("không phải ảnh".encode(), r.data)
        self.assertEqual(list(self.photo_dir.glob("*.jpg")), files)

        # thay ảnh -> file cũ bị xoá
        c.post("/employees/1/edit", data={**base, "photo": (png(300, 300), "b.png")},
               content_type="multipart/form-data")
        new = list(self.photo_dir.glob("*.jpg"))
        self.assertEqual(len(new), 1)
        self.assertNotEqual(new, files)

        c.post("/employees/1/edit", data={**base, "remove_photo": "1"})
        self.assertEqual(list(self.photo_dir.glob("*.jpg")), [])

    test_full_flow = None  # không chạy lại test của lớp cha


if __name__ == "__main__":
    unittest.main()
