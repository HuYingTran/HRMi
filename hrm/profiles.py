"""Hồ sơ nhân sự mở rộng: hợp đồng lao động, quá trình công tác, người phụ thuộc, giấy tờ, nghỉ việc.

Trạng thái hợp đồng (hiệu lực, sắp hết hạn, hết hạn...) không lưu mà tính từ ngày khi xem,
giống cách số liệu công được tính từ log. Chỉ việc chấm dứt sớm mới được ghi lại.
"""
import json
import re
import secrets
import shutil
from datetime import date, timedelta
from pathlib import Path

from .services import ServiceError

CONTRACT_TYPES = {
    "probation": "Thử việc",
    "fixed": "Xác định thời hạn",
    "indefinite": "Không xác định thời hạn",
    "seasonal": "Thời vụ",
}
CONTRACT_STATES = {
    "upcoming": "Chưa hiệu lực",
    "active": "Đang hiệu lực",
    "expiring": "Sắp hết hạn",
    "expired": "Hết hạn",
    "terminated": "Đã chấm dứt",
}
# lớp CSS của badge theo trạng thái
STATE_CLASS = {"upcoming": "off", "active": "ok", "expiring": "warn", "expired": "bad", "terminated": "inactive"}
EXPIRING_DAYS = 30
FIXED_MAX_MONTHS = 36      # Điều 20 BLLĐ 2019
PROBATION_MAX_DAYS = 180   # Điều 25 BLLĐ 2019 (người quản lý doanh nghiệp)

HISTORY_KINDS = {
    "hire": "Vào làm",
    "transfer": "Điều chuyển",
    "title": "Đổi chức danh",
    "promotion": "Thăng chức",
    "salary": "Thay đổi lương",
    "termination": "Nghỉ việc",
    "rehire": "Nhận lại làm",
    "other": "Khác",
}
# loại quyết định nhập tay trên trang hồ sơ (các loại còn lại do hệ thống tự ghi)
DECISION_KINDS = ("transfer", "title", "promotion", "salary", "other")

TERMINATION_REASONS = {
    "resign": "Người lao động xin nghỉ",
    "contract_end": "Hết hạn hợp đồng",
    "probation_fail": "Không đạt thử việc",
    "dismissal": "Công ty chấm dứt hợp đồng",
    "retire": "Nghỉ hưu",
    "other": "Lý do khác",
}
HANDOVER = {
    "work": "Bàn giao công việc, hồ sơ",
    "assets": "Thu hồi tài sản, thiết bị",
    "settlement": "Quyết toán lương, phép còn lại",
    "insurance": "Chốt và trả sổ BHXH",
}

MARITAL = ("Độc thân", "Đã kết hôn", "Ly hôn", "Goá")
EDUCATION = ("THCS", "THPT", "Trung cấp", "Cao đẳng", "Đại học", "Thạc sĩ", "Tiến sĩ")
RELATIONS = ("Con", "Vợ", "Chồng", "Cha", "Mẹ", "Anh/chị/em", "Khác")

DOC_KINDS = {
    "id_card": "CCCD / hộ chiếu",
    "degree": "Bằng cấp, chứng chỉ",
    "cv": "Sơ yếu lý lịch",
    "health": "Giấy khám sức khoẻ",
    "contract": "Hợp đồng đã ký",
    "decision": "Quyết định",
    "other": "Khác",
}
DOC_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".doc", ".docx", ".xls", ".xlsx", ".txt"}

# trường hồ sơ mở rộng: thường (ai sửa được hồ sơ là sửa được) và nhạy cảm (cần quyền riêng)
EXTRA_FIELDS = ("hometown", "marital_status", "education",
                "emergency_name", "emergency_relation", "emergency_phone")
SENSITIVE_FIELDS = ("id_number", "id_issue_date", "id_issue_place", "tax_code",
                    "social_insurance_no", "bank_account", "bank_name")

COMPANY_FIELDS = {
    "name": "Tên công ty",
    "address": "Địa chỉ",
    "tax_code": "Mã số thuế",
    "phone": "Điện thoại",
    "representative": "Người đại diện",
    "representative_title": "Chức vụ người đại diện",
    "workplace": "Địa điểm làm việc (in trên hợp đồng)",
}


