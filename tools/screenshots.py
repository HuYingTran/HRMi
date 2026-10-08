"""Chụp ảnh demo cho README vào docs/screenshots/.

    env/bin/python tools/screenshots.py            # cần Firefox (chạy headless), mất khoảng 3–5 phút

Cách làm: tạo CSDL mô phỏng (seed.py) trong thư mục tạm, lấy HTML các trang đã đăng nhập qua Flask
test client, đổi /static/ và /photos/ thành đường dẫn file://, rồi chụp bằng `firefox --headless
--screenshot` (Chromium headless bị treo trên Raspberry Pi). Ảnh được cắt và nén 256 màu cho nhẹ.
Không đụng tới instance/hrm.db.
"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
EMPLOYEE_ID = 5  # nhân viên dùng cho ảnh hồ sơ, bảng công và trợ lý

# tên ảnh: (trang đã xuất, cửa sổ rộng × cao, vùng cắt)
SHOTS = {
    "dashboard": ("dashboard", (1440, 900)),
    "dashboard-dark": ("dashboard_dark", (1440, 900)),
    "assistant": ("assistant", (1440, 900)),
    "employee": ("employee", (1440, 900)),
    "employees": ("employees", (1440, 900)),
    "timesheets": ("timesheets", (1440, 900)),
    "report": ("report", (1440, 900)),
    "contracts": ("contracts", (1440, 900)),
    "departments": ("departments", (1440, 900)),
    "work-rules": ("work_rules", (1440, 900)),
    "help": ("help", (1440, 900)),
    "kiosk": ("kiosk", (1280, 800)),
    "contract-print": ("contract_print", (1000, 1150)),
}


def export_pages(work):
    """Xuất HTML tĩnh các trang vào work/pages."""
    sys.path.insert(0, str(ROOT))
    from hrm import create_app
    pages_dir = work / "pages"
    pages_dir.mkdir()
    app = create_app({"DATABASE": str(work / "demo.db"), "TESTING": True, "HARDWARE_ENABLED": False,
                      "PHOTO_DIR": str(work / "ph"), "DOCUMENT_DIR": str(work / "docs")}, start_hardware=False)

    def client(user, pw):
        c = app.test_client()
        c.post("/login", data={"username": user, "password": pw})
        return c

    def save(name, html, dark=False, head=""):
        html = html.replace('"/static/', f'"file://{ROOT}/hrm/static/').replace('"/photos/', f'"file://{work}/ph/')
        html = html.replace(' loading="lazy"', "")  # Firefox chụp ngay khi tải xong, ảnh lười chưa kịp nạp
        html = html.replace("try { if (localStorage", "try { if (false && localStorage")  # theme cố định
        if dark:
            html = html.replace(' data-theme="light"', "", 1)
        (pages_dir / f"{name}.html").write_text(html.replace("</head>", head + "</head>", 1), encoding="utf-8")

    admin = client("admin", "admin")
    admin.post("/settings/company", follow_redirects=True,
               data={"name": "Công ty TNHH HRMi Demo", "address": "12 Lê Lợi, Q.1, TP.HCM",
                     "representative": "Nguyễn Văn Chủ", "representative_title": "Giám đốc"})
    admin.post("/work-rules/holidays/suggest", data={"year": str(date.today().year)}, follow_redirects=True)
    last_month = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    for name, url in {"dashboard": "/", "employees": "/employees", "employee": f"/employees/{EMPLOYEE_ID}",
                      "report": "/report", "timesheets": f"/timesheets?month={last_month}",
                      "contracts": "/contracts", "work_rules": "/work-rules", "help": "/help",
                      "departments": "/departments", "contract_print": "/contracts/2/print"}.items():
        r = admin.get(url)
        assert r.status_code == 200, (url, r.status_code)
        save(name, r.data.decode())
    save("dashboard_dark", admin.get("/").data.decode(), dark=True)

    # kiosk: giả lập máy chủ trả lời (ONLINE) và vài lượt quẹt gần đây, lượt cuối đang hiện
    scans = [{"kind": "scan", "type": "check_in", "method": "rfid", "name": n, "code": c, "time": t,
              "late_minutes": late}
             for n, c, t, late in [("Trần Thị Mai", "NV002", "07:52:10", 0), ("Phạm Quốc Bảo", "NV004", "08:07:41", 7),
                                   ("Hoàng Thị Lan", "NV005", "07:58:03", 0)]]
    kiosk = admin.get("/kiosk").data.decode().replace(
        "</body>", f"<script>{json.dumps(scans)}.forEach(show);</script></body>")
    save("kiosk", kiosk, dark=True,
         head="<script>window.fetch = async () => ({ json: async () => ({ events: [] }) });</script>")

    # trợ lý: nhân viên hỏi 2 câu; hội thoại nạp sẵn vào sessionStorage để khung chat mở kèm câu trả lời
    import sqlite3
    with sqlite3.connect(work / "demo.db") as con:
        uname, uid = con.execute("SELECT username, id FROM users WHERE employee_id = ?", (EMPLOYEE_ID,)).fetchone()
    emp = client(uname, "123456")  # mật khẩu demo của seed.py
    items = []
    for q in ("xin nghi nua ngay", "quên quẹt thẻ lúc về thì sao?"):
        answer = emp.post("/api/assistant", json={"q": q, "page": "main.my_timesheet"}).get_json()
        items += [{"role": "me", "text": q}, {"role": "bot", "data": answer}]
    key = f"hrmi.asst.{uid}"
    head = (f"<script>sessionStorage.setItem({json.dumps(key + '.log')}, {json.dumps(json.dumps(items))});"
            f"sessionStorage.setItem({json.dumps(key + '.open')}, 'true');</script>")
    save("assistant", emp.get(f"/my/timesheet?month={last_month}").data.decode(), head=head)


def main():
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        env = {**os.environ, "HRM_PHOTO_DIR": str(work / "ph")}
        print("Tạo dữ liệu mô phỏng…")
        subprocess.run([sys.executable, str(ROOT / "seed.py"), "--db", str(work / "demo.db"), "--days", "45"],
                       check=True, env=env, cwd=ROOT, stdout=subprocess.DEVNULL)
        export_pages(work)
        OUT.mkdir(parents=True, exist_ok=True)
        for out, (page, (w, h)) in SHOTS.items():
            png = work / f"{out}.png"
            subprocess.run(["timeout", "120", "firefox", "--headless", "--screenshot", str(png),
                            f"--window-size={w},{h}", f"file://{work}/pages/{page}.html"],
                           cwd=work, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if not png.exists():
                print(f"  ✗ {out}: Firefox không chụp được")
                continue
            im = Image.open(png).convert("RGB").crop((0, 0, w, h))
            im.quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(
                OUT / f"{out}.png", optimize=True)
            print(f"  ✓ {out}.png ({(OUT / f'{out}.png').stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
