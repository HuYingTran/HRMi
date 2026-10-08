"""Đơn trong ngày: đi muộn, về sớm, quên chấm công, ra ngoài, đăng ký làm thêm (OT).

- Đi muộn / về sớm được duyệt: ngày đó không tính phút muộn / về sớm.
- Quên chấm công được duyệt: tự thêm lượt chấm thủ công theo giờ trong đơn (huỷ đơn thì gỡ lại).
- Đăng ký OT được duyệt: giờ làm thêm nằm trong khung giờ đăng ký mới được tính
  (khi quy định ot_approval yêu cầu).
- Ra ngoài: ghi nhận để cấp trên nắm, không ảnh hưởng số liệu công.
"""
from datetime import date, datetime

from . import services
from .services import ServiceError
from .workrules import load_rules

REQ_TYPES = {
    "late": "Đi muộn",
    "early": "Về sớm",
    "forgot": "Quên chấm công",
    "out": "Ra ngoài",
    "overtime": "Đăng ký OT",
}
# nhãn hai ô giờ theo loại đơn
TIME_LABELS = {
    "late": ("Giờ dự kiến đến", None),
    "early": (None, "Giờ dự kiến về"),
    "forgot": ("Giờ vào thực tế", "Giờ ra thực tế"),
    "out": ("Từ", "Đến"),
    "overtime": ("Từ", "Đến"),
}
HINTS = {
    "late": "Được duyệt thì ngày này không tính phút đi muộn.",
    "early": "Được duyệt thì ngày này không tính phút về sớm.",
    "forgot": "Được duyệt thì hệ thống tự thêm lượt chấm công theo giờ đã nhập.",
    "out": "Ghi nhận việc ra ngoài trong giờ làm, không ảnh hưởng số liệu công.",
    "overtime": "Chỉ giờ làm nằm trong khung giờ đăng ký mới được tính OT (khi quy định yêu cầu đăng ký).",
}


def _hm(value):
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%H:%M").strftime("%H:%M")
    except ValueError:
        raise ServiceError("Giờ không hợp lệ.")


def _forgot_note(req_id):
    return f"Đơn quên chấm công #{req_id}:"


def create(conn, employee_id, req_type, day, time_from, time_to, reason, cfg, today=None):
    employee = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if employee is None:
        raise ServiceError("Không tìm thấy nhân viên.")
    if req_type not in REQ_TYPES:
        raise ServiceError("Loại đơn không hợp lệ.")
    try:
        day = date.fromisoformat(day) if isinstance(day, str) else day
    except ValueError:
        raise ServiceError("Ngày không hợp lệ.")
    if not isinstance(day, date):
        raise ServiceError("Ngày không hợp lệ.")
    tf, tt = _hm(time_from), _hm(time_to)
    reason = (reason or "").strip()
    if not reason:
        raise ServiceError("Hãy nhập lý do.")
    if req_type == "forgot":
        if not (tf or tt):
            raise ServiceError("Hãy nhập giờ vào và/hoặc giờ ra thực tế.")
        if day > (today or date.today()):
            raise ServiceError("Chỉ tạo đơn quên chấm công cho hôm nay hoặc ngày đã qua.")
    if req_type in ("out", "overtime") and not (tf and tt):
        raise ServiceError("Hãy nhập đủ giờ bắt đầu và kết thúc.")
    if tf and tt and tt <= tf:
        raise ServiceError("Giờ kết thúc phải sau giờ bắt đầu.")

    services.ensure_unlocked(conn, employee_id, day)
    dup = conn.execute(
        "SELECT id FROM attendance_requests WHERE employee_id = ? AND req_type = ? AND day = ? "
        "AND status IN ('pending', 'approved')", (employee_id, req_type, day.isoformat())).fetchone()
    if dup:
        raise ServiceError(f"Đã có đơn {REQ_TYPES[req_type].lower()} #{dup['id']} cho ngày này.")
    if req_type in ("late", "early"):
        limit = load_rules(conn)["req_limit_month"]
        used = conn.execute(
            "SELECT COUNT(*) FROM attendance_requests WHERE employee_id = ? AND req_type IN ('late', 'early') "
            "AND status IN ('pending', 'approved') AND substr(day, 1, 7) = ?",
            (employee_id, day.strftime("%Y-%m"))).fetchone()[0]
        if limit and used >= limit:
            raise ServiceError(f"Đã dùng hết {limit} đơn đi muộn / về sớm của tháng {day:%m/%Y}.")
    cur = conn.execute(
        "INSERT INTO attendance_requests (employee_id, req_type, day, time_from, time_to, reason) "
        "VALUES (?, ?, ?, ?, ?, ?)", (employee_id, req_type, day.isoformat(), tf, tt, reason[:500]))
    conn.commit()
    return cur.lastrowid


def _get(conn, req_id):
    req = conn.execute("SELECT * FROM attendance_requests WHERE id = ?", (req_id,)).fetchone()
    if req is None:
        raise ServiceError("Không tìm thấy đơn.")
    return req


def review(conn, req_id, approve, user, cfg, note=None):
    req = _get(conn, req_id)
    if req["status"] != "pending":
        raise ServiceError("Chỉ duyệt được đơn đang chờ duyệt.")
    services.ensure_unlocked(conn, req["employee_id"], req["day"])
    if approve and req["req_type"] == "forgot":
        emp = conn.execute("SELECT * FROM employees WHERE id = ?", (req["employee_id"],)).fetchone()
        for t in (req["time_from"], req["time_to"]):
            if t:
                when = datetime.strptime(f"{req['day']} {t}", "%Y-%m-%d %H:%M")
                services.record_scan(conn, emp, "manual", cfg, now=when,
                                     note=f"{_forgot_note(req_id)} {req['reason']}"[:200])
    conn.execute(
        "UPDATE attendance_requests SET status = ?, review_note = ?, reviewed_by = ?, "
        "reviewed_at = datetime('now', 'localtime') WHERE id = ?",
        ("approved" if approve else "rejected", note, user["id"] if user else None, req_id))
    conn.commit()


def cancel(conn, req_id):
    req = _get(conn, req_id)
    if req["status"] not in ("pending", "approved"):
        raise ServiceError("Đơn này đã kết thúc, không thể huỷ.")
    services.ensure_unlocked(conn, req["employee_id"], req["day"])
    if req["status"] == "approved" and req["req_type"] == "forgot":
        conn.execute("DELETE FROM attendance_logs WHERE employee_id = ? AND method = 'manual' "
                     "AND substr(note, 1, ?) = ?",
                     (req["employee_id"], len(_forgot_note(req_id)), _forgot_note(req_id)))
    conn.execute("UPDATE attendance_requests SET status = 'cancelled', "
                 "reviewed_at = datetime('now', 'localtime') WHERE id = ?", (req_id,))
    conn.commit()