# ---------------------------------------------------------------- tiện ích

def _date(value, label, required=False):
    value = (value or "").strip()
    if not value:
        if required:
            raise ServiceError(f"{label} là bắt buộc.")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ServiceError(f"{label} không hợp lệ.")


def parse_money(value, label="Số tiền"):
    """'10.000.000', '10,000,000', '10 000 000' -> 10000000.0; rỗng -> None."""
    raw = re.sub(r"[.,\s]", "", (value or "").replace("đ", "").replace("₫", ""))
    if not raw:
        return None
    if not raw.isdigit():
        raise ServiceError(f"{label} không hợp lệ.")
    return float(raw)


def money(value):
    """10000000 -> '10.000.000'."""
    return f"{value or 0:,.0f}".replace(",", ".")


_DIGITS = ("không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín")


def _read_block(n, full):
    """Đọc số 0..999; full=True đọc đủ 'không trăm', 'linh' (khối không đứng đầu)."""
    h, t, u = n // 100, n // 10 % 10, n % 10
    words = []
    if h or full:
        words += [_DIGITS[h], "trăm"]
    if t == 0:
        if u and (h or full):
            words.append("linh")
    elif t == 1:
        words.append("mười")
    else:
        words += [_DIGITS[t], "mươi"]
    if u:
        if u == 1 and t >= 2:
            words.append("mốt")
        elif u == 5 and t >= 1:
            words.append("lăm")
        elif u == 4 and t >= 2:
            words.append("tư")
        else:
            words.append(_DIGITS[u])
    return words


def money_words(amount):
    """Đọc số tiền bằng chữ: 10500000 -> 'Mười triệu năm trăm nghìn đồng'."""
    n = int(round(amount or 0))
    if n == 0:
        return "Không đồng"
    units = ["", "nghìn", "triệu", "tỷ", "nghìn tỷ", "triệu tỷ"]
    blocks = []
    while n:
        blocks.append(n % 1000)
        n //= 1000
    words = []
    for i in range(len(blocks) - 1, -1, -1):
        if blocks[i]:
            words += _read_block(blocks[i], full=i != len(blocks) - 1)
            if units[i]:
                words.append(units[i])
    text = " ".join(words) + " đồng"
    return text[0].upper() + text[1:]


def _months_between(a, b):
    """Số tháng (có phần lẻ) từ a tới b, dùng để kiểm tra thời hạn hợp đồng."""
    months = (b.year - a.year) * 12 + b.month - a.month
    return months + (1 if b.day >= a.day else 0)


# ---------------------------------------------------------------- hợp đồng

def _effective_end(c):
    """Ngày kết thúc thực tế: ngày chấm dứt sớm nếu có, không thì ngày hết hạn (None = vô thời hạn)."""
    if c["status"] == "terminated" and c["terminated_on"]:
        return c["terminated_on"]
    return c["end_date"]


def contract_state(c, today=None):
    today = (today or date.today()).isoformat()
    if c["status"] == "terminated":
        return "terminated"
    if c["start_date"] > today:
        return "upcoming"
    if c["end_date"] and c["end_date"] < today:
        return "expired"
    if c["end_date"] and c["end_date"] <= (date.fromisoformat(today) + timedelta(days=EXPIRING_DAYS)).isoformat():
        return "expiring"
    return "active"


def _decorate(row, today):
    c = dict(row)
    c["state"] = contract_state(c, today)
    c["allowances"] = json.loads(c["allowances"] or "[]")
    c["allowance_total"] = sum(a["amount"] for a in c["allowances"])
    if c["end_date"] and c["state"] in ("active", "expiring"):
        c["days_left"] = (date.fromisoformat(c["end_date"]) - today).days
    return c


def contracts_of(conn, employee_id, today=None):
    """Hợp đồng của một nhân viên, mới nhất trước."""
    today = today or date.today()
    return [_decorate(r, today) for r in conn.execute(
        "SELECT c.*, d.filename AS document_name FROM contracts c "
        "LEFT JOIN documents d ON d.id = c.document_id "
        "WHERE c.employee_id = ? ORDER BY c.start_date DESC, c.id DESC", (employee_id,))]


