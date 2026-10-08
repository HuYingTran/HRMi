"""Lịch làm việc: giờ làm, ca làm việc, ngày lễ (nghỉ hoán đổi, làm bù), quy định OT và phép.

- Ngày lễ lưu ở bảng `holidays`; ca làm việc ở bảng `shifts`.
- Giờ làm mặc định lưu ở `settings` với khoá `sched.<KHOÁ>` (không có thì lấy biến môi trường HRM_*).
- Quy định OT / phép lưu ở `settings` với khoá `rule.<tên>`.
"""
from datetime import date, datetime

from . import calendar_vn

HOLIDAY_KINDS = {
    "holiday": "Nghỉ lễ (hưởng lương)",
    "off": "Nghỉ hoán đổi (không tính công)",
    "makeup": "Làm bù",
}

# Loại nghỉ cấu hình được hưởng lương hay không và số ngày tối đa mỗi đơn (0 = không giới hạn).
# Mặc định theo Điều 115 BLLĐ 2019: kết hôn 3 ngày, con kết hôn 1 ngày, tang 3 ngày hưởng nguyên lương;
# nghỉ ốm, thai sản do BHXH chi trả.
LEAVE_POLICY = {
    "sick": (False, 0),
    "wedding": (True, 3),
    "child_wedding": (True, 1),
    "bereavement": (True, 3),
    "maternity": (False, 0),
    "other": (True, 0),
}

# key: (nhãn, mặc định, kiểu, giới hạn)
RULES = {
    "ot_weekday": ("Ngày thường", 150, int, (100, 1000)),
    "ot_weekend": ("Ngày nghỉ hằng tuần", 200, int, (100, 1000)),
    "ot_holiday": ("Ngày lễ, Tết", 300, int, (100, 1000)),
    "ot_night": ("Cộng thêm cho giờ làm đêm (22:00–06:00)", 30, int, (0, 500)),
    "ot_min_minutes": ("Ngày thường: ở lại sau giờ tan ca tối thiểu (phút) mới tính OT", 30, int, (0, 600)),
    "ot_approval": ("OT cần đơn đăng ký được duyệt", "weekday", str, ("none", "weekday", "all")),
    "ot_limit_month": ("Trần OT mỗi tháng (giờ)", 40, int, (0, 1000)),
    "ot_limit_year": ("Trần OT mỗi năm (giờ)", 200, int, (0, 5000)),
    "req_limit_month": ("Số đơn đi muộn / về sớm tối đa mỗi tháng (0 = không giới hạn)", 0, int, (0, 100)),
    # phép năm
    "leave_accrual": ("Cách cấp phép năm", "year", str, ("year", "month")),
    "leave_prorate": ("Người vào làm trong năm được phép theo tỉ lệ số tháng làm việc", True, bool, None),
    "leave_seniority": ("Cộng 1 ngày phép cho mỗi 5 năm thâm niên", True, bool, None),
    "leave_carry_max": ("Số ngày phép tồn tối đa được chuyển sang năm sau (0 = không chuyển)", 0, float, (0, 60)),
    "leave_carry_expiry": ("Phép chuyển sang phải dùng trước ngày (tháng-ngày)", "03-31", "mmdd", None),
    **{f"leave_paid_{t}": ("Hưởng lương", paid, bool, None) for t, (paid, _m) in LEAVE_POLICY.items()},
    **{f"leave_max_{t}": ("Tối đa mỗi đơn (ngày)", mx, float, (0, 365)) for t, (_p, mx) in LEAVE_POLICY.items()},
}
OT_KEYS = ("ot_weekday", "ot_weekend", "ot_holiday", "ot_night", "ot_min_minutes", "ot_approval",
           "ot_limit_month", "ot_limit_year", "req_limit_month")
