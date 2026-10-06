"""Tạo dữ liệu mô phỏng cho Mini HRM.

    python seed.py            # thêm dữ liệu vào CSDL (từ chối nếu đã có nhân viên)
    python seed.py --reset    # xoá toàn bộ nhân viên/chấm công/nghỉ phép rồi tạo lại
    python seed.py --days 90  # số ngày lịch sử chấm công (mặc định 60)
    python seed.py --no-photos  # không tạo ảnh avatar hoạt hình
    python seed.py --add-ot   # chỉ thêm lượt làm thêm thứ 7, CN vào CSDL đang có
    python seed.py --demo-workflow  # chỉ thêm tài khoản NV + mô phỏng quy trình bảng công tháng trước

Dữ liệu sinh ngẫu nhiên nhưng cố định theo --seed để mỗi lần chạy ra cùng một kết quả.
Mã thẻ RFID và vị trí vân tay là giả: khi dùng phần cứng thật hãy chạy lại
"Quét thẻ" / "Đăng ký vân tay" cho từng người, hoặc tạo CSDL mới.
"""
import argparse
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

from demo_avatars import animal_avatar
from werkzeug.security import generate_password_hash

from hrm import photos, services, timesheet
from hrm.config import Config
from hrm.db import init_db

CFG = {k: getattr(Config, k) for k in dir(Config) if k.isupper()}

DEPARTMENTS = {
    "Ban Giám đốc": ["Giám đốc", "Phó Giám đốc"],
    "Kỹ thuật": ["Trưởng phòng Kỹ thuật", "Kỹ sư phần mềm", "Kỹ sư phần cứng", "Kỹ thuật viên"],
    "Kinh doanh": ["Trưởng phòng Kinh doanh", "Chuyên viên kinh doanh", "Chăm sóc khách hàng"],
    "Kế toán": ["Kế toán trưởng", "Kế toán viên"],
    "Nhân sự": ["Trưởng phòng Nhân sự", "Chuyên viên nhân sự"],
    "Kho vận": ["Quản lý kho", "Nhân viên kho"],
}

# phòng ban con -> phòng ban cấp trên
PARENTS = {
    "Kỹ thuật": "Ban Giám đốc",
    "Kinh doanh": "Ban Giám đốc",
    "Kế toán": "Ban Giám đốc",
    "Nhân sự": "Ban Giám đốc",
    "Kho vận": "Kinh doanh",
}

# (họ tên, giới tính, phòng ban, chỉ số chức vụ, xu hướng đi muộn 0..1)
PEOPLE = [
    ("Nguyễn Văn Hùng", "Nam", "Ban Giám đốc", 0, 0.05),
    ("Trần Thị Mai", "Nữ", "Ban Giám đốc", 1, 0.08),
    ("Lê Minh Tuấn", "Nam", "Kỹ thuật", 0, 0.10),
    ("Phạm Quốc Bảo", "Nam", "Kỹ thuật", 1, 0.35),
    ("Hoàng Thị Lan", "Nữ", "Kỹ thuật", 1, 0.12),
    ("Vũ Đức Anh", "Nam", "Kỹ thuật", 2, 0.20),
    ("Đặng Thanh Tâm", "Nữ", "Kỹ thuật", 3, 0.45),
    ("Bùi Văn Long", "Nam", "Kỹ thuật", 3, 0.15),
    ("Đỗ Thị Hương", "Nữ", "Kinh doanh", 0, 0.10),
    ("Ngô Gia Huy", "Nam", "Kinh doanh", 1, 0.30),
    ("Dương Ngọc Ánh", "Nữ", "Kinh doanh", 1, 0.18),
    ("Lý Hoàng Nam", "Nam", "Kinh doanh", 2, 0.25),
    ("Trịnh Thu Trang", "Nữ", "Kế toán", 0, 0.03),
    ("Mai Phương Thảo", "Nữ", "Kế toán", 1, 0.06),
    ("Phan Thị Ngọc", "Nữ", "Nhân sự", 0, 0.05),
    ("Tạ Minh Khoa", "Nam", "Nhân sự", 1, 0.22),
    ("Cao Văn Thắng", "Nam", "Kho vận", 0, 0.12),
    ("Hồ Đức Thịnh", "Nam", "Kho vận", 1, 0.40),
    ("Lâm Bảo Ngọc", "Nữ", "Kho vận", 1, 0.15),
    ("Châu Quang Vinh", "Nam", "Kỹ thuật", 2, 0.10),
]