def current_contract(contracts):
    """Hợp đồng đang hiệu lực (mới nhất) trong danh sách đã decorate."""
    return next((c for c in contracts if c["state"] in ("active", "expiring")), None)


def get_contract(conn, contract_id, today=None):
    row = conn.execute(
        "SELECT c.*, e.full_name, e.code, e.photo, e.status AS employee_status FROM contracts c "
        "JOIN employees e ON e.id = c.employee_id WHERE c.id = ?", (contract_id,)).fetchone()
    if row is None:
        raise ServiceError("Không tìm thấy hợp đồng.")
    return _decorate(row, today or date.today())


def all_contracts(conn, today=None, state=None):
    """Hợp đồng của mọi nhân viên kèm trạng thái; state lọc theo trạng thái tính được."""
    today = today or date.today()
    rows = conn.execute(
        "SELECT c.*, e.full_name, e.code, e.photo, e.status AS employee_status, e.department_id, "
        "dp.name AS department FROM contracts c JOIN employees e ON e.id = c.employee_id "
        "LEFT JOIN departments dp ON dp.id = e.department_id "
        "ORDER BY c.start_date DESC, c.id DESC").fetchall()
    out = [_decorate(r, today) for r in rows]
    return [c for c in out if c["state"] == state] if state else out


def _parse_allowances(text):
    """Mỗi dòng 'Tên: số tiền' -> [{'name', 'amount'}]."""
    out = []
    for i, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        name, sep, amount = line.rpartition(":")
        if not sep or not name.strip():
            raise ServiceError(f"Phụ cấp dòng {i}: cần nhập dạng 'Tên phụ cấp: số tiền'.")
        value = parse_money(amount, f"Phụ cấp dòng {i}")
        if value is None:
            raise ServiceError(f"Phụ cấp dòng {i}: thiếu số tiền.")
        out.append({"name": name.strip()[:80], "amount": value})
    return out


def allowances_text(allowances):
    return "\n".join(f"{a['name']}: {money(a['amount'])}" for a in allowances)


def _next_number(conn, ctype, start):
    prefix = "HĐTV" if ctype == "probation" else "HĐLĐ"
    n = conn.execute("SELECT COUNT(*) FROM contracts WHERE substr(start_date, 1, 4) = ?",
                     (str(start.year),)).fetchone()[0] + 1
    return f"{n:02d}/{start.year}/{prefix}"