LEAVE_KEYS = tuple(k for k in RULES if k.startswith("leave_"))
LEAVE_ACCRUAL = {
    "year": "Cấp đủ từ đầu năm",
    "month": "Cộng dồn mỗi tháng (1/12 định mức)",
}
OT_APPROVAL = {
    "none": "Không cần — tự tính theo giờ quét",
    "weekday": "Chỉ OT ngày thường (ngày nghỉ, lễ tự tính)",
    "all": "Mọi loại OT",
}
# loại ngày -> khoá hệ số OT
OT_RATE_KEY = {"work": "ot_weekday", "weekend": "ot_weekend", "holiday": "ot_holiday"}
OT_KINDS = {"work": "Ngày thường", "weekend": "Ngày nghỉ", "holiday": "Ngày lễ"}


class RuleError(Exception):
    pass


# ---------------------------------------------------------------- quy định OT

def _decode(kind, raw):
    if kind is bool:
        return raw == "1"
    if kind == "mmdd":
        return raw
    return kind(raw)


def load_rules(conn):
    out = {k: v[1] for k, v in RULES.items()}
    for r in conn.execute("SELECT key, value FROM settings WHERE key LIKE 'rule.%'"):
        key = r["key"][5:]
        if key in RULES:
            try:
                out[key] = _decode(RULES[key][2], r["value"])
            except ValueError:
                pass
    return out


def _set(conn, key, value):
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                 "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))


def save_rules(conn, form, keys=None):
    """Lưu các quy định `keys` (mặc định: tất cả) từ biểu mẫu. Báo RuleError nếu không hợp lệ."""
    values = {}
    for key in keys or RULES:
        label, _default, kind, limits = RULES[key]
        raw = (form.get(key) or "").strip()
        if kind is bool:
            v = "1" if raw in ("1", "on", "true") else "0"
        elif kind in (int, float):
            try:
                num = kind(raw.replace(",", "."))
            except ValueError:
                raise RuleError(f"{label}: hãy nhập số{' nguyên' if kind is int else ''}.")
            if not limits[0] <= num <= limits[1]:
                raise RuleError(f"{label}: phải từ {limits[0]} đến {limits[1]}.")
            v = str(num)
        elif kind == "mmdd":
            try:
                datetime.strptime(f"2024-{raw}", "%Y-%m-%d")
            except ValueError:
                raise RuleError(f"{label}: nhập dạng tháng-ngày, ví dụ 03-31.")
            v = raw
        else:
            v = raw
            if v not in limits:
                raise RuleError(f"{label}: giá trị không hợp lệ.")
        values[key] = v
    for key, v in values.items():
        _set(conn, f"rule.{key}", v)
    conn.commit()


# ---------------------------------------------------------------- giờ làm việc, ca làm việc

SCHEDULE_KEYS = ("WORK_START", "WORK_END", "LUNCH_START", "LUNCH_END", "LATE_GRACE_MINUTES", "WORK_DAYS")
WEEKDAYS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
SHORT_DAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]


def _hm(value, label):
    try:
        return datetime.strptime((value or "").strip(), "%H:%M").strftime("%H:%M")
    except ValueError:
        raise RuleError(f"{label}: giờ không hợp lệ (HH:MM).")