STREETS = ["Nguyễn Trãi", "Lê Lợi", "Trần Hưng Đạo", "Hai Bà Trưng", "Điện Biên Phủ",
           "Cách Mạng Tháng 8", "Võ Văn Tần", "Pasteur", "Nam Kỳ Khởi Nghĩa", "Lý Thường Kiệt"]
DISTRICTS = ["Quận 1", "Quận 3", "Quận 5", "Quận 10", "Bình Thạnh", "Phú Nhuận", "Gò Vấp", "Tân Bình"]

LEAVE_REASONS = {
    "annual": ["Về quê thăm gia đình", "Du lịch cùng gia đình", "Việc cá nhân", "Đám cưới người thân",
               "Nghỉ ngơi sau dự án"],
    "sick": ["Sốt, có giấy khám bệnh", "Đau dạ dày", "Cảm cúm", "Khám sức khoẻ định kỳ"],
    "unpaid": ["Giải quyết việc gia đình", "Chuyển nhà"],
    "business": ["Gặp khách hàng tại Hà Nội", "Lắp đặt thiết bị cho khách", "Hội thảo ngành tại Đà Nẵng",
                 "Khảo sát kho Bình Dương"],
    "other": ["Tham gia khoá đào tạo bên ngoài", "Việc hành chính tại phường"],
}


def ascii_slug(name):
    table = str.maketrans(
        "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ",
        "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyyd",
    )
    parts = name.lower().translate(table).split()
    return parts[-1] + "." + "".join(p[0] for p in parts[:-1])


def jitter(rng, base, sd_minutes, lo=-60, hi=120):
    minutes = max(lo, min(hi, rng.gauss(0, sd_minutes)))
    return base + timedelta(minutes=minutes, seconds=rng.randint(0, 59))


def add_overtime(conn, rng, start, today, people=5):
    """Thêm lượt chấm công làm thêm (OT) thứ 7, CN cho vài nhân viên.

    Chỉ thêm, không xoá gì; bỏ qua ngày người đó đã có lượt quét. Cuối tuần gần nhất
    luôn có ít nhất 2 người OT để thấy ngay trên biểu đồ 2 tuần.
    """
    emps = conn.execute(
        "SELECT id, hire_date, fingerprint_id FROM employees WHERE status = 'active' ORDER BY id"
    ).fetchall()
    team = rng.sample(emps, min(people, len(emps)))
    now = datetime.now()
    last_weekend = [d for d in (today - timedelta(days=i) for i in range(1, 8))
                    if not services.is_workday(d, CFG)]
    added = 0
    d = start
    while d <= today:
        if services.is_workday(d, CFG):
            d += timedelta(days=1)
            continue
        sunday = d.weekday() == 6
        for i, emp in enumerate(team):
            forced = d in last_weekend and i < 2
            if not forced and rng.random() > (0.15 if sunday else 0.35):
                continue
            if emp["hire_date"] and emp["hire_date"] > d.isoformat():
                continue
            if conn.execute("SELECT 1 FROM attendance_logs WHERE employee_id = ? AND ts LIKE ?",
                            (emp["id"], d.isoformat() + "%")).fetchone():
                continue
            # nửa ngày sáng hoặc cả ngày
            t_in = datetime.combine(d, time(8, rng.randint(0, 40), rng.randint(0, 59)))
            if rng.random() < 0.5:
                t_out = datetime.combine(d, time(rng.randint(11, 12), rng.randint(0, 59), rng.randint(0, 59)))
            else:
                t_out = datetime.combine(d, time(rng.randint(16, 18), rng.randint(0, 59), rng.randint(0, 59)))
            method = "fingerprint" if emp["fingerprint_id"] is not None else "rfid"
            for ts in (t_in, t_out):
                if ts <= now:
                    conn.execute(
                        "INSERT INTO attendance_logs (employee_id, ts, method, note) VALUES (?, ?, ?, 'OT')",
                        (emp["id"], ts.strftime(services.TS_FMT), method),
                    )
            added += 1
        d += timedelta(days=1)
    conn.commit()
    return added