def save_contract(conn, employee_id, form, user_id=None, contract_id=None):
    """Tạo / sửa hợp đồng. Trả về (id, cảnh báo)."""
    ctype = form.get("type")
    if ctype not in CONTRACT_TYPES:
        raise ServiceError("Loại hợp đồng không hợp lệ.")
    start = _date(form.get("start_date"), "Ngày bắt đầu", required=True)
    end = _date(form.get("end_date"), "Ngày kết thúc")
    sign = _date(form.get("sign_date"), "Ngày ký")
    if ctype == "indefinite":
        end = None
    elif end is None:
        raise ServiceError(f"Hợp đồng {CONTRACT_TYPES[ctype].lower()} cần có ngày kết thúc.")
    if end and end < start:
        raise ServiceError("Ngày kết thúc phải sau ngày bắt đầu.")
    if ctype == "fixed" and _months_between(start, end) > FIXED_MAX_MONTHS:
        raise ServiceError(f"Hợp đồng xác định thời hạn tối đa {FIXED_MAX_MONTHS} tháng (Điều 20 BLLĐ 2019).")
    if ctype == "probation" and (end - start).days + 1 > PROBATION_MAX_DAYS:
        raise ServiceError(f"Thời gian thử việc tối đa {PROBATION_MAX_DAYS} ngày (Điều 25 BLLĐ 2019).")
    salary = parse_money(form.get("salary"), "Mức lương")
    if salary is None:
        raise ServiceError("Mức lương là bắt buộc.")
    insurance = parse_money(form.get("insurance_salary"), "Lương đóng BHXH")
    insurance = salary if insurance is None else insurance
    allowances = _parse_allowances(form.get("allowances"))

    # không cho hai hợp đồng còn hiệu lực chồng thời gian
    for c in conn.execute("SELECT * FROM contracts WHERE employee_id = ? AND id != ?",
                          (employee_id, contract_id or 0)):
        c_end = _effective_end(c)
        if c["start_date"] <= (end.isoformat() if end else "9999") and (c_end is None or c_end >= start.isoformat()):
            raise ServiceError(f"Trùng thời gian với hợp đồng {c['number'] or '#' + str(c['id'])} "
                               f"({c['start_date']} → {c_end or 'không thời hạn'}). "
                               "Hãy chấm dứt hoặc sửa hợp đồng đó trước.")

    warnings = []
    if ctype == "fixed":
        n_fixed = conn.execute("SELECT COUNT(*) FROM contracts WHERE employee_id = ? AND type = 'fixed' "
                               "AND id != ? AND start_date < ?",
                               (employee_id, contract_id or 0, start.isoformat())).fetchone()[0]
        if n_fixed >= 2:
            warnings.append("Nhân viên đã ký 2 hợp đồng xác định thời hạn; theo Điều 20 BLLĐ 2019 lần này "
                            "thường phải ký hợp đồng không xác định thời hạn.")

    values = {
        "type": ctype, "start_date": start.isoformat(), "end_date": end.isoformat() if end else None,
        "sign_date": (sign or start).isoformat(),
        "number": (form.get("number") or "").strip()[:40] or _next_number(conn, ctype, start),
        "position": (form.get("position") or "").strip()[:100] or None,
        "salary": salary, "insurance_salary": insurance,
        "allowances": json.dumps(allowances, ensure_ascii=False),
        "note": (form.get("note") or "").strip()[:500] or None,
    }
    if contract_id:
        conn.execute(f"UPDATE contracts SET {', '.join(k + ' = ?' for k in values)} WHERE id = ?",
                     [*values.values(), contract_id])
    else:
        prev = conn.execute("SELECT salary FROM contracts WHERE employee_id = ? AND start_date < ? "
                            "ORDER BY start_date DESC LIMIT 1", (employee_id, start.isoformat())).fetchone()
        cur = conn.execute(f"INSERT INTO contracts (employee_id, {', '.join(values)}) "
                           f"VALUES (?, {', '.join('?' * len(values))})", [employee_id, *values.values()])
        contract_id = cur.lastrowid
        if prev and prev["salary"] != salary:
            add_history(conn, employee_id, "salary", start, money(prev["salary"]), money(salary),
                        note=f"Theo hợp đồng {values['number']}", user_id=user_id, commit=False)
    conn.commit()
    return contract_id, warnings


def terminate_contract(conn, contract_id, day):
    c = conn.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
    if c is None:
        raise ServiceError("Không tìm thấy hợp đồng.")
    day = _date(day, "Ngày chấm dứt", required=True) if isinstance(day, str) else day
    if day.isoformat() < c["start_date"]:
        raise ServiceError("Ngày chấm dứt phải sau ngày bắt đầu hợp đồng.")
    if c["end_date"] and day.isoformat() > c["end_date"]:
        raise ServiceError("Ngày chấm dứt phải trước ngày hết hạn hợp đồng.")
    conn.execute("UPDATE contracts SET status = 'terminated', terminated_on = ? WHERE id = ?",
                 (day.isoformat(), contract_id))
    conn.commit()


def delete_contract(conn, contract_id):
    conn.execute("DELETE FROM contracts WHERE id = ?", (contract_id,))
    conn.commit()


def attach_contract_document(conn, contract_id, document_id):
    conn.execute("UPDATE contracts SET document_id = ? WHERE id = ?", (document_id, contract_id))
    conn.commit()


# ---------------------------------------------------------------- nhắc việc

