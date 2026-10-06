"""Nghiệp vụ chấm công và nghỉ phép, tách khỏi web để luồng phần cứng dùng chung."""
import calendar
from datetime import date, datetime, time, timedelta

TS_FMT = "%Y-%m-%d %H:%M:%S"

LEAVE_TYPES = {
    "annual": "Phép năm",
    "sick": "Nghỉ ốm",
    "unpaid": "Không lương",
    "business": "Công tác",
    "other": "Khác",
}
LEAVE_STATUSES = {
    "pending": "Chờ duyệt",
    "approved": "Đã duyệt",
    "rejected": "Từ chối",
    "cancelled": "Đã huỷ",
}
DAY_STATUSES = {
    "present": "Đúng giờ",
    "late": "Đi muộn",
    "missing_out": "Thiếu giờ ra",
    "leave": "Nghỉ phép",
    "business": "Công tác",
    "ot": "Làm thêm (OT)",
    "absent": "Vắng",
    "off": "Ngày nghỉ",
    "upcoming": "—",
}


class ServiceError(Exception):
    """Lỗi nghiệp vụ, thông điệp hiển thị được cho người dùng."""


def _parse_hm(value):
    h, m = value.split(":")
    return time(int(h), int(m))


def _parse_date(value):
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def is_workday(day, cfg):
    return day.weekday() in cfg["WORK_DAYS"]


def workdays_between(start, end, cfg):
    days, d = [], start
    while d <= end:
        if is_workday(d, cfg):
            days.append(d)
        d += timedelta(days=1)
    return days


# ---------------------------------------------------------------- Nhân viên

def find_employee_by_rfid(conn, uid):
    return conn.execute(
        "SELECT * FROM employees WHERE rfid_uid = ? AND status = 'active'", (uid,)
    ).fetchone()


def find_employee_by_fingerprint(conn, slot):
    return conn.execute(
        "SELECT * FROM employees WHERE fingerprint_id = ? AND status = 'active'", (slot,)
    ).fetchone()


# ---------------------------------------------------------------- Chấm công

PRESENCE = {
    "in": "Đang ở công ty",
    "out": "Đã checkout",
    "business": "Đi công tác",
    "leave": "Nghỉ phép",
    "absent": "Chưa đến",
}


def presence_map(conn, day=None):
    """Trạng thái hiện tại của từng nhân viên có dữ liệu hôm nay.

    Lượt quét được ưu tiên: số lượt lẻ (vào - ra - vào...) là đang ở công ty, chẵn là đã
    checkout. Chưa quét thì xét đơn công tác / nghỉ đã duyệt. Ai không có trong kết quả
    là "absent" (chưa đến).
    """
    day = (day or date.today()).isoformat()
    state = {}
    for row in conn.execute(
        "SELECT employee_id, leave_type FROM leave_requests WHERE status = 'approved' "
        "AND start_date <= ? AND end_date >= ?", (day, day)
    ):
        state[row["employee_id"]] = "business" if row["leave_type"] == "business" else "leave"
    for emp_id, n in conn.execute(
        "SELECT employee_id, COUNT(*) FROM attendance_logs WHERE ts LIKE ? GROUP BY employee_id",
        (day + "%",),
    ):
        state[emp_id] = "in" if n % 2 else "out"
    return state


def record_scan(conn, employee, method, cfg, now=None, note=None):
    """Ghi một lần chấm công.

    Lần quét đầu tiên trong ngày là giờ vào, các lần sau được tính là giờ ra
    (lấy lần cuối cùng). Quét lặp lại trong SCAN_COOLDOWN_SECONDS bị bỏ qua.
    Trả về dict mô tả kết quả để hiển thị lên kiosk.
    """
    now = (now or datetime.now()).replace(microsecond=0)
    day = now.strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT ts FROM attendance_logs WHERE employee_id = ? AND ts LIKE ? ORDER BY ts",
        (employee["id"], day + "%"),
    ).fetchall()

    result = {
        "employee_id": employee["id"],
        "code": employee["code"],
        "name": employee["full_name"],
        "method": method,
        "time": now.strftime("%H:%M:%S"),
    }

    # Chỉ xét các lượt trước (hoặc đúng) thời điểm quét: có thể đã có lượt thủ công nhập trước
    # với giờ muộn hơn, lượt đó không được làm lượt quét thật bị coi là quét lặp.
    prior = [datetime.strptime(r["ts"], TS_FMT) for r in rows]
    prior = [t for t in prior if t <= now]
    if prior and method != "manual":
        if (now - prior[-1]).total_seconds() < cfg["SCAN_COOLDOWN_SECONDS"]:
            result["type"] = "duplicate"
            return result

    conn.execute(
        "INSERT INTO attendance_logs (employee_id, ts, method, note) VALUES (?, ?, ?, ?)",
        (employee["id"], now.strftime(TS_FMT), method, note),
    )
    conn.commit()

    if not prior:
        result["type"] = "check_in"
        if not is_workday(now.date(), cfg):
            result["ot"] = True
        elif _late_minutes(now, cfg):
            result["late_minutes"] = _late_minutes(now, cfg)
    else:
        result["type"] = "check_out"
    return result