def validate_schedule(form):
    """Biểu mẫu giờ làm (work_start, work_end, lunch_start, lunch_end, grace_minutes, work_days)
    -> dict khoá SCHEDULE_KEYS đã chuẩn hoá."""
    start, end = _hm(form.get("work_start"), "Giờ vào"), _hm(form.get("work_end"), "Giờ ra")
    ls, le = _hm(form.get("lunch_start"), "Bắt đầu nghỉ trưa"), _hm(form.get("lunch_end"), "Hết nghỉ trưa")
    if end <= start:
        raise RuleError("Giờ ra phải sau giờ vào (chưa hỗ trợ ca qua đêm).")
    if le < ls or ls < start or le > end:
        raise RuleError("Giờ nghỉ trưa phải nằm trong giờ làm việc.")
    try:
        grace = int(form.get("grace_minutes") or 0)
    except ValueError:
        raise RuleError("Phút ân hạn đi muộn phải là số nguyên.")
    if not 0 <= grace <= 120:
        raise RuleError("Phút ân hạn đi muộn phải từ 0 đến 120.")
    raw_days = form.getlist("work_days") if hasattr(form, "getlist") else form.get("work_days", [])
    if isinstance(raw_days, str):
        raw_days = raw_days.split(",")
    days = sorted({int(d) for d in raw_days if str(d).strip().isdigit() and 0 <= int(d) <= 6})
    if not days:
        raise RuleError("Hãy chọn ít nhất một ngày làm việc trong tuần.")
    return {"WORK_START": start, "WORK_END": end, "LUNCH_START": ls, "LUNCH_END": le,
            "LATE_GRACE_MINUTES": grace, "WORK_DAYS": days}


def default_schedule(conn, cfg):
    """Giờ làm mặc định: cấu hình trên web, không có thì lấy biến môi trường."""
    out = {k: cfg[k] for k in SCHEDULE_KEYS}
    for r in conn.execute("SELECT key, value FROM settings WHERE key LIKE 'sched.%'"):
        key = r["key"][6:]
        if key == "WORK_DAYS":
            out[key] = [int(d) for d in r["value"].split(",") if d]
        elif key == "LATE_GRACE_MINUTES":
            out[key] = int(r["value"])
        elif key in SCHEDULE_KEYS:
            out[key] = r["value"]
    out["SHIFT_NAME"] = None
    return out


def save_default_schedule(conn, form):
    sched = validate_schedule(form)
    for key, v in sched.items():
        _set(conn, f"sched.{key}", ",".join(map(str, v)) if key == "WORK_DAYS" else str(v))
    conn.commit()


def shift_schedule(row):
    return {"WORK_START": row["work_start"], "WORK_END": row["work_end"],
            "LUNCH_START": row["lunch_start"], "LUNCH_END": row["lunch_end"],
            "LATE_GRACE_MINUTES": row["grace_minutes"],
            "WORK_DAYS": [int(d) for d in row["work_days"].split(",") if d],
            "SHIFT_NAME": row["name"]}


def shifts(conn):
    return conn.execute("SELECT * FROM shifts ORDER BY work_start, name").fetchall()


def save_shift(conn, form, shift_id=None):
    name = (form.get("name") or "").strip()
    if not name:
        raise RuleError("Hãy nhập tên ca.")
    s = validate_schedule(form)
    params = (name[:60], s["WORK_START"], s["WORK_END"], s["LUNCH_START"], s["LUNCH_END"],
              s["LATE_GRACE_MINUTES"], ",".join(map(str, s["WORK_DAYS"])))
    try:
        if shift_id:
            conn.execute("UPDATE shifts SET name = ?, work_start = ?, work_end = ?, lunch_start = ?, "
                         "lunch_end = ?, grace_minutes = ?, work_days = ? WHERE id = ?", (*params, shift_id))
        else:
            conn.execute("INSERT INTO shifts (name, work_start, work_end, lunch_start, lunch_end, "
                         "grace_minutes, work_days) VALUES (?, ?, ?, ?, ?, ?, ?)", params)
    except Exception as exc:  # trùng tên
        if "UNIQUE" in str(exc):
            raise RuleError("Tên ca đã tồn tại.")
        raise
    conn.commit()


def delete_shift(conn, shift_id):
    conn.execute("UPDATE departments SET shift_id = NULL WHERE shift_id = ?", (shift_id,))
    conn.execute("UPDATE employees SET shift_id = NULL WHERE shift_id = ?", (shift_id,))
    conn.execute("DELETE FROM shifts WHERE id = ?", (shift_id,))
    conn.commit()