def hr_alerts(conn, today=None, days=EXPIRING_DAYS):
    """Hợp đồng sắp hết hạn / đã hết hạn chưa ký tiếp, nhân viên chưa có hợp đồng, sinh nhật trong tháng."""
    today = today or date.today()
    rows = conn.execute(
        "SELECT c.*, e.full_name, e.code, e.photo FROM contracts c JOIN employees e ON e.id = c.employee_id "
        "WHERE e.status = 'active' ORDER BY c.employee_id, c.start_date").fetchall()
    by_emp = {}
    for r in rows:
        by_emp.setdefault(r["employee_id"], []).append(_decorate(r, today))
    expiring, expired = [], []
    for contracts in by_emp.values():
        last = contracts[-1]  # hợp đồng mới nhất; đã có hợp đồng tiếp theo thì không cần nhắc
        if last["state"] == "expiring":
            expiring.append(last)
        elif last["state"] == "expired":
            expired.append(last)
    expiring.sort(key=lambda c: c["end_date"])
    expired.sort(key=lambda c: c["end_date"])
    no_contract = conn.execute(
        "SELECT id, code, full_name, photo, hire_date FROM employees WHERE status = 'active' "
        "AND id NOT IN (SELECT employee_id FROM contracts) ORDER BY code").fetchall()
    birthdays = conn.execute(
        "SELECT id, code, full_name, photo, dob FROM employees WHERE status = 'active' "
        "AND substr(dob, 6, 2) = ? ORDER BY substr(dob, 9, 2)", (f"{today.month:02d}",)).fetchall()
    return {"expiring": expiring, "expired": expired, "no_contract": no_contract,
            "birthdays": birthdays, "today": today}


# ---------------------------------------------------------------- quá trình công tác