DEMO_PASSWORD = "123456"

EXPLAIN = {
    "missing_out": ["Quên quét thẻ khi về", "Máy chấm công không nhận vân tay lúc về"],
    "late": ["Kẹt xe trên cầu Sài Gòn", "Đưa con đi khám bệnh", "Xe hỏng dọc đường"],
    "absent": ["Bị sốt, quên làm đơn nghỉ", "Đi gặp khách hàng, quên tạo đơn công tác"],
}


def add_accounts(conn):
    """Tạo tài khoản nhân viên (mã NV viết thường / DEMO_PASSWORD) cho người chưa có."""
    n = 0
    for e in conn.execute("SELECT e.id, e.code FROM employees e LEFT JOIN users u ON u.employee_id = e.id "
                          "WHERE u.id IS NULL AND e.status = 'active'").fetchall():
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (e["code"].lower(),)).fetchone():
            continue
        conn.execute("INSERT INTO users (username, password_hash, role, employee_id) VALUES (?, ?, 'employee', ?)",
                     (e["code"].lower(), generate_password_hash(DEMO_PASSWORD), e["id"]))
        n += 1
    conn.commit()
    return n


def demo_workflow(conn, rng, month):
    """Mô phỏng quy trình xác nhận bảng công của một tháng đã kết thúc (chỉ thêm dữ liệu)."""
    existing = {r[0] for r in conn.execute("SELECT employee_id FROM timesheets WHERE month = ?", (month,))}
    first = services.parse_month(month)
    rows = services.monthly_report(conn, first.year, first.month, CFG)
    # không đụng tới bảng công đã có (do người dùng thao tác)
    rows = [r for r in rows if r["employee"]["status"] == "active" and r["employee"]["id"] not in existing]
    if not rows:
        return "mọi nhân viên đã có bảng công tháng này, bỏ qua"
    timesheet.send(conn, [r["employee"]["id"] for r in rows], month)
    admin = conn.execute("SELECT * FROM users WHERE role = 'admin' ORDER BY id").fetchone()

    def reviewer(emp):
        rid = timesheet.reviewer_id(conn, emp)
        u = conn.execute("SELECT * FROM users WHERE employee_id = ?", (rid,)).fetchone() if rid else None
        return u or admin

    with_issues = [r for r in rows if services.issues_of(r) or r["late"]]
    clean = [r for r in rows if r not in with_issues]
    rng.shuffle(with_issues)
    rng.shuffle(clean)
    counts = {"giải trình + chờ duyệt": 0, "đã chốt": 0, "bị trả lại": 0, "chưa xác nhận": 0}
    for i, r in enumerate(with_issues):
        emp = r["employee"]
        if i >= 7:
            counts["chưa xác nhận"] += 1
            continue
        ts = timesheet.get(conn, emp["id"], month)
        for d in timesheet.detail(conn, emp["id"], month, CFG)["flagged"]:
            reason = rng.choice(EXPLAIN[d["status"]])
            p_in = p_out = None
            if d["status"] == "missing_out":
                p_out = f"17:{rng.randint(5, 45):02d}"
            elif d["status"] == "absent" and "quên làm đơn" not in reason and "công tác" not in reason:
                p_in, p_out = "08:00", "17:00"
            timesheet.explain(conn, ts, d["date"].isoformat(), reason, p_in, p_out)
        timesheet.submit(conn, ts, rng.choice([None, "Nhờ anh/chị xem giúp các ngày giải trình."]))
        ts = timesheet.get(conn, emp["id"], month)
        if i < 3:  # cấp trên đã xử lý và chốt
            for day in timesheet.explanations(conn, ts["id"]):
                timesheet.review_explanation(conn, ts, day, True, "Đồng ý", CFG)
            timesheet.confirm(conn, emp["id"], month, reviewer(emp), CFG)
            counts["đã chốt"] += 1
        elif i == 3:
            timesheet.return_to_employee(conn, ts, "Cần bổ sung minh chứng cho các ngày giải trình, gửi lại giúp anh/chị.")
            counts["bị trả lại"] += 1
        else:
            counts["giải trình + chờ duyệt"] += 1
    for i, r in enumerate(clean):
        ts = timesheet.get(conn, r["employee"]["id"], month)
        if i % 2 == 0:
            timesheet.submit(conn, ts)  # xác nhận đúng, không cần giải trình
            counts["giải trình + chờ duyệt"] += 1
        else:
            counts["chưa xác nhận"] += 1
    return ", ".join(f"{v} {k}" for k, v in counts.items())