def schedule_label(s):
    """'08:00–17:00 · T2–T6'"""
    days = s["WORK_DAYS"]
    contiguous = len(days) > 2 and days == list(range(days[0], days[-1] + 1))
    span = (f"{SHORT_DAYS[days[0]]}–{SHORT_DAYS[days[-1]]}" if contiguous
            else ", ".join(SHORT_DAYS[d] for d in days))
    return f"{s['WORK_START']}–{s['WORK_END']} · {span}"


# ---------------------------------------------------------------- lịch làm việc

class WorkCalendar:
    """Phân loại từng ngày: 'work' (đi làm), 'weekend' (nghỉ hằng tuần / hoán đổi), 'holiday' (lễ)."""

    def __init__(self, cfg, holidays=None, rules=None):
        self.work_days = cfg["WORK_DAYS"]
        self.holidays = holidays or {}  # {date: {"name", "kind"}}
        self.rules = {**{k: v[1] for k, v in RULES.items()}, **(rules or {})}

    def kind(self, day):
        h = self.holidays.get(day)
        if h:
            return {"holiday": "holiday", "off": "weekend", "makeup": "work"}[h["kind"]]
        return "work" if day.weekday() in self.work_days else "weekend"

    def is_workday(self, day):
        return self.kind(day) == "work"

    def holiday(self, day):
        return self.holidays.get(day)

    def paid_holiday(self, day):
        """Ngày lễ rơi vào ngày làm việc thường: tính vào công chuẩn và được trả lương."""
        return self.kind(day) == "holiday" and day.weekday() in self.work_days

    def standard_day(self, day):
        """Ngày tính vào công chuẩn."""
        return self.is_workday(day) or self.paid_holiday(day)

    def ot_rate(self, kind):
        return self.rules[OT_RATE_KEY[kind]]


def _holidays(conn):
    return {date.fromisoformat(r["day"]): {"name": r["name"], "kind": r["kind"]}
            for r in conn.execute("SELECT * FROM holidays")}


def work_calendar(conn, cfg):
    """Lịch theo giờ làm mặc định (không gắn với nhân viên cụ thể)."""
    return WorkCalendar({**cfg, **default_schedule(conn, cfg)}, _holidays(conn), load_rules(conn))


class Schedules:
    """Giờ làm của từng nhân viên: ca riêng của nhân viên -> ca của phòng ban (đi ngược lên phòng
    cấp trên) -> giờ làm mặc định. Nạp một lần cho cả trang / báo cáo."""

    def __init__(self, conn, cfg):
        self.cfg = cfg
        self.default = default_schedule(conn, cfg)
        self.shifts = {r["id"]: shift_schedule(r) for r in conn.execute("SELECT * FROM shifts")}
        self.depts = {r["id"]: (r["parent_id"], r["shift_id"])
                      for r in conn.execute("SELECT id, parent_id, shift_id FROM departments")}
        self.holidays = _holidays(conn)
        self.rules = load_rules(conn)
        self._cals = {}

    def schedule_for(self, emp):
        keys = emp.keys() if hasattr(emp, "keys") else ()
        if "shift_id" in keys and emp["shift_id"] in self.shifts:
            return self.shifts[emp["shift_id"]]
        dept, seen = emp["department_id"] if "department_id" in keys else None, set()
        while dept and dept not in seen:
            seen.add(dept)
            parent, shift = self.depts.get(dept, (None, None))
            if shift in self.shifts:
                return self.shifts[shift]
            dept = parent
        return self.default

    def cfg_for(self, emp):
        return {**self.cfg, **self.schedule_for(emp)}

    def cal_for(self, emp):
        sched = self.schedule_for(emp)
        key = tuple(sched["WORK_DAYS"])
        if key not in self._cals:
            self._cals[key] = WorkCalendar({"WORK_DAYS": sched["WORK_DAYS"]}, self.holidays, self.rules)
        return self._cals[key]

    def context(self, emp):
        """(cfg theo ca, lịch) của nhân viên."""
        return self.cfg_for(emp), self.cal_for(emp)


