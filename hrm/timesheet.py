"""Quy trình xác nhận bảng công tháng (tiền đề tính lương).

    (chưa gửi) --gửi--> sent --NV gửi duyệt--> submitted --cấp trên chốt--> confirmed
                          ^                        |
                          +---- returned <--trả lại+

- Nhân viên giải trình từng ngày có vấn đề khi bảng công ở trạng thái sent / returned.
- Cấp trên (trưởng phòng theo sơ đồ phòng ban, không có thì admin) chấp nhận / từ chối giải
  trình; chấp nhận giải trình có giờ đề nghị sẽ thêm lượt chấm công thủ công tương ứng.
- Đã chốt thì lưu bản chụp số liệu và khoá dữ liệu tháng (services.ensure_unlocked).
"""
import calendar
import json
from datetime import date, datetime

from . import services
from .services import ServiceError

STATUSES = {
    None: "Chưa gửi",
    "sent": "Chờ NV xác nhận",
    "returned": "Bị trả lại",
    "submitted": "Chờ cấp trên duyệt",
    "confirmed": "Đã chốt",
}
# Ngày cần giải trình
FLAGGED = ("late", "missing_out", "absent")


# ---------------------------------------------------------------- truy vấn

def _row(conn, sql, params):
    r = conn.execute(sql, params).fetchone()
    if r is None:
        return None
    out = dict(r)
    out["data"] = json.loads(out["data"]) if out.get("data") else None
    return out


def get(conn, employee_id, month):
    return _row(conn, "SELECT t.*, u.username AS confirmed_by_name FROM timesheets t "
                      "LEFT JOIN users u ON u.id = t.confirmed_by "
                      "WHERE t.employee_id = ? AND t.month = ?", (employee_id, month))


def of_month(conn, month):
    """{employee_id: timesheet} của một tháng."""
    out = {}
    for r in conn.execute("SELECT t.*, u.username AS confirmed_by_name FROM timesheets t "
                          "LEFT JOIN users u ON u.id = t.confirmed_by WHERE t.month = ?", (month,)):
        d = dict(r)
        d["data"] = json.loads(d["data"]) if d["data"] else None
        out[d["employee_id"]] = d
    return out


def explanations(conn, timesheet_id):
    return {r["day"]: dict(r) for r in conn.execute(
        "SELECT * FROM timesheet_explanations WHERE timesheet_id = ? ORDER BY day", (timesheet_id,))}


def pending_counts(conn, month):
    """{timesheet_id: số giải trình chưa xử lý}"""
    return {r[0]: r[1] for r in conn.execute(
        "SELECT x.timesheet_id, COUNT(*) FROM timesheet_explanations x "
        "JOIN timesheets t ON t.id = x.timesheet_id WHERE t.month = ? AND x.status = 'pending' "
        "GROUP BY x.timesheet_id", (month,))}


# ---------------------------------------------------------------- cấp trên

def reviewer_id(conn, employee):
    """Id nhân viên là cấp trên duyệt bảng công; None nghĩa là admin duyệt.

    Trưởng phòng của phòng nhân viên; nếu chính họ là trưởng phòng thì đi lên phòng cấp trên.
    """
    dept_id, seen = employee["department_id"], set()
    while dept_id and dept_id not in seen:
        seen.add(dept_id)
        d = conn.execute("SELECT parent_id, manager_id FROM departments WHERE id = ?", (dept_id,)).fetchone()
        if d is None:
            return None
        if d["manager_id"] and d["manager_id"] != employee["id"]:
            mgr = conn.execute("SELECT status FROM employees WHERE id = ?", (d["manager_id"],)).fetchone()
            if mgr and mgr["status"] == "active":
                return d["manager_id"]
        dept_id = d["parent_id"]
    return None


def subordinate_ids(conn, manager_employee_id):
    """Nhân viên mà người này là cấp trên duyệt bảng công."""
    rows = conn.execute("SELECT * FROM employees").fetchall()
    return {e["id"] for e in rows if reviewer_id(conn, e) == manager_employee_id}


def can_review(conn, user, employee):
    """Admin, hoặc trưởng phòng có quyền duyệt bảng công và nhân viên nằm trong nhánh mình quản lý.

    Cấp trên trực tiếp (reviewer_id) là người được nhắc duyệt; các cấp cao hơn cùng nhánh
    cũng duyệt thay được.
    """
    if user["role"] == "admin":
        return True
    if not user["employee_id"] or employee["id"] == user["employee_id"]:
        return False
    from .permissions import settings, team_ids
    return (settings(conn)[("manager", "timesheets.review")]
            and employee["id"] in team_ids(conn, user["employee_id"]))


