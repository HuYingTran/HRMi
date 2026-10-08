"""Hồ sơ nhân sự, hợp đồng, quá trình công tác, nghỉ việc. Chạy: env/bin/python -m unittest discover tests"""
import io
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from werkzeug.security import generate_password_hash

from hrm import create_app, notify, profiles, services
from hrm.db import connect
from hrm.services import ServiceError

from test_hrm import Base
from test_rules import scan

TODAY = date(2026, 10, 8)


def contract(conn, emp_id, ctype, start, end=None, salary="10.000.000", **extra):
    return profiles.save_contract(conn, emp_id, {"type": ctype, "start_date": start, "end_date": end or "",
                                                 "salary": salary, **extra})


class MoneyTest(unittest.TestCase):
    def test_parse_and_words(self):
        self.assertEqual(profiles.parse_money("10.500.000"), 10500000)
        self.assertEqual(profiles.parse_money("10,500,000 đ"), 10500000)
        self.assertIsNone(profiles.parse_money(" "))
        with self.assertRaises(ServiceError):
            profiles.parse_money("10tr")
        self.assertEqual(profiles.money(10500000), "10.500.000")
        self.assertEqual(profiles.money_words(10500000), "Mười triệu năm trăm nghìn đồng")
        self.assertEqual(profiles.money_words(1005000), "Một triệu không trăm linh năm nghìn đồng")
        self.assertEqual(profiles.money_words(21000), "Hai mươi mốt nghìn đồng")
        self.assertEqual(profiles.money_words(15000000), "Mười lăm triệu đồng")


class ContractTest(Base):
    def test_validation(self):
        eid = self.emp["id"]
        with self.assertRaises(ServiceError):  # quá 36 tháng
            contract(self.conn, eid, "fixed", "2026-01-01", "2029-01-01")
        with self.assertRaises(ServiceError):  # thử việc quá 180 ngày
            contract(self.conn, eid, "probation", "2026-01-01", "2026-07-15")
        with self.assertRaises(ServiceError):  # thiếu ngày kết thúc
            contract(self.conn, eid, "fixed", "2026-01-01")
        with self.assertRaises(ServiceError):  # thiếu lương
            contract(self.conn, eid, "indefinite", "2026-01-01", salary="")
        cid, _ = contract(self.conn, eid, "fixed", "2026-01-01", "2028-12-31",
                          allowances="Ăn trưa: 730.000\nXăng xe: 500000")
        c = profiles.get_contract(self.conn, cid, TODAY)
        self.assertEqual((c["number"], c["state"], c["insurance_salary"]), ("01/2026/HĐLĐ", "active", 10000000))
        self.assertEqual(c["allowance_total"], 1230000)
        with self.assertRaises(ServiceError):  # trùng thời gian
            contract(self.conn, eid, "indefinite", "2027-01-01")
        with self.assertRaises(ServiceError):
            profiles.save_contract(self.conn, eid, {"type": "seasonal", "start_date": "2026-01-01",
                                                    "end_date": "2026-03-01", "salary": "1",
                                                    "allowances": "không có số tiền"})

    def test_states_salary_history_and_renewal_warning(self):
        eid = self.emp["id"]
        contract(self.conn, eid, "probation", "2026-01-01", "2026-02-28", salary="8.000.000")
        contract(self.conn, eid, "fixed", "2026-03-01", "2026-10-31", salary="10.000.000")
        states = [c["state"] for c in profiles.contracts_of(self.conn, eid, TODAY)]
        self.assertEqual(states, ["expiring", "expired"])
        h = profiles.history_of(self.conn, eid)
        self.assertEqual((h[0]["kind"], h[0]["from_value"], h[0]["to_value"]), ("salary", "8.000.000", "10.000.000"))
        contract(self.conn, eid, "fixed", "2026-11-01", "2027-10-31")
        _, warnings = contract(self.conn, eid, "fixed", "2027-11-01", "2028-10-31")
        self.assertEqual(len(warnings), 1)  # lần thứ 3 ký xác định thời hạn
        self.assertEqual(profiles.contracts_of(self.conn, eid, TODAY)[1]["state"], "upcoming")

    def test_terminate(self):
        cid, _ = contract(self.conn, self.emp["id"], "indefinite", "2026-01-01")
        with self.assertRaises(ServiceError):
            profiles.terminate_contract(self.conn, cid, "2025-12-31")
        profiles.terminate_contract(self.conn, cid, "2026-06-30")
        c = profiles.get_contract(self.conn, cid, TODAY)
        self.assertEqual((c["state"], c["terminated_on"]), ("terminated", "2026-06-30"))
        contract(self.conn, self.emp["id"], "indefinite", "2026-07-01")  # sau ngày chấm dứt: không trùng

    def test_alerts(self):
        self.conn.execute("INSERT INTO employees (code, full_name, dob) VALUES ('NV02', 'B', '1990-10-20'), "
                          "('NV03', 'C', '1991-03-02')")
        ids = [r[0] for r in self.conn.execute("SELECT id FROM employees ORDER BY id")]
        contract(self.conn, ids[0], "probation", "2026-09-01", "2026-10-31")
        contract(self.conn, ids[1], "fixed", "2025-10-01", "2026-09-30")
        a = profiles.hr_alerts(self.conn, TODAY)
        self.assertEqual([c["employee_id"] for c in a["expiring"]], [ids[0]])
        self.assertEqual(a["expiring"][0]["days_left"], 23)
        self.assertEqual([c["employee_id"] for c in a["expired"]], [ids[1]])
        self.assertEqual([e["id"] for e in a["no_contract"]], [ids[2]])
        self.assertEqual([e["id"] for e in a["birthdays"]], [ids[1]])
        contract(self.conn, ids[0], "fixed", "2026-11-01", "2027-10-31")  # đã ký tiếp: hết nhắc
        contract(self.conn, ids[1], "indefinite", "2026-10-01")
        a = profiles.hr_alerts(self.conn, TODAY)
        self.assertEqual((a["expiring"], a["expired"]), ([], []))

    def test_email_reminder_once(self):
        self.conn.execute("UPDATE employees SET email = 'a@x.vn'")
        self.conn.executemany("INSERT INTO settings (key, value) VALUES (?, ?)",
                              [("mail.enabled", "1"), ("mail.admin_email", "hr@x.vn")])
        self.conn.commit()
        contract(self.conn, self.emp["id"], "probation", "2026-09-01", "2026-10-31")
        self.assertEqual(notify.contract_reminders(self.conn, TODAY), 1)
        body = self.conn.execute("SELECT recipient, body FROM email_outbox").fetchone()
        self.assertEqual(body["recipient"], "hr@x.vn")
        self.assertIn("31/10/2026 (còn 23 ngày)", body["body"])
        self.assertEqual(notify.contract_reminders(self.conn, TODAY), 0)


