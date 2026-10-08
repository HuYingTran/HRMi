"""Trợ lý HRMi (tầng offline) và kho hướng dẫn. Chạy: env/bin/python -m unittest discover tests"""
import re
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import generate_password_hash

from hrm import create_app
from hrm.assistant import knowledge
from hrm.assistant.search import Index, strip_accents, terms
from hrm.db import connect

# (câu hỏi, chủ đề mong đợi) -- None: không tìm thấy; "page:<nhãn>": mở trang; "other": việc của vai trò khác
ADMIN_CASES = [
    ("làm sao xin nghỉ nửa ngày", "xin-nghi-phep"),
    ("xin nghi nua ngay", "xin-nghi-phep"),
    ("quên quẹt thẻ lúc về", "quen-cham-cong"),
    ("tôi còn bao nhiêu ngày phép", "so-ngay-phep"),
    ("đổi mật khẩu", "doi-mat-khau"),
    ("hợp đồng sắp hết hạn", "hop-dong"),
    ("dang ky the rfid", "dang-ky-the-van-tay"),
    ("chốt công cuối tháng", "chot-cong-cuoi-thang"),
    ("tăng ca tính sao", "lam-them-gio"),
    ("ai đi muộn hôm nay", "bao-cao"),
    ("thêm nhân viên", "them-nhan-vien"),
    ("nhân viên nghỉ việc", "nghi-viec"),
    ("cài đặt email", "email"),
    ("máy không nhận thẻ", "thiet-bi"),
    ("nạp ngày lễ tết", "ngay-le"),
    ("đổi giờ làm việc", "gio-lam-ca"),
    ("phân quyền trưởng phòng", "phan-quyen"),
    ("huỷ đơn nghỉ", "huy-don"),
    ("thêm người phụ thuộc", "ho-so-giay-to"),
    ("mở trang hợp đồng", "page:Hợp đồng"),
    ("vào trang báo cáo", "page:Báo cáo tháng"),
    ("thời tiết hôm nay", None),
]
EMPLOYEE_CASES = [
    ("làm sao xin nghỉ nửa ngày", "xin-nghi-phep"),
    ("xác nhận bảng công", "bang-cong-cua-toi"),
    ("tôi còn bao nhiêu ngày phép", "so-ngay-phep"),
    ("đăng ký OT", "lam-them-gio"),
    ("mở trang hợp đồng", "other"),
    ("thêm nhân viên", "other"),
    ("chốt công cuối tháng", "other"),
    ("thời tiết hôm nay", None),
]


class SearchTest(unittest.TestCase):
    def test_normalize_and_terms(self):
        self.assertEqual(strip_accents("Đơn NGHỈ phép"), "don nghi phep")
        self.assertEqual(terms("Làm sao để xin nghỉ phép?"), ["lam", "de", "xin", "nghi", "phep",
                                                               "lam de", "de xin", "xin nghi", "nghi phep"])

    def test_phrase_beats_scattered_words(self):
        idx = Index([("a", [("nghỉ phép năm", 1)]), ("b", [("phép thử, ngày nghỉ hằng tuần", 1)]),
                     ("c", [("chấm công", 1)])])
        self.assertEqual(idx.search("nghi phep")[0][0], "a")
        self.assertEqual(idx.search("nghi phep", allowed={"b"})[0][0], "b")
        self.assertAlmostEqual(idx.coverage("chấm công hôm nay", "c"), 2 / 3)  # "này" là từ dừng


class KnowledgeTest(unittest.TestCase):
    def test_parse_topic(self):
        t = knowledge.parse_topic("x", "---\ntitle: Tiêu đề\nroles: [admin]\npages: [main.leaves]\n"
                                       "ask: [Hỏi 1?, Hỏi 2?]\n---\nTóm tắt.\n\n## Chi tiết\nThêm.\n")
        self.assertEqual((t.title, t.roles, t.pages, t.ask), ("Tiêu đề", ("admin",), ("main.leaves",),
                                                             ("Hỏi 1?", "Hỏi 2?")))
        self.assertEqual(t.summary, "Tóm tắt.")
        self.assertTrue(t.has_more)
        self.assertEqual(knowledge.parse_topic("y", "---\ntitle: T\n---\nA").roles, knowledge.ROLES)

    def test_render_escapes_html(self):
        app = create_app({"DATABASE": ":memory:", "TESTING": True, "HARDWARE_ENABLED": False},
                         start_hardware=False)
        with app.test_request_context():
            html = str(knowledge.render("<script>x</script> **đậm** `mã`\n\n- một\n- hai\n\n1. a\n## T"))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("<b>đậm</b> <code>mã</code>", html)
        self.assertIn("<ul>\n<li>một</li>\n<li>hai</li>\n</ul>", html)
        self.assertIn("<ol>\n<li>a</li>\n</ol>\n<h3>T</h3>", html)


class AssistantWebTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({"DATABASE": str(Path(self.tmp.name) / "a.db"), "TESTING": True,
                               "HARDWARE_ENABLED": False, "PHOTO_DIR": str(Path(self.tmp.name) / "p")},
                              start_hardware=False)
        conn = connect(self.app.config["DATABASE"])
        conn.execute("INSERT INTO employees (id, code, full_name) VALUES (1, 'NV01', 'A')")
        conn.execute("INSERT INTO users (username, password_hash, role, employee_id) VALUES ('nv01', ?, "
                     "'employee', 1)", (generate_password_hash("pw"),))
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def login(self, user, pw):
        c = self.app.test_client()
        c.post("/login", data={"username": user, "password": pw})
        return c

    def ask(self, c, q, page="main.dashboard"):
        r = c.post("/api/assistant", json={"q": q, "page": page})
        self.assertEqual(r.status_code, 200, q)
        return r.get_json()

    def check(self, c, cases):
        topics, _ = knowledge.load()
        for q, want in cases:
            d = self.ask(c, q)
            if want is None:
                self.assertIsNone(d["title"], q)
                self.assertIn("chưa tìm thấy", d["html"], q)
            elif want == "other":
                self.assertIn("không có quyền", d["html"], q)
                self.assertEqual(d["links"], [], q)
            elif want.startswith("page:"):
                self.assertEqual(d["links"][0]["label"], want[5:], q)
            else:
                self.assertEqual(d["title"], topics[want].title, q)

    def test_questions_admin(self):
        self.check(self.login("admin", "admin"), ADMIN_CASES)

    def test_questions_employee_and_permissions(self):
        c = self.login("nv01", "pw")
        self.check(c, EMPLOYEE_CASES)
        admin_only = {"/employees", "/contracts", "/timesheets", "/permissions", "/work-rules", "/device"}
        for q in ("mở trang nhân viên", "hợp đồng", "phân quyền", "thiết bị", "chốt công", "báo cáo"):
            for link in self.ask(c, q)["links"]:
                self.assertNotIn(link["url"].split("?")[0], admin_only, q)
        page = c.get("/help").data.decode()
        self.assertIn("Xin nghỉ phép", page)
        self.assertNotIn("Hợp đồng lao động", page)
        self.assertEqual(c.get("/help/hop-dong").status_code, 404)
        self.assertEqual(c.get("/help/xin-nghi-phep").status_code, 200)

    def test_small_talk_suggestions_and_widget(self):
        c = self.login("nv01", "pw")
        d = self.ask(c, "xin chào")
        self.assertIn("nhân viên", d["html"])
        self.assertEqual(len(d["suggestions"]), 3)
        self.assertIn("Không có gì", self.ask(c, "cảm ơn nhé")["html"])
        self.assertEqual(c.post("/api/assistant", json={}).status_code, 400)
        long_q = self.ask(c, "nghỉ phép " * 200)  # bị cắt còn 500 ký tự, vẫn trả lời được
        self.assertIsNotNone(long_q["title"])
        page = c.get("/my/timesheet").data.decode()
        self.assertIn('id="asst"', page)
        self.assertIn("Xác nhận bảng công thế nào?", page)  # gợi ý theo trang đang mở
        anon = self.app.test_client()
        self.assertNotIn('id="asst"', anon.get("/login").data.decode())
        self.assertEqual(anon.post("/api/assistant", json={"q": "x"}).status_code, 401)

    def test_help_files_valid(self):
        """Mọi hướng dẫn: khai báo đủ, trang tồn tại và mở được không cần tham số, liên kết [[...]] hợp lệ."""
        topics, _ = knowledge.load()
        self.assertGreaterEqual(len(topics), 25)
        endpoints = {r.endpoint for r in self.app.url_map.iter_rules()}
        c = self.login("admin", "admin")
        for t in topics.values():
            self.assertTrue(t.title and t.ask and t.summary, t.slug)
            self.assertTrue(set(t.roles) <= set(knowledge.ROLES), t.slug)
            refs = set(t.pages) | set(re.findall(r"\[\[(main\.[a-z_]+)", t.body))
            for ep in refs:
                self.assertIn(ep, endpoints, f"{t.slug}: {ep}")
            self.assertEqual(c.get(f"/help/{t.slug}").status_code, 200, t.slug)
        for ep in list(knowledge.PAGE_ALIASES) + list(knowledge.EXTRA_PAGES):
            self.assertIn(ep, endpoints, ep)


if __name__ == "__main__":
    unittest.main()