def add_history(conn, employee_id, kind, effective, from_value=None, to_value=None, note=None,
                user_id=None, decision_no=None, decided_by=None, commit=True):
    effective = effective.isoformat() if isinstance(effective, date) else effective
    conn.execute(
        "INSERT INTO employment_history (employee_id, kind, effective_date, from_value, to_value, "
        "decision_no, decided_by, note, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (employee_id, kind, effective, from_value, to_value, decision_no, decided_by, note, user_id))
    if commit:
        conn.commit()


def history_of(conn, employee_id, include_salary=True):
    sql = ("SELECT h.*, u.username FROM employment_history h LEFT JOIN users u ON u.id = h.created_by "
           "WHERE h.employee_id = ?")
    if not include_salary:
        sql += " AND h.kind != 'salary'"
    return conn.execute(sql + " ORDER BY h.effective_date DESC, h.id DESC", (employee_id,)).fetchall()


def _dept_name(conn, dept_id):
    if not dept_id:
        return None
    row = conn.execute("SELECT name FROM departments WHERE id = ?", (dept_id,)).fetchone()
    return row["name"] if row else None


def track_changes(conn, old, new, user_id=None):
    """Tự ghi quá trình công tác khi sửa hồ sơ làm đổi phòng ban / chức danh."""
    today = date.today()
    if (old["department_id"] or None) != (new["department_id"] or None):
        add_history(conn, old["id"], "transfer", today, _dept_name(conn, old["department_id"]) or "—",
                    _dept_name(conn, new["department_id"]) or "—", note="Sửa hồ sơ", user_id=user_id,
                    commit=False)
    if (old["position"] or None) != (new["position"] or None):
        add_history(conn, old["id"], "title", today, old["position"] or "—", new["position"] or "—",
                    note="Sửa hồ sơ", user_id=user_id, commit=False)
    conn.commit()


def record_decision(conn, emp, form, user_id=None):
    """Ghi một quyết định nhân sự; điều chuyển / đổi chức danh cập nhật luôn hồ sơ."""
    kind = form.get("kind")
    if kind not in DECISION_KINDS:
        raise ServiceError("Loại quyết định không hợp lệ.")
    effective = _date(form.get("effective_date"), "Ngày hiệu lực", required=True)
    note = (form.get("note") or "").strip()[:500] or None
    extra = {"decision_no": (form.get("decision_no") or "").strip()[:60] or None,
             "decided_by": (form.get("decided_by") or "").strip()[:100] or None}
    updates = {}
    if kind == "transfer":
        dept = form.get("department_id") or ""
        dept_id = int(dept) if dept.isdigit() else None
        if dept_id and not _dept_name(conn, dept_id):
            raise ServiceError("Phòng ban không tồn tại.")
        if dept_id == emp["department_id"]:
            raise ServiceError("Nhân viên đang ở phòng ban này.")
        from_v, to_v = _dept_name(conn, emp["department_id"]) or "—", _dept_name(conn, dept_id) or "—"
        updates["department_id"] = dept_id
        position = (form.get("position") or "").strip()
        if position and position != emp["position"]:
            updates["position"] = position[:100]
            to_v += f" · {position[:100]}"
    elif kind in ("title", "promotion"):
        position = (form.get("position") or "").strip()[:100]
        if not position:
            raise ServiceError("Cần nhập chức danh mới.")
        from_v, to_v = emp["position"] or "—", position
        updates["position"] = position
    elif kind == "salary":
        amount = parse_money(form.get("salary"), "Mức lương mới")
        if amount is None:
            raise ServiceError("Cần nhập mức lương mới.")
        cur = current_contract(contracts_of(conn, emp["id"]))
        from_v, to_v = (money(cur["salary"]) if cur else None), money(amount)
    else:
        if not note:
            raise ServiceError("Cần nhập nội dung quyết định.")
        from_v = to_v = None
    if updates and effective <= date.today():
        conn.execute(f"UPDATE employees SET {', '.join(k + ' = ?' for k in updates)} WHERE id = ?",
                     [*updates.values(), emp["id"]])
    elif updates:
        note = ((note + " · ") if note else "") + "Chưa áp dụng vào hồ sơ (ngày hiệu lực ở tương lai)"
    add_history(conn, emp["id"], kind, effective, from_v, to_v, note=note, user_id=user_id, commit=False,
                **extra)
    conn.commit()


def delete_history(conn, employee_id, history_id):
    conn.execute("DELETE FROM employment_history WHERE id = ? AND employee_id = ?", (history_id, employee_id))
    conn.commit()


# ---------------------------------------------------------------- người phụ thuộc

def dependents_of(conn, employee_id):
    return conn.execute("SELECT * FROM dependents WHERE employee_id = ? ORDER BY dob, id",
                        (employee_id,)).fetchall()


def add_dependent(conn, employee_id, form):
    name = (form.get("full_name") or "").strip()[:100]
    relation = (form.get("relation") or "").strip()[:30]
    if not name or not relation:
        raise ServiceError("Cần nhập họ tên và quan hệ của người phụ thuộc.")
    dob = _date(form.get("dob"), "Ngày sinh")
    start = _date(form.get("deduct_from"), "Giảm trừ từ")
    end = _date(form.get("deduct_to"), "Giảm trừ đến")
    if start and end and end < start:
        raise ServiceError("Thời gian giảm trừ không hợp lệ.")
    conn.execute(
        "INSERT INTO dependents (employee_id, full_name, relation, dob, id_number, tax_code, deduct_from, "
        "deduct_to, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (employee_id, name, relation, dob and dob.isoformat(),
         (form.get("id_number") or "").strip()[:20] or None, (form.get("tax_code") or "").strip()[:20] or None,
         start and start.isoformat(), end and end.isoformat(), (form.get("note") or "").strip()[:200] or None))
    conn.commit()


def active_dependents(conn, employee_id, day=None):
    """Số người phụ thuộc đang được giảm trừ tại ngày `day` (dùng khi tính thuế TNCN)."""
    day = (day or date.today()).isoformat()
    return conn.execute(
        "SELECT COUNT(*) FROM dependents WHERE employee_id = ? AND (deduct_from IS NULL OR deduct_from <= ?) "
        "AND (deduct_to IS NULL OR deduct_to >= ?)", (employee_id, day, day)).fetchone()[0]


def delete_dependent(conn, employee_id, dependent_id):
    conn.execute("DELETE FROM dependents WHERE id = ? AND employee_id = ?", (dependent_id, employee_id))
    conn.commit()


# ---------------------------------------------------------------- giấy tờ

def documents_of(conn, employee_id):
    return conn.execute("SELECT d.*, u.username FROM documents d LEFT JOIN users u ON u.id = d.uploaded_by "
                        "WHERE d.employee_id = ? ORDER BY d.created_at DESC, d.id DESC", (employee_id,)).fetchall()