def schedules(conn, cfg):
    return Schedules(conn, cfg)


# ---------------------------------------------------------------- quản lý ngày lễ

def holidays_of_year(conn, year):
    return conn.execute("SELECT * FROM holidays WHERE day LIKE ? ORDER BY day", (f"{year}-%",)).fetchall()


def _ensure_month_open(conn, day):
    month = day.strftime("%Y-%m")
    if conn.execute("SELECT 1 FROM timesheets WHERE month = ? AND status = 'confirmed' LIMIT 1",
                    (month,)).fetchone():
        raise RuleError(f"Tháng {month[5:]}/{month[:4]} đã có bảng công được chốt, "
                        "hãy mở lại trước khi đổi lịch.")


def _parse_day(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise RuleError("Ngày không hợp lệ.")


def save_holiday(conn, day, name, kind, cfg):
    day = _parse_day(day)
    name = (name or "").strip()
    if not name:
        raise RuleError("Hãy nhập tên ngày lễ.")
    if kind not in HOLIDAY_KINDS:
        raise RuleError("Loại ngày không hợp lệ.")
    work_days = default_schedule(conn, cfg)["WORK_DAYS"]
    if kind == "makeup" and day.weekday() in work_days:
        raise RuleError("Ngày làm bù phải là ngày nghỉ hằng tuần.")
    if kind == "off" and day.weekday() not in work_days:
        raise RuleError("Ngày nghỉ hoán đổi phải là ngày làm việc thường.")
    _ensure_month_open(conn, day)
    conn.execute("INSERT INTO holidays (day, name, kind) VALUES (?, ?, ?) "
                 "ON CONFLICT (day) DO UPDATE SET name = excluded.name, kind = excluded.kind",
                 (day.isoformat(), name[:100], kind))
    recount_leaves(conn, cfg, day)
    conn.commit()


def delete_holiday(conn, day, cfg):
    day = _parse_day(day)
    _ensure_month_open(conn, day)
    conn.execute("DELETE FROM holidays WHERE day = ?", (day.isoformat(),))
    recount_leaves(conn, cfg, day)
    conn.commit()


def load_suggested(conn, year, cfg):
    """Thêm các ngày lễ theo luật của năm, bỏ qua ngày đã có.

    Trả về (số ngày thêm mới, các ngày bị bỏ qua vì tháng đã chốt công).
    """
    added, skipped = 0, []
    for day, name in calendar_vn.suggested_holidays(year, default_schedule(conn, cfg)["WORK_DAYS"]):
        if conn.execute("SELECT 1 FROM holidays WHERE day = ?", (day.isoformat(),)).fetchone():
            continue
        try:
            _ensure_month_open(conn, day)
        except RuleError:
            skipped.append(day)
            continue
        conn.execute("INSERT INTO holidays (day, name, kind) VALUES (?, ?, 'holiday')",
                     (day.isoformat(), name))
        added += 1
        recount_leaves(conn, cfg, day)
    conn.commit()
    return added, skipped


def recount_leaves(conn, cfg, day):
    """Tính lại số ngày của các đơn nghỉ còn hiệu lực đi qua `day` sau khi đổi lịch."""
    from .services import count_leave_days  # tránh vòng import
    sch = schedules(conn, cfg)
    for lv in conn.execute(
            "SELECT l.*, e.department_id, e.shift_id FROM leave_requests l "
            "JOIN employees e ON e.id = l.employee_id WHERE l.status IN ('pending', 'approved') "
            "AND l.start_date <= ? AND l.end_date >= ?", (day.isoformat(), day.isoformat())).fetchall():
        days = count_leave_days(date.fromisoformat(lv["start_date"]), date.fromisoformat(lv["end_date"]),
                                lv["half_day"], cfg, sch.cal_for(lv))
        conn.execute("UPDATE leave_requests SET days = ? WHERE id = ?", (days, lv["id"]))