def seed(conn, days, rng, with_photos=True):
    today = date.today()
    start = today - timedelta(days=days)

    dept_ids = {}
    for name in DEPARTMENTS:
        conn.execute("INSERT OR IGNORE INTO departments (name) VALUES (?)", (name,))
        dept_ids[name] = conn.execute("SELECT id FROM departments WHERE name = ?", (name,)).fetchone()[0]

    for child, parent in PARENTS.items():
        conn.execute("UPDATE departments SET parent_id = ? WHERE id = ?",
                     (dept_ids[parent], dept_ids[child]))

    employees = []
    for i, (name, gender, dept, pos_idx, lateness) in enumerate(PEOPLE, start=1):
        # 2 người mới vào trong khoảng mô phỏng, 1 người đã nghỉ việc
        if i in (19, 20):
            hire = today - timedelta(days=rng.randint(10, days - 10))
        else:
            hire = today - timedelta(days=rng.randint(200, 2500))
        status = "inactive" if i == 8 else "active"
        dob = date(rng.randint(1975, 2001), rng.randint(1, 12), rng.randint(1, 28))
        has_fp = rng.random() < 0.75
        cur = conn.execute(
            "INSERT INTO employees (code, full_name, gender, dob, phone, email, address, "
            "department_id, position, hire_date, status, annual_leave_days, rfid_uid, fingerprint_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"NV{i:03d}", name, gender, dob.isoformat(),
                "09" + "".join(str(rng.randint(0, 9)) for _ in range(8)),
                ascii_slug(name) + "@hrmi.local",
                f"{rng.randint(1, 300)} {rng.choice(STREETS)}, {rng.choice(DISTRICTS)}, TP.HCM",
                dept_ids[dept], DEPARTMENTS[dept][pos_idx], hire.isoformat(), status,
                12 + (2 if pos_idx == 0 else 0),
                "".join(rng.choice("0123456789ABCDEF") for _ in range(8)),
                i if has_fp else None,
            ),
        )
        employees.append({"id": cur.lastrowid, "hire": hire, "lateness": lateness,
                          "has_fp": has_fp, "status": status, "pos_idx": pos_idx})
        if with_photos:  # avatar hoạt hình con vật, lần lượt chó, mèo, lợn, gà, cá...
            _, img = animal_avatar(i - 1)
            conn.execute("UPDATE employees SET photo = ? WHERE id = ?",
                         (photos.save_image(img, Config.PHOTO_DIR, cur.lastrowid), cur.lastrowid))
        if pos_idx == 0:  # người giữ chức vụ đầu tiên của phòng là trưởng phòng
            conn.execute("UPDATE departments SET manager_id = ? WHERE id = ?",
                         (cur.lastrowid, dept_ids[dept]))

    # ---- đơn nghỉ phép (tạo trước để không chấm công vào ngày nghỉ)
    leave_days = {}  # emp_id -> set(ngày đã duyệt)
    taken = {}       # emp_id -> list((start, end)) để tránh trùng

    def add_leave(emp, ltype, s, e, half, status, note=None):
        for a, b in taken.get(emp["id"], []):
            if s <= b and e >= a:
                return False
        n = services.count_leave_days(s, e, half, CFG)
        if n <= 0:
            return False
        created = datetime.combine(s - timedelta(days=rng.randint(2, 10)), time(rng.randint(8, 17), rng.randint(0, 59)))
        reviewed = None if status == "pending" else (created + timedelta(hours=rng.randint(2, 30))).strftime(services.TS_FMT)
        conn.execute(
            "INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, half_day, days, "
            "reason, status, review_note, created_at, reviewed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (emp["id"], ltype, s.isoformat(), e.isoformat(), 1 if half else 0, n,
             rng.choice(LEAVE_REASONS[ltype]), status, note, created.strftime(services.TS_FMT), reviewed),
        )
        taken.setdefault(emp["id"], []).append((s, e))
        if status == "approved":
            d = s
            while d <= e:
                leave_days.setdefault(emp["id"], set()).add(d)
                d += timedelta(days=1)
        return True

    active = [e for e in employees if e["status"] == "active"]
    plans = (
        [("annual", "approved")] * 12 + [("sick", "approved")] * 6 + [("unpaid", "approved")] * 1
        + [("business", "approved")] * 5
        + [("annual", "rejected")] * 2 + [("annual", "cancelled")] * 1 + [("other", "approved")] * 1
    )
    for ltype, status in plans:
        for _ in range(10):
            emp = rng.choice(active)
            s = start + timedelta(days=rng.randint(0, days - 3))
            if s < emp["hire"]:
                continue
            length = 0 if ltype == "sick" else rng.choice([0, 0, 1, 2])
            half = length == 0 and rng.random() < 0.3
            note = "Trùng lịch dự án, đề nghị dời sang tuần sau" if status == "rejected" else None
            if add_leave(emp, ltype, s, s + timedelta(days=length), half, status, note):
                break

    # Đơn đang chờ duyệt trong tương lai gần + 1 người nghỉ phép hôm nay
    for ltype in ("annual", "annual", "sick", "annual", "other"):
        for _ in range(10):
            emp = rng.choice(active)
            s = today + timedelta(days=rng.randint(1, 20))
            if add_leave(emp, ltype, s, s + timedelta(days=rng.choice([0, 1, 2])), False, "pending"):
                break
    if services.is_workday(today, CFG):
        for ltype in ("annual", "business"):  # 1 người nghỉ phép + 1 người đi công tác hôm nay
            for emp in rng.sample(active, len(active)):
                if add_leave(emp, ltype, today, today + timedelta(days=1 if ltype == "business" else 0),
                             False, "approved"):
                    break

    # ---- chấm công
    work_start = datetime.strptime(CFG["WORK_START"], "%H:%M").time()
    work_end = datetime.strptime(CFG["WORK_END"], "%H:%M").time()
    now = datetime.now()
    logs = 0
    for emp in employees:
        if emp["status"] != "active":
            last_day = today - timedelta(days=rng.randint(5, 20))  # đã nghỉ việc gần đây
        else:
            last_day = today
        d = max(start, emp["hire"])
        while d <= last_day:
            if not services.is_workday(d, CFG) or d in leave_days.get(emp["id"], set()):
                d += timedelta(days=1)
                continue
            if rng.random() < 0.025:  # vắng không phép
                d += timedelta(days=1)
                continue
            base_in = datetime.combine(d, work_start) - timedelta(minutes=12)
            if rng.random() < emp["lateness"]:
                t_in = base_in + timedelta(minutes=rng.randint(19, 55), seconds=rng.randint(0, 59))
            else:
                t_in = jitter(rng, base_in, 7, lo=-25, hi=16)
            t_out = jitter(rng, datetime.combine(d, work_end) + timedelta(minutes=12), 18, lo=-50, hi=110)
            if emp["pos_idx"] == 0:
                t_out += timedelta(minutes=rng.randint(20, 70))  # quản lý về muộn hơn
            method = "fingerprint" if emp["has_fp"] and rng.random() < 0.65 else "rfid"

            stamps = [t_in]
            if rng.random() < 0.15:  # ra ngoài ăn trưa
                stamps.append(datetime.combine(d, time(12, rng.randint(0, 10), rng.randint(0, 59))))
            if rng.random() > 0.03:  # 3% quên quét giờ ra
                stamps.append(t_out)
            for ts in stamps:
                if ts > now:
                    continue
                note = None
                m = method
                if rng.random() < 0.02:
                    m, note = "manual", "Quên thẻ, quản lý xác nhận"
                conn.execute(
                    "INSERT INTO attendance_logs (employee_id, ts, method, note) VALUES (?, ?, ?, ?)",
                    (emp["id"], ts.strftime(services.TS_FMT), m, note),
                )
                logs += 1
            d += timedelta(days=1)

    add_overtime(conn, rng, start, today)
    conn.commit()
    n_leaves = conn.execute("SELECT COUNT(*) FROM leave_requests").fetchone()[0]
    return len(DEPARTMENTS), len(employees), logs, n_leaves