def save_document(conn, doc_dir, employee_id, upload, kind, title, user_id=None):
    """Lưu file upload vào DOCUMENT_DIR/<employee_id>/, tên file ngẫu nhiên. Trả về id."""
    if upload is None or not upload.filename:
        raise ServiceError("Chưa chọn file.")
    if kind not in DOC_KINDS:
        kind = "other"
    filename = Path(upload.filename).name[-150:]
    ext = Path(filename).suffix.lower()
    if ext not in DOC_EXTENSIONS:
        raise ServiceError("Chỉ nhận file " + ", ".join(sorted(e[1:] for e in DOC_EXTENSIONS)) + ".")
    folder = Path(doc_dir) / str(employee_id)
    folder.mkdir(parents=True, exist_ok=True)
    stored = f"{secrets.token_hex(8)}{ext}"
    upload.save(folder / stored)
    size = (folder / stored).stat().st_size
    if size == 0:
        (folder / stored).unlink()
        raise ServiceError("File rỗng.")
    cur = conn.execute(
        "INSERT INTO documents (employee_id, kind, title, filename, stored_name, size, uploaded_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (employee_id, kind, (title or "").strip()[:150] or DOC_KINDS[kind], filename, stored, size, user_id))
    conn.commit()
    return cur.lastrowid


def get_document(conn, doc_id):
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if row is None:
        raise ServiceError("Không tìm thấy giấy tờ.")
    return row


def document_path(doc_dir, doc):
    return Path(doc_dir) / str(doc["employee_id"]) / doc["stored_name"]


def delete_document(conn, doc_dir, doc):
    conn.execute("DELETE FROM documents WHERE id = ?", (doc["id"],))
    conn.commit()
    document_path(doc_dir, doc).unlink(missing_ok=True)


def delete_employee_files(doc_dir, employee_id):
    shutil.rmtree(Path(doc_dir) / str(employee_id), ignore_errors=True)


# ---------------------------------------------------------------- nghỉ việc

def offboarding_info(conn, emp):
    """Những việc còn treo cần xử lý khi cho nghỉ việc."""
    return {
        "pending_leaves": conn.execute("SELECT COUNT(*) FROM leave_requests WHERE employee_id = ? "
                                       "AND status = 'pending'", (emp["id"],)).fetchone()[0],
        "pending_requests": conn.execute("SELECT COUNT(*) FROM attendance_requests WHERE employee_id = ? "
                                         "AND status = 'pending'", (emp["id"],)).fetchone()[0],
        "account": conn.execute("SELECT * FROM users WHERE employee_id = ?", (emp["id"],)).fetchone(),
        "managed": conn.execute("SELECT name FROM departments WHERE manager_id = ?", (emp["id"],)).fetchall(),
        "open_contracts": [c for c in contracts_of(conn, emp["id"])
                           if c["state"] in ("active", "expiring", "upcoming")],
    }


def offboard(conn, emp, form, user_id=None, delete_fingerprint=None, today=None):
    """Cho nhân viên nghỉ việc theo checklist. Trả về (việc đã làm, cảnh báo).

    delete_fingerprint(slot) -> bool: xoá mẫu vân tay trên cảm biến (None khi không có phần cứng).
    """
    today = today or date.today()
    if emp["status"] != "active":
        raise ServiceError("Nhân viên đã nghỉ việc.")
    day = _date(form.get("termination_date"), "Ngày nghỉ việc", required=True)
    if day > today:
        raise ServiceError("Ngày nghỉ việc không được sau hôm nay. Hãy ghi nhận vào ngày làm việc cuối cùng.")
    if emp["hire_date"] and day.isoformat() < emp["hire_date"]:
        raise ServiceError("Ngày nghỉ việc phải sau ngày vào làm.")
    reason = form.get("reason")
    if reason not in TERMINATION_REASONS:
        raise ServiceError("Chọn lý do nghỉ việc.")
    info = offboarding_info(conn, emp)
    done, warnings = [], []

    if form.get("revoke_rfid") and emp["rfid_uid"]:
        conn.execute("UPDATE employees SET rfid_uid = NULL WHERE id = ?", (emp["id"],))
        done.append("Thu hồi thẻ RFID")
    if form.get("delete_fingerprint") and emp["fingerprint_id"] is not None:
        ok = delete_fingerprint(emp["fingerprint_id"]) if delete_fingerprint else False
        conn.execute("UPDATE employees SET fingerprint_id = NULL WHERE id = ?", (emp["id"],))
        done.append("Xoá vân tay")
        if not ok:
            warnings.append(f"Chưa xoá được mẫu vân tay #{emp['fingerprint_id']} trên cảm biến; "
                            "hãy xoá lại khi thiết bị kết nối.")
    if form.get("end_contracts"):
        n = 0
        for c in info["open_contracts"]:
            if c["start_date"] > day.isoformat():
                conn.execute("DELETE FROM contracts WHERE id = ?", (c["id"],))  # chưa hiệu lực: bỏ
            else:
                conn.execute("UPDATE contracts SET status = 'terminated', terminated_on = ? WHERE id = ?",
                             (day.isoformat(), c["id"]))
            n += 1
        if n:
            done.append(f"Chấm dứt {n} hợp đồng")
    if form.get("cancel_pending"):
        a = conn.execute("UPDATE leave_requests SET status = 'cancelled', review_note = 'Nghỉ việc' "
                         "WHERE employee_id = ? AND status = 'pending'", (emp["id"],)).rowcount
        b = conn.execute("UPDATE attendance_requests SET status = 'cancelled', review_note = 'Nghỉ việc' "
                         "WHERE employee_id = ? AND status = 'pending'", (emp["id"],)).rowcount
        if a + b:
            done.append(f"Huỷ {a + b} đơn chờ duyệt")
    if info["account"]:
        if form.get("delete_account"):
            conn.execute("DELETE FROM users WHERE id = ?", (info["account"]["id"],))
            done.append("Xoá tài khoản đăng nhập")
        else:
            done.append("Khoá tài khoản đăng nhập")  # tài khoản của người đã nghỉ không đăng nhập được
    if info["managed"]:
        conn.execute("UPDATE departments SET manager_id = NULL WHERE manager_id = ?", (emp["id"],))
        warnings.append("Đã bỏ vị trí trưởng phòng: " + ", ".join(d["name"] for d in info["managed"])
                        + ". Hãy chỉ định trưởng phòng mới.")
    handover = [label for key, label in HANDOVER.items() if form.get(f"handover_{key}")]

    conn.execute("UPDATE employees SET status = 'inactive', termination_date = ?, termination_reason = ? "
                 "WHERE id = ?", (day.isoformat(), reason, emp["id"]))
    note = (form.get("note") or "").strip()[:500]
    details = "; ".join(x for x in (note, "Đã làm: " + ", ".join(done + handover) if done or handover else "") if x)
    add_history(conn, emp["id"], "termination", day, None, TERMINATION_REASONS[reason],
                note=details or None, user_id=user_id, commit=False,
                decision_no=(form.get("decision_no") or "").strip()[:60] or None)
    conn.commit()
    return done + handover, warnings


def rehire(conn, emp, form, user_id=None):
    if emp["status"] == "active":
        raise ServiceError("Nhân viên đang làm việc.")
    day = _date(form.get("hire_date"), "Ngày vào làm lại", required=True)
    if emp["termination_date"] and day.isoformat() <= emp["termination_date"]:
        raise ServiceError("Ngày vào làm lại phải sau ngày nghỉ việc.")
    conn.execute("UPDATE employees SET status = 'active', hire_date = ?, termination_date = NULL, "
                 "termination_reason = NULL WHERE id = ?", (day.isoformat(), emp["id"]))
    add_history(conn, emp["id"], "rehire", day, emp["termination_date"], None,
                note=(form.get("note") or "").strip()[:500] or None, user_id=user_id, commit=False)
    conn.commit()


# ---------------------------------------------------------------- thông tin công ty (in hợp đồng)

def load_company(conn):
    out = {k: "" for k in COMPANY_FIELDS}
    for r in conn.execute("SELECT key, value FROM settings WHERE key LIKE 'company.%'"):
        out[r["key"][8:]] = r["value"]
    return out


def save_company(conn, form):
    for key in COMPANY_FIELDS:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                     "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                     (f"company.{key}", (form.get(key) or "").strip()[:300]))
    conn.commit()
