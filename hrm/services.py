"""Nghiệp vụ chấm công và nghỉ phép, tách khỏi web để luồng phần cứng dùng chung."""
import calendar
import math
from datetime import date, datetime, time, timedelta

from .workrules import LEAVE_POLICY, OT_RATE_KEY, WorkCalendar, load_rules, schedules

TS_FMT = "%Y-%m-%d %H:%M:%S"

LEAVE_TYPES = {
    "annual": "Phép năm",
    "sick": "Nghỉ ốm",
    "unpaid": "Không lương",
    "business": "Công tác",
    "wedding": "Kết hôn",
    "child_wedding": "Con kết hôn",
    "bereavement": "Tang chế",
    "maternity": "Thai sản",
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
    "holiday": "Nghỉ lễ",
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


def is_workday(day, cfg, cal=None):
    return (cal or WorkCalendar(cfg)).is_workday(day)


def workdays_between(start, end, cfg, cal=None):
    cal = cal or WorkCalendar(cfg)
    days, d = [], start
    while d <= end:
        if cal.is_workday(d):
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
    cfg, cal = schedules(conn, cfg).context(employee)  # giờ làm theo ca của nhân viên
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
        if not cal.is_workday(now.date()):
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


def _shift_hours(first_in, last_out, cfg):
    """Giờ công trong ca (ngày làm việc): chỉ tính phần nằm trong giờ làm việc, trừ nghỉ trưa."""
    start = datetime.combine(first_in.date(), _parse_hm(cfg["WORK_START"]))
    end = datetime.combine(first_in.date(), _parse_hm(cfg["WORK_END"]))
    a, b = max(first_in, start), min(last_out, end)
    return _worked_hours(a, b, cfg) if b > a else 0.0


def _hours(intervals):
    return sum((b - a).total_seconds() for a, b in intervals) / 3600


def _night_hours(a, b):
    """Số giờ của khoảng [a, b] rơi vào ban đêm (22:00 - 06:00)."""
    total, d = 0.0, a.date()
    while d <= b.date():
        for ws, we in ((datetime.combine(d, time(0)), datetime.combine(d, time(6))),
                       (datetime.combine(d, time(22)), datetime.combine(d + timedelta(days=1), time(0)))):
            total += max((min(b, we) - max(a, ws)).total_seconds(), 0)
        d += timedelta(days=1)
    return total / 3600


def _overtime(day, first_in, last_out, kind, cfg, cal, approved):
    """Làm thêm giờ của một ngày: (giờ được tính, giờ đêm trong đó, giờ chờ đăng ký).

    - Ngày làm việc: phần sau giờ tan ca, chỉ tính khi ở lại đủ ot_min_minutes.
    - Ngày nghỉ / lễ: toàn bộ thời gian làm (trừ nghỉ trưa).
    - Loại OT cần đăng ký (rule ot_approval): chỉ tính phần nằm trong khung giờ của đơn
      OT đã duyệt; chưa có đơn thì toàn bộ là giờ chờ đăng ký.
    """
    if first_in is None or last_out is None:
        return 0.0, 0.0, 0.0
    rules = cal.rules
    if kind == "work":
        end = datetime.combine(day, _parse_hm(cfg["WORK_END"]))
        intervals = [(max(first_in, end), last_out)]
        need = rules["ot_approval"] in ("weekday", "all")
    else:
        lunch_start = datetime.combine(day, _parse_hm(cfg["LUNCH_START"]))
        lunch_end = datetime.combine(day, _parse_hm(cfg["LUNCH_END"]))
        intervals = [(first_in, min(last_out, lunch_start)), (max(first_in, lunch_end), last_out)]
        need = rules["ot_approval"] == "all"
    intervals = [(a, b) for a, b in intervals if b > a]
    if kind == "work" and not (need and approved) and _hours(intervals) * 60 < rules["ot_min_minutes"]:
        return 0.0, 0.0, 0.0
    if need:
        if not approved:
            return 0.0, 0.0, round(_hours(intervals), 2)
        ws = datetime.combine(day, _parse_hm(approved["time_from"]))
        we = datetime.combine(day, _parse_hm(approved["time_to"]))
        intervals = [(max(a, ws), min(b, we)) for a, b in intervals]
        intervals = [(a, b) for a, b in intervals if b > a]
    return (round(_hours(intervals), 2), round(sum(_night_hours(a, b) for a, b in intervals), 2), 0.0)


def _approved_requests(conn, start, end, employee_id=None):
    """{employee_id: {date: {req_type: đơn}}} các đơn trong ngày đã duyệt."""
    sql = "SELECT * FROM attendance_requests WHERE status = 'approved' AND day >= ? AND day <= ?"
    params = [start.isoformat(), end.isoformat()]
    if employee_id:
        sql += " AND employee_id = ?"
        params.append(employee_id)
    out = {}
    for row in conn.execute(sql, params):
        out.setdefault(row["employee_id"], {}).setdefault(
            date.fromisoformat(row["day"]), {})[row["req_type"]] = row
    return out


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


def employed(day, hire_date, end_date=None):
    """Ngày `day` có nằm trong thời gian làm việc (từ ngày vào làm tới ngày nghỉ việc) không."""
    iso = day.isoformat()
    return not ((hire_date and iso < hire_date) or (end_date and iso > end_date))


def _end_date(emp):
    return emp["termination_date"] if emp and "termination_date" in emp.keys() else None


def summarize_day(day, timestamps, leave, cfg, today=None, hire_date=None, cal=None, requests=None,
                  end_date=None):
    """Tổng hợp một ngày công của một nhân viên từ danh sách thời điểm quét.

    cal: lịch làm việc (ngày lễ, quy định OT); requests: {loại: đơn} các đơn trong ngày đã duyệt.
    hire_date / end_date: ngày vào làm / nghỉ việc; ngoài khoảng này không tính vắng, không hưởng lễ.
    """
    today = today or date.today()
    cal = cal or WorkCalendar(cfg)
    requests = requests or {}
    kind = cal.kind(day)
    info = {
        "date": day,
        "first_in": None,
        "last_out": None,
        "late_minutes": 0,
        "early_minutes": 0,
        "hours": 0.0,
        "leave": leave,
        "kind": kind,
        "holiday": cal.holiday(day),
        "requests": requests,
        "excused": [],
        "ot_kind": None,
        "ot_hours": 0.0,
        "ot_night_hours": 0.0,
        "ot_pending_hours": 0.0,
        "ot_weighted": 0.0,
    }
    before_hire = not employed(day, hire_date, end_date)
    first_in = timestamps[0] if timestamps else None
    last_out = timestamps[-1] if len(timestamps) > 1 else None
    info["first_in"], info["last_out"] = first_in, last_out
    if timestamps and kind != "work":
        # làm ngày nghỉ / lễ = OT: không tính muộn/về sớm, chỉ tính giờ
        if last_out:
            info["hours"] = _worked_hours(first_in, last_out, cfg)
        info["status"] = "ot"
    elif timestamps:
        late = _late_minutes(first_in, cfg)
        if late and "late" in requests:
            info["excused"].append("late")
            late = 0
        info["late_minutes"] = late
        if last_out:
            early = _early_minutes(last_out, cfg)
            if early and "early" in requests:
                info["excused"].append("early")
                early = 0
            info["early_minutes"] = early
            info["hours"] = _shift_hours(first_in, last_out, cfg)
        if last_out is None and day < today:
            info["status"] = "missing_out"
        elif info["late_minutes"]:
            info["status"] = "late"
        else:
            info["status"] = "present"
    elif kind == "holiday" and not before_hire:
        info["status"] = "holiday"
    elif leave:
        info["status"] = "business" if leave["leave_type"] == "business" else "leave"
    elif kind != "work" or before_hire:
        info["status"] = "off"
    elif day > today or (day == today and datetime.now().time() < _parse_hm(cfg["WORK_START"])):
        info["status"] = "upcoming"
    else:
        info["status"] = "absent"

    if timestamps:
        hours, night, pending = _overtime(day, first_in, last_out, kind, cfg, cal,
                                          requests.get("overtime"))
        info["ot_pending_hours"] = pending
        if hours:
            info.update(ot_kind=kind, ot_hours=hours, ot_night_hours=night,
                        ot_weighted=round((hours * cal.ot_rate(kind) + night * cal.rules["ot_night"]) / 100, 2))
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
    reqs = _approved_requests(conn, day, day)
    sch = schedules(conn, cfg)
    rows = []
    for emp in employees:
        stamps = logs.get(emp["id"], {}).get(day, [])
        leave = _leave_on(leaves.get(emp["id"], []), day)
        ecfg, cal = sch.context(emp)
        rows.append({"employee": emp,
                     **summarize_day(day, stamps, leave, ecfg, hire_date=emp["hire_date"], cal=cal,
                                     requests=reqs.get(emp["id"], {}).get(day))})
    return rows


def employee_period(conn, employee_id, start, end, cfg):
    """Chi tiết từng ngày của một nhân viên trong khoảng thời gian."""
    start, end = _parse_date(start), _parse_date(end)
    emp = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    hire_date = emp["hire_date"] if emp else None
    logs = _logs_by_employee(conn, start, end, employee_id).get(employee_id, {})
    leaves = _approved_leaves(conn, start, end, employee_id).get(employee_id, [])
    reqs = _approved_requests(conn, start, end, employee_id).get(employee_id, {})
    ecfg, cal = schedules(conn, cfg).context(emp or {})
    days, d = [], start
    while d <= end:
        days.append(summarize_day(d, logs.get(d, []), _leave_on(leaves, d), ecfg,
                                  hire_date=hire_date, cal=cal, requests=reqs.get(d), end_date=_end_date(emp)))
        d += timedelta(days=1)
    return days


def attendance_trend(conn, start, end, cfg, today=None):
    """Đếm đúng giờ / đi muộn / công tác / nghỉ phép / vắng cho từng ngày (theo lịch)."""
    start, end = _parse_date(start), _parse_date(end)
    today = today or date.today()
    employees = conn.execute(
        "SELECT id, hire_date, department_id, shift_id FROM employees WHERE status = 'active'").fetchall()
    logs = _logs_by_employee(conn, start, end)
    leaves = _approved_leaves(conn, start, end)
    reqs = _approved_requests(conn, start, end)
    sch = schedules(conn, cfg)
    contexts = {emp["id"]: sch.context(emp) for emp in employees}
    default_cal = sch.cal_for({})
    trend, day = [], start
    while day <= end:
        holiday = default_cal.holiday(day)
        row = {"date": day.isoformat(), "workday": default_cal.is_workday(day), "future": day > today,
               "holiday": holiday["name"] if holiday else None,
               "on_time": 0, "late": 0, "ot": 0, "business": 0, "leave": 0, "absent": 0}
        for emp in employees:
            ecfg, cal = contexts[emp["id"]]
            info = summarize_day(day, logs.get(emp["id"], {}).get(day, []),
                                 _leave_on(leaves.get(emp["id"], []), day), ecfg,
                                 today=today, hire_date=emp["hire_date"], cal=cal,
                                 requests=reqs.get(emp["id"], {}).get(day))
            if info["status"] == "ot":
                row["ot"] += 1
            elif info["first_in"]:
                row["late" if info["late_minutes"] else "on_time"] += 1
            elif info["status"] in ("leave", "business", "absent"):
                row[info["status"]] += 1
        trend.append(row)
        day += timedelta(days=1)
    return trend


def paid_leave_types(rules):
    """Loại nghỉ do công ty trả lương (cấu hình ở Quy định công). Nghỉ ốm, thai sản mặc định do
    BHXH chi trả nên tính riêng cùng nghỉ không lương."""
    return {"annual"} | {t for t in LEAVE_POLICY if rules[f"leave_paid_{t}"]}


def monthly_report(conn, year, month, cfg, employee_id=None):
    """Tổng hợp công tháng cho từng nhân viên.

    Gồm cả người đã nghỉ việc nhưng còn chấm công trong tháng (cần cho tính lương).
    """
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    return period_report(conn, start, end, cfg, employee_id)


def period_report(conn, start, end, cfg, employee_id=None):
    """Tổng hợp công của từng nhân viên trong khoảng [start, end]."""
    sql = ("SELECT e.*, d.name AS department FROM employees e "
           "LEFT JOIN departments d ON d.id = e.department_id "
           "WHERE (e.status = 'active' OR e.id IN (SELECT employee_id FROM attendance_logs "
           "WHERE ts >= ? AND ts < ?))")
    params = [start.isoformat(), (end + timedelta(days=1)).isoformat()]
    if employee_id:
        sql += " AND e.id = ?"
        params.append(employee_id)
    employees = conn.execute(sql + " ORDER BY e.code", params).fetchall()
    logs = _logs_by_employee(conn, start, end, employee_id)
    leaves = _approved_leaves(conn, start, end, employee_id)
    reqs = _approved_requests(conn, start, end, employee_id)
    sch = schedules(conn, cfg)
    paid_types = paid_leave_types(sch.rules)
    calendar_days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    report = []
    for emp in employees:
        ecfg, cal = sch.context(emp)
        workdays = [d for d in calendar_days if cal.standard_day(d)]
        emp_logs = logs.get(emp["id"], {})
        emp_leaves = leaves.get(emp["id"], [])
        emp_reqs = reqs.get(emp["id"], {})
        row = {
            "employee": emp,
            "workdays": len(workdays),
            "present": 0,
            "late": 0,
            "late_minutes": 0,
            "early_minutes": 0,
            "missing_out": 0,
            "excused": 0,
            "leave_days": 0.0,
            "paid_leave": 0.0,
            "unpaid_leave": 0.0,
            "business": 0.0,
            "holidays": 0,
            "ot_days": 0,
            "ot_hours": 0.0,
            "ot_weekday_hours": 0.0,
            "ot_weekend_hours": 0.0,
            "ot_holiday_hours": 0.0,
            "ot_night_hours": 0.0,
            "ot_weighted_hours": 0.0,
            "ot_pending_hours": 0.0,
            "payable_days": 0.0,
            "absent": 0,
            "hours": 0.0,
        }
        for d in calendar_days:
            info = summarize_day(d, emp_logs.get(d, []), _leave_on(emp_leaves, d), ecfg,
                                 hire_date=emp["hire_date"], cal=cal, requests=emp_reqs.get(d),
                                 end_date=_end_date(emp))
            if info["status"] != "ot" and info["first_in"]:
                row["present"] += 1
                row["payable_days"] += 1  # có đi làm: đủ 1 công, kể cả ngày có đơn nửa ngày
                row["hours"] += info["hours"]
                row["late_minutes"] += info["late_minutes"]
                row["early_minutes"] += info["early_minutes"]
                if info["late_minutes"]:
                    row["late"] += 1
                if info["status"] == "missing_out":
                    row["missing_out"] += 1
            row["excused"] += len(info["excused"])
            if info["ot_hours"]:
                row["ot_days"] += 1
                row["ot_hours"] += info["ot_hours"]
                row[OT_RATE_KEY[info["ot_kind"]] + "_hours"] += info["ot_hours"]
                row["ot_night_hours"] += info["ot_night_hours"]
                row["ot_weighted_hours"] += info["ot_weighted"]
            row["ot_pending_hours"] += info["ot_pending_hours"]
            if cal.paid_holiday(d) and employed(d, emp["hire_date"], _end_date(emp)):
                row["holidays"] += 1
                row["payable_days"] += 1  # nghỉ lễ hưởng nguyên lương, đi làm thì tính thêm OT
            if info["leave"] and cal.is_workday(d):
                n = 0.5 if info["leave"]["half_day"] else 1
                ltype = info["leave"]["leave_type"]
                if ltype == "business":
                    row["business"] += n
                else:
                    row["leave_days"] += n
                    row["paid_leave" if ltype in paid_types else "unpaid_leave"] += n
                if not info["first_in"] and (ltype == "business" or ltype in paid_types):
                    row["payable_days"] += n
            if info["status"] == "absent":
                row["absent"] += 1
        for key in ("hours", "ot_hours", "ot_weekday_hours", "ot_weekend_hours", "ot_holiday_hours",
                    "ot_night_hours", "ot_weighted_hours", "ot_pending_hours"):
            row[key] = round(row[key], 2)
        report.append(row)
    return report


def ot_limits(conn, year, month, rows, cfg):
    """Cảnh báo vượt trần làm thêm: {employee_id: [thông điệp]} cho các dòng báo cáo tháng."""
    rules = load_rules(conn)
    end = date(year, month, calendar.monthrange(year, month)[1])
    ytd = {r["employee"]["id"]: r["ot_hours"]
           for r in period_report(conn, date(year, 1, 1), end, cfg)} if rules["ot_limit_year"] else {}
    out = {}
    for r in rows:
        emp_id, msgs = r["employee"]["id"], []
        if rules["ot_limit_month"] and r["ot_hours"] > rules["ot_limit_month"]:
            msgs.append(f"Vượt trần OT tháng ({r['ot_hours']:g}/{rules['ot_limit_month']}h)")
        if rules["ot_limit_year"] and ytd.get(emp_id, 0) > rules["ot_limit_year"]:
            msgs.append(f"Vượt trần OT năm ({ytd[emp_id]:g}/{rules['ot_limit_year']}h)")
        if msgs:
            out[emp_id] = msgs
    return out


# ---------------------------------------------------------------- Nghỉ phép

def count_leave_days(start, end, half_day, cfg, cal=None):
    days = len(workdays_between(start, end, cfg, cal))
    if half_day:
        return 0.5 if days else 0
    return float(days)


def _days_within(lv, start, end, cfg, cal):
    """Số ngày làm việc của đơn nghỉ `lv` nằm trong khoảng [start, end]."""
    a = max(_parse_date(lv["start_date"]), start)
    b = min(_parse_date(lv["end_date"]), end)
    return count_leave_days(a, b, lv["half_day"], cfg, cal) if b >= a else 0.0


def _months_worked(employee, year, upto=12):
    """Số tháng làm việc trong năm tính tới tháng `upto` (vào làm sau ngày 15 thì từ tháng sau,
    nghỉ việc trước ngày 15 thì không tính tháng đó)."""
    first = 1
    if employee["hire_date"]:
        hire = _parse_date(employee["hire_date"])
        if hire.year > year:
            return 0
        if hire.year == year:
            first = hire.month + (1 if hire.day > 15 else 0)
    end = _end_date(employee)
    if end:
        end = _parse_date(end)
        if end.year < year:
            return 0
        if end.year == year:
            upto = min(upto, end.month - (1 if end.day < 15 else 0))
    return max(0, upto - first + 1)


def leave_entitlement(employee, year, rules, today=None):
    """Định mức phép năm: định mức gốc + thâm niên, theo tỉ lệ / cộng dồn nếu cấu hình."""
    today = today or date.today()
    base = float(employee["annual_leave_days"])
    seniority = 0
    if rules["leave_seniority"] and employee["hire_date"]:
        hire = _parse_date(employee["hire_date"])
        full_years = year - hire.year - (0 if (hire.month, hire.day) == (1, 1) else 1)  # tính tới 1/1
        seniority = max(full_years, 0) // 5
    full = base + seniority
    months = _months_worked(employee, year)
    if rules["leave_accrual"] == "month":
        upto = 12 if year < today.year else 0 if year > today.year else today.month
        earned = round(full * _months_worked(employee, year, upto) / 12, 2)
    elif rules["leave_prorate"] and months < 12:
        earned = float(math.floor(full * months / 12 + 0.5))  # làm tròn theo Điều 66 NĐ 145/2020
    else:
        earned = full
    return {"base": base, "seniority": seniority, "full": full, "earned": earned, "months": months}


def leave_balance(conn, employee, year, cfg, today=None):
    """Phép năm: định mức, chuyển từ năm trước, điều chỉnh, đã dùng, đang chờ duyệt, còn lại."""
    return _balance(conn, employee, year, schedules(conn, cfg), today or date.today(), 0)


def _carry_in(conn, employee, year, sch, depth):
    """Phép tồn năm trước được chuyển sang (chỉ khi năm trước nhân viên đã có dữ liệu chấm công)."""
    limit = sch.rules["leave_carry_max"]
    prev = year - 1
    if not limit or depth >= 3:
        return 0.0
    if employee["hire_date"] and _parse_date(employee["hire_date"]).year > prev:
        return 0.0
    first = conn.execute("SELECT MIN(ts) FROM attendance_logs WHERE employee_id = ?",
                         (employee["id"],)).fetchone()[0]
    if not first or int(first[:4]) > prev:
        return 0.0
    left = _balance(conn, employee, prev, sch, date(prev, 12, 31), depth + 1)["remaining"]
    return float(min(limit, max(left, 0)))


def _balance(conn, employee, year, sch, today, depth):
    ecfg, cal = sch.context(employee)
    rules = sch.rules
    ent = leave_entitlement(employee, year, rules, today)
    adjust = conn.execute("SELECT COALESCE(SUM(days), 0) FROM leave_adjustments WHERE employee_id = ? "
                          "AND year = ?", (employee["id"], year)).fetchone()[0]
    carry_in = _carry_in(conn, employee, year, sch, depth)
    month, day = (int(x) for x in rules["leave_carry_expiry"].split("-"))
    expiry = date(year, month, day)
    y0, y1 = date(year, 1, 1), date(year, 12, 31)
    used = pending = used_early = 0.0
    for lv in conn.execute(
            "SELECT * FROM leave_requests WHERE employee_id = ? AND leave_type = 'annual' "
            "AND status IN ('approved', 'pending') AND start_date <= ? AND end_date >= ?",
            (employee["id"], y1.isoformat(), y0.isoformat())):
        n = _days_within(lv, y0, y1, ecfg, cal)
        if lv["status"] == "approved":
            used += n
            if carry_in:
                used_early += _days_within(lv, y0, expiry, ecfg, cal)
        else:
            pending += n
    carry_used = min(carry_in, used_early)
    carry_expired = carry_in - carry_used if today > expiry else 0.0
    quota = ent["earned"] + adjust + carry_in
    remaining = quota - carry_expired - used
    return {
        **ent,
        "adjust": adjust,
        "carry_in": carry_in,
        "carry_left": carry_in - carry_used - carry_expired,
        "carry_expired": carry_expired,
        "carry_expiry": expiry,
        "quota": quota,
        "used": used,
        "pending": pending,
        "remaining": remaining,
        "available": remaining - pending,
        "accrual": rules["leave_accrual"],
    }


def adjust_leave(conn, employee_id, year, days, note, user_id=None):
    """Cộng / trừ thủ công số ngày phép năm (vd. thưởng phép, trừ phép nghỉ quá)."""
    try:
        days = float(str(days).replace(",", "."))
    except ValueError:
        raise ServiceError("Số ngày điều chỉnh không hợp lệ.")
    if not days or abs(days) > 60:
        raise ServiceError("Số ngày điều chỉnh phải khác 0 và không quá 60.")
    note = (note or "").strip()
    if not note:
        raise ServiceError("Hãy ghi lý do điều chỉnh.")
    conn.execute("INSERT INTO leave_adjustments (employee_id, year, days, note, created_by) "
                 "VALUES (?, ?, ?, ?, ?)", (employee_id, year, days, note[:200], user_id))
    conn.commit()


def create_leave(conn, employee_id, leave_type, start, end, half_day, reason, cfg, today=None):
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
    if (end - start).days > 366:
        raise ServiceError("Đơn nghỉ dài quá một năm, hãy tách thành nhiều đơn.")
    sch = schedules(conn, cfg)
    ecfg, cal = sch.context(employee)
    days = count_leave_days(start, end, half_day, ecfg, cal)
    if days <= 0:
        raise ServiceError("Khoảng thời gian đã chọn không có ngày làm việc nào.")
    limit = sch.rules.get(f"leave_max_{leave_type}")
    if limit and days > limit:
        raise ServiceError(f"Nghỉ {LEAVE_TYPES[leave_type].lower()} tối đa {limit:g} ngày mỗi đơn, "
                           f"đơn này {days:g} ngày.")

    ensure_unlocked(conn, employee_id, start, end)
    overlap = conn.execute(
        "SELECT id FROM leave_requests WHERE employee_id = ? "
        "AND status IN ('pending', 'approved') AND start_date <= ? AND end_date >= ?",
        (employee_id, end.isoformat(), start.isoformat()),
    ).fetchone()
    if overlap:
        raise ServiceError(f"Trùng với đơn nghỉ #{overlap['id']} đã có.")

    if leave_type == "annual":
        # đơn qua năm: mỗi phần trừ vào phép của năm đó
        lv = {"start_date": start.isoformat(), "end_date": end.isoformat(), "half_day": half_day}
        for year in range(start.year, end.year + 1):
            need = _days_within(lv, date(year, 1, 1), date(year, 12, 31), ecfg, cal)
            balance = _balance(conn, employee, year, sch, today or date.today(), 0)
            if need > balance["available"]:
                raise ServiceError(
                    f"Không đủ phép năm {year}: còn {balance['available']:g} ngày khả dụng, "
                    f"đơn cần {need:g} ngày."
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
                    "excused", "business", "paid_leave", "unpaid_leave", "holidays", "absent", "hours",
                    "ot_days", "ot_hours", "ot_weekday_hours", "ot_weekend_hours", "ot_holiday_hours",
                    "ot_night_hours", "ot_weighted_hours", "ot_pending_hours", "payable_days")


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
    if row.get("ot_pending_hours"):
        out.append(f"OT chưa duyệt {row['ot_pending_hours']:g}h")
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