def main():
    ap = argparse.ArgumentParser(description="Tạo dữ liệu mô phỏng cho Mini HRM")
    ap.add_argument("--reset", action="store_true", help="xoá dữ liệu nhân sự cũ trước khi tạo")
    ap.add_argument("--days", type=int, default=60, help="số ngày lịch sử chấm công")
    ap.add_argument("--seed", type=int, default=2026, help="hạt giống ngẫu nhiên")
    ap.add_argument("--db", default=Config.DATABASE, help="đường dẫn CSDL")
    ap.add_argument("--no-photos", action="store_true", help="không tạo ảnh hoạt hình")
    ap.add_argument("--demo-workflow", action="store_true",
                    help="chỉ thêm tài khoản nhân viên + mô phỏng quy trình xác nhận bảng công tháng trước")
    ap.add_argument("--add-ot", action="store_true",
                    help="chỉ thêm lượt OT thứ 7, CN vào CSDL hiện có (không xoá dữ liệu)")
    args = ap.parse_args()

    conn = init_db(args.db)
    if args.demo_workflow:
        n = add_accounts(conn)
        month = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        print(f"Đã tạo {n} tài khoản nhân viên (mật khẩu {DEMO_PASSWORD})")
        print(f"Bảng công {month}: {demo_workflow(conn, random.Random(args.seed), month)}")
        return
    if args.add_ot:
        today = date.today()
        n = add_overtime(conn, random.Random(args.seed), today - timedelta(days=args.days), today)
        print(f"Đã thêm {n} ngày OT (thứ 7, CN) → {args.db}")
        return
    existing = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    if existing and not args.reset:
        raise SystemExit(f"CSDL {args.db} đã có {existing} nhân viên. Dùng --reset để xoá và tạo lại.")
    if args.reset:
        for table in ("attendance_logs", "leave_requests", "employees", "departments"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        for f in Path(Config.PHOTO_DIR).glob("*.jpg"):
            f.unlink()

    depts, emps, logs, leaves = seed(conn, max(args.days, 20), random.Random(args.seed),
                                     with_photos=not args.no_photos)
    if not conn.execute("SELECT 1 FROM users WHERE role = 'admin'").fetchone():
        conn.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
                     (Config.ADMIN_USERNAME, generate_password_hash(Config.ADMIN_PASSWORD)))
    add_accounts(conn)
    demo_workflow(conn, random.Random(args.seed), (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m"))
    print(f"Đã tạo {depts} phòng ban, {emps} nhân viên, {logs} lượt chấm công, {leaves} đơn nghỉ "
          f"→ {args.db}")
    conn.close()


if __name__ == "__main__":
    main()