# ---------------------------------------------------------------- chuyển trạng thái

def _require(ts, *states):
    if ts is None or ts["status"] not in states:
        current = STATUSES[ts["status"] if ts else None]
        raise ServiceError(f"Không thực hiện được ở trạng thái \"{current}\".")


def send(conn, employee_ids, month, today=None):
    """Gửi bảng công cho nhân viên xác nhận. Trả về danh sách nhân viên mới được gửi."""
    if not services.month_ended(month, today):
        raise ServiceError("Chỉ gửi được bảng công của tháng đã kết thúc.")
    sent = []
    for emp_id in employee_ids:
        cur = conn.execute("INSERT OR IGNORE INTO timesheets (employee_id, month, status) "
                           "VALUES (?, ?, 'sent')", (emp_id, month))
        if cur.rowcount:
            sent.append(emp_id)
    conn.commit()
    return sent


def explain(conn, ts, day, reason, proposed_in=None, proposed_out=None):
    _require(ts, "sent", "returned")
    if not reason:
        raise ServiceError("Hãy nhập lý do giải trình.")
    if not day.startswith(ts["month"]):
        raise ServiceError("Ngày không thuộc tháng của bảng công.")
    for t in (proposed_in, proposed_out):
        if t:
            try:
                datetime.strptime(t, "%H:%M")
            except ValueError:
                raise ServiceError("Giờ đề nghị không hợp lệ.")
    conn.execute(
        "INSERT INTO timesheet_explanations (timesheet_id, day, reason, proposed_in, proposed_out) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT (timesheet_id, day) DO UPDATE SET reason = excluded.reason, "
        "proposed_in = excluded.proposed_in, proposed_out = excluded.proposed_out, "
        "status = 'pending', reply = NULL",
        (ts["id"], day, reason, proposed_in or None, proposed_out or None),
    )
    conn.commit()


def remove_explanation(conn, ts, day):
    _require(ts, "sent", "returned")
    conn.execute("DELETE FROM timesheet_explanations WHERE timesheet_id = ? AND day = ?", (ts["id"], day))
    conn.commit()


def submit(conn, ts, note=None):
    """Nhân viên xác nhận bảng công (kèm giải trình nếu có) và gửi cấp trên duyệt."""
    _require(ts, "sent", "returned")
    conn.execute("UPDATE timesheets SET status = 'submitted', employee_note = ?, "
                 "submitted_at = datetime('now', 'localtime') WHERE id = ?", (note, ts["id"]))
    conn.commit()


def review_explanation(conn, ts, day, accept, reply, cfg):
    """Cấp trên chấp nhận / từ chối giải trình. Chấp nhận kèm giờ đề nghị -> thêm chấm công."""
    _require(ts, "submitted")
    x = conn.execute("SELECT * FROM timesheet_explanations WHERE timesheet_id = ? AND day = ?",
                     (ts["id"], day)).fetchone()
    if x is None:
        raise ServiceError("Không tìm thấy giải trình.")
    if accept:
        emp = conn.execute("SELECT * FROM employees WHERE id = ?", (ts["employee_id"],)).fetchone()
        for t in (x["proposed_in"], x["proposed_out"]):
            if t:
                when = datetime.strptime(f"{day} {t}", "%Y-%m-%d %H:%M")
                services.record_scan(conn, emp, "manual", cfg, now=when,
                                     note=f"Giải trình: {x['reason']}"[:200])
    conn.execute("UPDATE timesheet_explanations SET status = ?, reply = ? WHERE id = ?",
                 ("accepted" if accept else "rejected", reply or None, x["id"]))
    conn.commit()


def return_to_employee(conn, ts, note):
    _require(ts, "submitted")
    if not note:
        raise ServiceError("Hãy ghi lý do trả lại để nhân viên biết cần sửa gì.")
    conn.execute("UPDATE timesheets SET status = 'returned', manager_note = ? WHERE id = ?", (note, ts["id"]))
    conn.commit()