def _late_minutes(first_in, cfg):
    start = datetime.combine(first_in.date(), _parse_hm(cfg["WORK_START"]))
    minutes = int((first_in - start).total_seconds() // 60)
    return minutes if minutes > cfg["LATE_GRACE_MINUTES"] else 0


def _early_minutes(last_out, cfg):
    end = datetime.combine(last_out.date(), _parse_hm(cfg["WORK_END"]))
    minutes = int((end - last_out).total_seconds() // 60)
    return max(minutes, 0)


def _worked_hours(first_in, last_out, cfg):
    total = (last_out - first_in).total_seconds()
    lunch_start = datetime.combine(first_in.date(), _parse_hm(cfg["LUNCH_START"]))
    lunch_end = datetime.combine(first_in.date(), _parse_hm(cfg["LUNCH_END"]))
    overlap = (min(last_out, lunch_end) - max(first_in, lunch_start)).total_seconds()
    total -= max(overlap, 0)
    return round(max(total, 0) / 3600, 2)


def _approved_leaves(conn, start, end, employee_id=None):
    sql = (
        "SELECT * FROM leave_requests WHERE status = 'approved' "
        "AND start_date <= ? AND end_date >= ?"
    )
    params = [end.isoformat(), start.isoformat()]
    if employee_id:
        sql += " AND employee_id = ?"
        params.append(employee_id)
    leaves = {}
    for row in conn.execute(sql, params):
        leaves.setdefault(row["employee_id"], []).append(row)
    return leaves


def _leave_on(leaves, day):
    iso = day.isoformat()
    for lv in leaves:
        if lv["start_date"] <= iso <= lv["end_date"]:
            return lv
    return None


def summarize_day(day, timestamps, leave, cfg, today=None, hire_date=None):
    """Tổng hợp một ngày công của một nhân viên từ danh sách thời điểm quét."""
    today = today or date.today()
    info = {
        "date": day,
        "first_in": None,
        "last_out": None,
        "late_minutes": 0,
        "early_minutes": 0,
        "hours": 0.0,
        "leave": leave,
    }
    if timestamps and not is_workday(day, cfg):
        # làm ngày nghỉ = OT: không tính muộn/về sớm, chỉ tính giờ
        info["first_in"] = timestamps[0]
        if len(timestamps) > 1:
            info["last_out"] = timestamps[-1]
            info["hours"] = _worked_hours(timestamps[0], timestamps[-1], cfg)
        info["status"] = "ot"
    elif timestamps:
        first_in = timestamps[0]
        info["first_in"] = first_in
        info["late_minutes"] = _late_minutes(first_in, cfg)
        if len(timestamps) > 1:
            last_out = timestamps[-1]
            info["last_out"] = last_out
            info["early_minutes"] = _early_minutes(last_out, cfg)
            info["hours"] = _worked_hours(first_in, last_out, cfg)
        if info["last_out"] is None and day < today:
            info["status"] = "missing_out"
        elif info["late_minutes"]:
            info["status"] = "late"
        else:
            info["status"] = "present"
    elif leave:
        info["status"] = "business" if leave["leave_type"] == "business" else "leave"
    elif not is_workday(day, cfg) or (hire_date and day.isoformat() < hire_date):
        info["status"] = "off"
    elif day > today or (day == today and datetime.now().time() < _parse_hm(cfg["WORK_START"])):
        info["status"] = "upcoming"
    else:
        info["status"] = "absent"
    return info


def _logs_by_employee(conn, start, end, employee_id=None):
    sql = "SELECT employee_id, ts FROM attendance_logs WHERE ts >= ? AND ts < ?"
    params = [start.isoformat(), (end + timedelta(days=1)).isoformat()]
    if employee_id:
        sql += " AND employee_id = ?"
        params.append(employee_id)
    data = {}
    for row in conn.execute(sql + " ORDER BY ts", params):
        ts = datetime.strptime(row["ts"], TS_FMT)
        data.setdefault(row["employee_id"], {}).setdefault(ts.date(), []).append(ts)
    return data


def daily_attendance(conn, day, cfg):
    """Bảng chấm công một ngày cho toàn bộ nhân viên đang làm việc."""
    day = _parse_date(day)
    employees = conn.execute(
        "SELECT e.*, d.name AS department FROM employees e "
        "LEFT JOIN departments d ON d.id = e.department_id "
        "WHERE e.status = 'active' ORDER BY e.code"
    ).fetchall()
    logs = _logs_by_employee(conn, day, day)
    leaves = _approved_leaves(conn, day, day)
    rows = []
    for emp in employees:
        stamps = logs.get(emp["id"], {}).get(day, [])
        leave = _leave_on(leaves.get(emp["id"], []), day)
        rows.append({"employee": emp,
                     **summarize_day(day, stamps, leave, cfg, hire_date=emp["hire_date"])})
    return rows


def employee_period(conn, employee_id, start, end, cfg):
    """Chi tiết từng ngày của một nhân viên trong khoảng thời gian."""
    start, end = _parse_date(start), _parse_date(end)
    hire = conn.execute("SELECT hire_date FROM employees WHERE id = ?", (employee_id,)).fetchone()
    hire_date = hire["hire_date"] if hire else None
    logs = _logs_by_employee(conn, start, end, employee_id).get(employee_id, {})
    leaves = _approved_leaves(conn, start, end, employee_id).get(employee_id, [])
    days, d = [], start
    while d <= end:
        days.append(summarize_day(d, logs.get(d, []), _leave_on(leaves, d), cfg,
                                  hire_date=hire_date))
        d += timedelta(days=1)
    return days


def attendance_trend(conn, start, end, cfg, today=None):
    """Đếm đúng giờ / đi muộn / công tác / nghỉ phép / vắng cho từng ngày (theo lịch)."""
    start, end = _parse_date(start), _parse_date(end)
    today = today or date.today()
    employees = conn.execute(
        "SELECT id, hire_date FROM employees WHERE status = 'active'").fetchall()
    logs = _logs_by_employee(conn, start, end)
    leaves = _approved_leaves(conn, start, end)
    trend, day = [], start
    while day <= end:
        row = {"date": day.isoformat(), "workday": is_workday(day, cfg), "future": day > today,
               "on_time": 0, "late": 0, "ot": 0, "business": 0, "leave": 0, "absent": 0}
        for emp in employees:
            info = summarize_day(day, logs.get(emp["id"], {}).get(day, []),
                                 _leave_on(leaves.get(emp["id"], []), day), cfg,
                                 today=today, hire_date=emp["hire_date"])
            if info["status"] == "ot":
                row["ot"] += 1
            elif info["first_in"]:
                row["late" if info["late_minutes"] else "on_time"] += 1
            elif info["status"] in ("leave", "business", "absent"):
                row[info["status"]] += 1
        trend.append(row)
        day += timedelta(days=1)
    return trend


# Nghỉ có lương do công ty trả; nghỉ ốm do BHXH chi trả nên tách riêng cùng nghỉ không lương.
PAID_LEAVE = ("annual", "other")


def monthly_report(conn, year, month, cfg, employee_id=None):
    """Tổng hợp công tháng cho từng nhân viên.

    Gồm cả người đã nghỉ việc nhưng còn chấm công trong tháng (cần cho tính lương).
    """
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    sql = ("SELECT e.*, d.name AS department FROM employees e "
           "LEFT JOIN departments d ON d.id = e.department_id "
           "WHERE (e.status = 'active' OR e.id IN (SELECT employee_id FROM attendance_logs "
           "WHERE ts >= ? AND ts < ?))")
    params = [start.isoformat(), (end + timedelta(days=1)).isoformat()]
    if employee_id:
        sql += " AND e.id = ?"
        params.append(employee_id)
    employees = conn.execute(sql + " ORDER BY e.code", params).fetchall()
    logs = _logs_by_employee(conn, start, end)
    leaves = _approved_leaves(conn, start, end)
    workdays = workdays_between(start, end, cfg)
    report = []
    for emp in employees:
        emp_logs = logs.get(emp["id"], {})
        emp_leaves = leaves.get(emp["id"], [])
        row = {
            "employee": emp,
            "workdays": len(workdays),
            "present": 0,
            "late": 0,
            "late_minutes": 0,
            "early_minutes": 0,
            "missing_out": 0,
            "leave_days": 0.0,
            "paid_leave": 0.0,
            "unpaid_leave": 0.0,
            "business": 0.0,
            "ot_days": 0,
            "ot_hours": 0.0,
            "payable_days": 0.0,
            "absent": 0,
            "hours": 0.0,
        }
        d = start
        while d <= end:
            info = summarize_day(d, emp_logs.get(d, []), _leave_on(emp_leaves, d), cfg,
                                 hire_date=emp["hire_date"])
            if info["status"] == "ot":
                row["ot_days"] += 1
                row["ot_hours"] += info["hours"]
            elif info["first_in"]:
                row["present"] += 1
                row["payable_days"] += 1  # có đi làm: đủ 1 công, kể cả ngày có đơn nửa ngày
                row["hours"] += info["hours"]
                row["late_minutes"] += info["late_minutes"]
                row["early_minutes"] += info["early_minutes"]
                if info["late_minutes"]:
                    row["late"] += 1
                if info["status"] == "missing_out":
                    row["missing_out"] += 1
            if info["leave"] and is_workday(d, cfg):
                n = 0.5 if info["leave"]["half_day"] else 1
                ltype = info["leave"]["leave_type"]
                if ltype == "business":
                    row["business"] += n
                else:
                    row["leave_days"] += n
                    row["paid_leave" if ltype in PAID_LEAVE else "unpaid_leave"] += n
                if not info["first_in"] and (ltype == "business" or ltype in PAID_LEAVE):
                    row["payable_days"] += n
            if info["status"] == "absent":
                row["absent"] += 1
            d += timedelta(days=1)
        row["hours"] = round(row["hours"], 2)
        row["ot_hours"] = round(row["ot_hours"], 2)
        report.append(row)
    return report


# ---------------------------------------------------------------- Nghỉ phép

def count_leave_days(start, end, half_day, cfg):
    days = len(workdays_between(start, end, cfg))
    if half_day:
        return 0.5 if days else 0
    return float(days)


def leave_balance(conn, employee, year):
    """Phép năm: định mức, đã dùng, đang chờ duyệt, còn lại."""
    used = pending = 0.0
    for row in conn.execute(
        "SELECT status, days FROM leave_requests WHERE employee_id = ? "
        "AND leave_type = 'annual' AND status IN ('approved', 'pending') "
        "AND substr(start_date, 1, 4) = ?",
        (employee["id"], str(year)),
    ):
        if row["status"] == "approved":
            used += row["days"]
        else:
            pending += row["days"]
    quota = employee["annual_leave_days"]
    return {
        "quota": quota,
        "used": used,
        "pending": pending,
        "remaining": quota - used,
        "available": quota - used - pending,
    }


def create_leave(conn, employee_id, leave_type, start, end, half_day, reason, cfg):
    employee = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if employee is None:
        raise ServiceError("Không tìm thấy nhân viên.")
    if leave_type not in LEAVE_TYPES:
        raise ServiceError("Loại nghỉ không hợp lệ.")
    try:
        start, end = _parse_date(start), _parse_date(end)
    except (TypeError, ValueError):
        raise ServiceError("Ngày không hợp lệ.")
    if end < start:
        raise ServiceError("Ngày kết thúc phải sau hoặc bằng ngày bắt đầu.")
    if half_day and start != end:
        raise ServiceError("Nghỉ nửa ngày chỉ áp dụng khi bắt đầu và kết thúc cùng một ngày.")
    if start.year != end.year:
        raise ServiceError("Đơn nghỉ không được kéo dài sang năm khác, hãy tách thành hai đơn.")
    days = count_leave_days(start, end, half_day, cfg)
    if days <= 0:
        raise ServiceError("Khoảng thời gian đã chọn không có ngày làm việc nào.")

    ensure_unlocked(conn, employee_id, start, end)
    overlap = conn.execute(
        "SELECT id FROM leave_requests WHERE employee_id = ? "
        "AND status IN ('pending', 'approved') AND start_date <= ? AND end_date >= ?",
        (employee_id, end.isoformat(), start.isoformat()),
    ).fetchone()
    if overlap:
        raise ServiceError(f"Trùng với đơn nghỉ #{overlap['id']} đã có.")

    if leave_type == "annual":
        balance = leave_balance(conn, employee, start.year)
        if days > balance["available"]:
            raise ServiceError(
                f"Không đủ phép năm: còn {balance['available']:g} ngày khả dụng, "
                f"đơn cần {days:g} ngày."
            )

    cur = conn.execute(
        "INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, "
        "half_day, days, reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (employee_id, leave_type, start.isoformat(), end.isoformat(),
         1 if half_day else 0, days, reason),
    )
    conn.commit()
    return cur.lastrowid


def review_leave(conn, leave_id, approve, note=None):
    leave = conn.execute("SELECT * FROM leave_requests WHERE id = ?", (leave_id,)).fetchone()
    if leave is None:
        raise ServiceError("Không tìm thấy đơn nghỉ.")
    if leave["status"] != "pending":
        raise ServiceError("Chỉ duyệt được đơn đang chờ duyệt.")
    ensure_unlocked(conn, leave["employee_id"], leave["start_date"], leave["end_date"])
    conn.execute(
        "UPDATE leave_requests SET status = ?, review_note = ?, "
        "reviewed_at = datetime('now', 'localtime') WHERE id = ?",
        ("approved" if approve else "rejected", note, leave_id),
    )
    conn.commit()


def cancel_leave(conn, leave_id):
    leave = conn.execute("SELECT * FROM leave_requests WHERE id = ?", (leave_id,)).fetchone()
    if leave is None:
        raise ServiceError("Không tìm thấy đơn nghỉ.")
    if leave["status"] not in ("pending", "approved"):
        raise ServiceError("Đơn này đã kết thúc, không thể huỷ.")
    ensure_unlocked(conn, leave["employee_id"], leave["start_date"], leave["end_date"])
    conn.execute(
        "UPDATE leave_requests SET status = 'cancelled', "
        "reviewed_at = datetime('now', 'localtime') WHERE id = ?",
        (leave_id,),
    )
    conn.commit()


# ---------------------------------------------------------------- Chốt công

TIMESHEET_FIELDS = ("workdays", "present", "late", "late_minutes", "early_minutes", "missing_out",
                    "business", "paid_leave", "unpaid_leave", "absent", "hours", "ot_days",
                    "ot_hours", "payable_days")


def parse_month(month):
    try:
        year, mon = (int(x) for x in month.split("-"))
        return date(year, mon, 1)
    except (AttributeError, ValueError):
        raise ServiceError("Tháng không hợp lệ.")


def month_ended(month, today=None):
    first = parse_month(month)
    last = date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])
    return last < (today or date.today())


def issues_of(row):
    """Các điểm cần kiểm tra trước khi chốt công."""
    out = []
    if row["missing_out"]:
        out.append(f"Thiếu ra ×{row['missing_out']}")
    if row["absent"]:
        out.append(f"Vắng ×{row['absent']}")
    return out


def ensure_unlocked(conn, employee_id, start, end=None):
    """Báo lỗi nếu khoảng ngày rơi vào tháng đã chốt công của nhân viên."""
    start = _parse_date(start)
    end = _parse_date(end) if end else start
    months, d = set(), start.replace(day=1)
    while d <= end:
        months.add(d.strftime("%Y-%m"))
        d = date(d.year + d.month // 12, d.month % 12 + 1, 1)
    q = ",".join("?" * len(months))
    row = conn.execute(
        f"SELECT month FROM timesheets WHERE employee_id = ? AND status = 'confirmed' "
        f"AND month IN ({q}) ORDER BY month",
        (employee_id, *sorted(months)),
    ).fetchone()
    if row:
        m = row["month"]
        raise ServiceError(f"Tháng {m[5:]}/{m[:4]} đã chốt công, hãy mở lại bảng công trước khi sửa.")