class HistoryOffboardTest(Base):
    def setUp(self):
        super().setUp()
        self.conn.execute("INSERT INTO departments (id, name) VALUES (1, 'Kho'), (2, 'Kinh doanh')")
        self.conn.execute("UPDATE employees SET department_id = 1, position = 'Thủ kho', hire_date = '2025-01-01'")
        self.conn.commit()

    def cur(self):
        return self.conn.execute("SELECT * FROM employees").fetchone()

    def test_decisions(self):
        profiles.record_decision(self.conn, self.cur(), {"kind": "transfer", "effective_date": "2026-01-01",
                                                         "department_id": "2", "position": "Sale"})
        emp = self.cur()
        self.assertEqual((emp["department_id"], emp["position"]), (2, "Sale"))
        h = profiles.history_of(self.conn, emp["id"])[0]
        self.assertEqual((h["from_value"], h["to_value"]), ("Kho", "Kinh doanh · Sale"))
        profiles.record_decision(self.conn, emp, {"kind": "promotion", "effective_date": "2099-01-01",
                                                  "position": "Trưởng nhóm"})
        self.assertEqual(self.cur()["position"], "Sale")  # ngày hiệu lực tương lai: chưa áp dụng
        with self.assertRaises(ServiceError):
            profiles.record_decision(self.conn, emp, {"kind": "transfer", "effective_date": "2026-01-01",
                                                      "department_id": "2"})  # đang ở phòng này
        with self.assertRaises(ServiceError):
            profiles.record_decision(self.conn, emp, {"kind": "termination", "effective_date": "2026-01-01"})

    def test_offboard_and_rehire(self):
        eid = self.emp["id"]
        contract(self.conn, eid, "indefinite", "2025-01-01")
        self.conn.execute("INSERT INTO users (username, password_hash, role, employee_id) VALUES ('nv01', 'x', 'employee', ?)", (eid,))
        self.conn.execute("UPDATE departments SET manager_id = ? WHERE id = 1", (eid,))
        self.conn.execute("INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, days) "
                          "VALUES (?, 'annual', '2026-12-01', '2026-12-01', 1)", (eid,))
        self.conn.commit()
        deleted = []
        form = {"termination_date": "2026-06-10", "reason": "resign", "revoke_rfid": "1",
                "delete_fingerprint": "1", "end_contracts": "1", "cancel_pending": "1", "handover_assets": "1"}
        with self.assertRaises(ServiceError):
            profiles.offboard(self.conn, self.cur(), {**form, "termination_date": "2026-12-01"}, today=TODAY)
        done, warnings = profiles.offboard(self.conn, self.cur(), form, delete_fingerprint=deleted.append,
                                           today=TODAY)
        emp = self.cur()
        self.assertEqual((emp["status"], emp["termination_date"], emp["rfid_uid"], emp["fingerprint_id"]),
                         ("inactive", "2026-06-10", None, None))
        self.assertEqual(deleted, [1])
        self.assertIn("Chấm dứt 1 hợp đồng", done)
        self.assertIn("Thu hồi tài sản, thiết bị", done)
        self.assertTrue(any("trưởng phòng" in w for w in warnings))
        self.assertEqual(profiles.contracts_of(self.conn, eid, TODAY)[0]["terminated_on"], "2026-06-10")
        self.assertEqual(self.conn.execute("SELECT status FROM leave_requests").fetchone()[0], "cancelled")
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM users WHERE employee_id = ?", (eid,)).fetchone())
        self.assertEqual(profiles.history_of(self.conn, eid)[0]["kind"], "termination")

        # sau ngày nghỉ việc: không tính vắng, không hưởng lễ; phép theo tỉ lệ tới tháng 5 (nghỉ trước ngày 15)
        june = services.monthly_report(self.conn, 2026, 6, self.cfg, employee_id=eid)
        self.assertEqual(june, [])  # đã nghỉ, không chấm công tháng 6 -> không có trong báo cáo
        scan(self.conn, emp, self.cfg, datetime(2026, 6, 1, 8, 0), datetime(2026, 6, 1, 17, 0))
        row = services.monthly_report(self.conn, 2026, 6, self.cfg, employee_id=eid)[0]
        self.assertEqual((row["present"], row["absent"]), (1, 7))  # 2–10/6: 7 ngày làm việc còn lại
        days = services.employee_period(self.conn, eid, "2026-06-11", "2026-06-12", self.cfg)
        self.assertEqual({d["status"] for d in days}, {"off"})
        rules = {"leave_seniority": 0, "leave_accrual": "year", "leave_prorate": 1}
        self.assertEqual(services.leave_entitlement(self.cur(), 2026, rules)["months"], 5)

        with self.assertRaises(ServiceError):
            profiles.rehire(self.conn, self.cur(), {"hire_date": "2026-06-01"})
        profiles.rehire(self.conn, self.cur(), {"hire_date": "2026-09-01"})
        emp = self.cur()
        self.assertEqual((emp["status"], emp["hire_date"], emp["termination_date"]), ("active", "2026-09-01", None))

    def test_dependents(self):
        eid = self.emp["id"]
        profiles.add_dependent(self.conn, eid, {"full_name": "Con A", "relation": "Con", "deduct_from": "2026-01-01"})
        profiles.add_dependent(self.conn, eid, {"full_name": "Mẹ", "relation": "Mẹ", "deduct_from": "2020-01-01",
                                                "deduct_to": "2025-12-31"})
        self.assertEqual(profiles.active_dependents(self.conn, eid, TODAY), 1)
        with self.assertRaises(ServiceError):
            profiles.add_dependent(self.conn, eid, {"full_name": "", "relation": "Con"})


class ProfileWebTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.docs = Path(self.tmp.name) / "docs"
        self.app = create_app({"DATABASE": str(Path(self.tmp.name) / "w.db"), "TESTING": True,
                               "HARDWARE_ENABLED": False, "PHOTO_DIR": str(Path(self.tmp.name) / "p"),
                               "DOCUMENT_DIR": str(self.docs)}, start_hardware=False)
        conn = connect(self.app.config["DATABASE"])
        pw = generate_password_hash("pw")
        conn.executescript("""
            INSERT INTO departments (id, name) VALUES (1, 'Kho');
            INSERT INTO employees (id, code, full_name, department_id, hire_date, id_number) VALUES
              (1, 'NV01', 'Trưởng kho', 1, '2025-01-01', NULL), (2, 'NV02', 'Thủ kho', 1, '2025-01-01', '001090000001');
            UPDATE departments SET manager_id = 1 WHERE id = 1;
        """)
        for i in (1, 2):
            conn.execute("INSERT INTO users (username, password_hash, role, employee_id) VALUES (?, ?, 'employee', ?)",
                         (f"nv0{i}", pw, i))
        conn.commit()
        conn.close()
        self.admin = self.login("admin", "admin")

    def tearDown(self):
        self.tmp.cleanup()

    def login(self, user, pw="pw"):
        c = self.app.test_client()
        c.post("/login", data={"username": user, "password": pw})
        return c

    def test_admin_flow(self):
        a = self.admin
        r = a.post("/employees/2/contracts/new", data={"type": "fixed", "start_date": "2026-01-01",
                                                       "end_date": "2026-12-31", "salary": "12.000.000",
                                                       "allowances": "Ăn trưa: 730.000",
                                                       "file": (io.BytesIO(b"%PDF-1.4 x"), "hd.pdf")},
                   follow_redirects=True)
        page = r.data.decode()
        self.assertIn("Đã lưu hợp đồng", page)
        self.assertIn("12.000.000", page)
        self.assertIn("001090000001", page)
        self.assertEqual(len(list((self.docs / "2").iterdir())), 1)
        printed = a.get("/contracts/1/print").data.decode()
        self.assertIn("Mười hai triệu đồng", printed)
        self.assertIn("Ăn trưa", printed)
        for url in ("/contracts", "/contracts?state=expiring", "/contracts/1/edit", "/employees/2/contracts/new",
                    "/employees/2/offboard", "/settings/company", "/", "/employees/2/edit"):
            self.assertEqual(a.get(url).status_code, 200, url)
        r = a.post("/employees/2/contracts/new", data={"type": "indefinite", "start_date": "2026-06-01",
                                                       "salary": "1"}, follow_redirects=True)
        self.assertIn("Trùng thời gian", r.data.decode())

        # sửa hồ sơ đổi chức danh -> tự ghi quá trình công tác
        a.post("/employees/2/edit", data={"code": "NV02", "full_name": "Thủ kho", "department_id": "1",
                                          "position": "Thủ kho chính", "id_number": "001090000001"})
        self.assertIn("Thủ kho chính", a.get("/employees/2").data.decode())
        r = a.post("/employees/2/history", data={"kind": "salary", "effective_date": "2026-07-01",
                                                 "salary": "13.000.000", "decision_no": "05/QĐ"},
                   follow_redirects=True)
        self.assertIn("QĐ 05/QĐ", r.data.decode())

        a.post("/settings/company", data={"name": "Công ty TNHH ABC"})
        self.assertIn("CÔNG TY TNHH ABC", a.get("/contracts/1/print").data.decode())

        r = a.post("/employees/2/offboard", data={"termination_date": date.today().isoformat(),
                                                  "reason": "resign", "end_contracts": "1"}, follow_redirects=True)
        self.assertIn("đã nghỉ việc", r.data.decode())
        self.assertEqual(self.login("nv02").get("/me").status_code, 302)  # tài khoản bị khoá
        self.assertIn("Nhận lại", a.get("/employees/2").data.decode())

    def test_documents_and_sensitive_permission(self):
        a = self.admin
        a.post("/employees/2/documents", data={"kind": "id_card", "file": (io.BytesIO(b"\x89PNGxx"), "cccd.png")})
        r = a.post("/employees/2/documents", data={"file": (io.BytesIO(b"MZ"), "virus.exe")}, follow_redirects=True)
        self.assertIn("Chỉ nhận file", r.data.decode())
        self.assertEqual(a.get("/documents/1").status_code, 200)

        boss = self.login("nv01")  # trưởng phòng: xem hồ sơ được, thông tin nhạy cảm thì không
        page = boss.get("/employees/2").data.decode()
        self.assertNotIn("001090000001", page)
        self.assertNotIn("CCCD / hộ chiếu", page)
        self.assertEqual(boss.get("/documents/1").status_code, 403)
        self.assertEqual(boss.get("/contracts").status_code, 302)  # trang hợp đồng: chỉ admin

        me = self.login("nv02")  # chính mình: xem & tải được, không sửa / xoá được
        self.assertIn("001090000001", me.get("/me").data.decode())
        self.assertEqual(me.get("/documents/1").status_code, 200)
        self.assertEqual(me.post("/documents/1/delete").status_code, 302)
        self.assertTrue(list((self.docs / "2").iterdir()))

        # bật quyền sửa hồ sơ (không có quyền nhạy cảm): lưu form không được xoá CCCD
        a.post("/permissions", data={"perm": ["manager:employees.view", "manager:employees.edit"]})
        boss.post("/employees/2/edit", data={"code": "NV02", "full_name": "Thủ kho 2", "department_id": "1"})
        self.assertIn("001090000001", a.get("/employees/2").data.decode())
        self.assertEqual(boss.post("/employees/2/dependents", data={"full_name": "X", "relation": "Con"}).status_code, 403)
        a.post("/permissions", data={"perm": ["manager:employees.view", "manager:employees.edit",
                                              "manager:employees.sensitive"]})
        self.assertIn("001090000001", boss.get("/employees/2").data.decode())
        boss.post("/employees/2/dependents", data={"full_name": "Con X", "relation": "Con"})
        self.assertIn("Con X", a.get("/employees/2").data.decode())

        a.post("/documents/1/delete")
        self.assertFalse(list((self.docs / "2").iterdir()))
        a.post("/documents/2/delete")
        a.post("/employees/2/documents", data={"file": (io.BytesIO(b"x"), "a.pdf")})
        a.post("/employees/2/delete")
        self.assertFalse((self.docs / "2").exists())


if __name__ == "__main__":
    unittest.main()