def confirm(conn, employee_id, month, user, cfg, note=None, today=None, force=False):
    """Chốt công. Cấp trên chỉ chốt được bảng công nhân viên đã gửi duyệt;
    admin (force=True) chốt được ở mọi trạng thái chưa chốt."""
    first = services.parse_month(month)
    if not services.month_ended(month, today):
        raise ServiceError("Chỉ chốt được tháng đã kết thúc.")
    ts = get(conn, employee_id, month)
    if ts and ts["status"] == "confirmed":
        raise ServiceError("Bảng công tháng này đã được chốt.")
    if not force:
        _require(ts, "submitted")
    if ts:
        pending = conn.execute("SELECT COUNT(*) FROM timesheet_explanations WHERE timesheet_id = ? "
                               "AND status = 'pending'", (ts["id"],)).fetchone()[0]
        if pending and not force:
            raise ServiceError(f"Còn {pending} giải trình chưa xử lý.")
    rows = services.monthly_report(conn, first.year, first.month, cfg, employee_id=employee_id)
    if not rows:
        raise ServiceError("Nhân viên không có dữ liệu trong tháng.")
    data = json.dumps({k: rows[0][k] for k in services.TIMESHEET_FIELDS})
    if ts:
        conn.execute("UPDATE timesheets SET status = 'confirmed', data = ?, confirmed_by = ?, "
                     "confirmed_at = datetime('now', 'localtime'), manager_note = COALESCE(?, manager_note) "
                     "WHERE id = ?", (data, user["id"], note, ts["id"]))
    else:
        conn.execute("INSERT INTO timesheets (employee_id, month, status, data, confirmed_by, confirmed_at, "
                     "manager_note) VALUES (?, ?, 'confirmed', ?, ?, datetime('now', 'localtime'), ?)",
                     (employee_id, month, data, user["id"], note))
    conn.commit()


def reopen(conn, ts):
    """Mở lại bảng công đã chốt: quay về chờ cấp trên duyệt, dữ liệu tháng hết bị khoá."""
    _require(ts, "confirmed")
    conn.execute("UPDATE timesheets SET status = 'submitted', data = NULL, confirmed_by = NULL, "
                 "confirmed_at = NULL WHERE id = ?", (ts["id"],))
    conn.commit()


# ---------------------------------------------------------------- dữ liệu trang chi tiết

def detail(conn, employee_id, month, cfg):
    first = services.parse_month(month)
    last = date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])
    days = services.employee_period(conn, employee_id, first, last, cfg)
    report = services.monthly_report(conn, first.year, first.month, cfg, employee_id=employee_id)
    live = {k: report[0][k] for k in services.TIMESHEET_FIELDS} if report else None
    ts = get(conn, employee_id, month)
    return {
        "days": days,
        "live": live,
        "summary": ts["data"] if ts and ts["data"] else live,
        "timesheet": ts,
        "explanations": explanations(conn, ts["id"]) if ts else {},
        "flagged": [d for d in days if d["status"] in FLAGGED],
    }


# ---------------------------------------------------------------- sơ đồ quanh một nhân viên

def org_around(conn, employee_id):
    """Chuỗi cấp trên (từ cao xuống cấp trên trực tiếp) và cấp dưới trực thuộc của một nhân viên.

    Cùng quy tắc với người duyệt bảng công (reviewer_id): cấp trên trực tiếp là trưởng phòng
    của phòng mình; trưởng phòng thì báo cáo trưởng phòng cấp trên.
    """
    rows = conn.execute(
        "SELECT e.*, d.name AS department FROM employees e "
        "LEFT JOIN departments d ON d.id = e.department_id WHERE e.status = 'active' OR e.id = ?",
        (employee_id,),
    ).fetchall()
    by_id = {e["id"]: e for e in rows}
    boss_of = {e["id"]: reviewer_id(conn, e) for e in rows}
    chain, cur, seen = [], employee_id, {employee_id}
    while boss_of.get(cur) and boss_of[cur] not in seen and boss_of[cur] in by_id:
        cur = boss_of[cur]
        seen.add(cur)
        chain.insert(0, by_id[cur])
    reports = {}
    for eid, boss in boss_of.items():
        if boss and by_id[eid]["status"] == "active":
            reports.setdefault(boss, []).append(by_id[eid])
    # cấp dưới là trưởng phòng (có người dưới quyền) xếp trước
    subs = sorted(reports.get(employee_id, []),
                  key=lambda e: (-len(reports.get(e["id"], [])), e["code"]))
    return {"chain": chain, "subs": subs,
            "sub_counts": {e["id"]: len(reports.get(e["id"], [])) for e in subs}}
