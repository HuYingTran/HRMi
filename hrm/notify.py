"""Thông báo email.

Mỗi sự kiện (đơn mới, đơn được duyệt, bảng công chuyển bước...) tạo thư trong bảng
`email_outbox`; luồng nền `Mailer` gửi dần qua SMTP, lỗi mạng thì thử lại sau (tối đa
MAX_ATTEMPTS lần). Web không bao giờ phải chờ máy chủ thư.

Cấu hình lưu ở `settings` với khoá `mail.<tên>`; mật khẩu SMTP có thể đặt bằng biến môi
trường HRM_SMTP_PASSWORD thay vì lưu trong CSDL.
"""
import logging
import os
import smtplib
import ssl
import threading
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

from flask import has_request_context, request

from .db import connect
from .services import LEAVE_TYPES

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
TS = "%Y-%m-%d %H:%M:%S"

# key: (nhãn, mặc định)
MAIL_SETTINGS = {
    "enabled": ("Bật gửi email", "0"),
    "host": ("Máy chủ SMTP", ""),
    "port": ("Cổng", "587"),
    "security": ("Bảo mật", "starttls"),
    "username": ("Tên đăng nhập", ""),
    "password": ("Mật khẩu", ""),
    "sender": ("Địa chỉ gửi", ""),
    "sender_name": ("Tên người gửi", "HRMi"),
    "admin_email": ("Email quản trị (nhận thay khi không có cấp trên)", ""),
    "base_url": ("Địa chỉ web trong email", ""),
}
SECURITY = {"starttls": "STARTTLS (cổng 587)", "ssl": "SSL/TLS (cổng 465)", "none": "Không mã hoá (mạng nội bộ)"}
EVENTS = {
    "leave_new": "Đơn nghỉ mới → người duyệt",
    "leave_reviewed": "Đơn nghỉ được duyệt / từ chối → nhân viên",
    "request_new": "Đơn trong ngày mới → người duyệt",
    "request_reviewed": "Đơn trong ngày được duyệt / từ chối → nhân viên",
    "timesheet_sent": "Bảng công cần xác nhận → nhân viên",
    "timesheet_submitted": "Bảng công chờ duyệt → cấp trên",
    "timesheet_returned": "Bảng công bị trả lại → nhân viên",
    "timesheet_confirmed": "Bảng công đã chốt → nhân viên",
    "contract_expiring": "Hợp đồng / thử việc sắp hết hạn → quản trị (mỗi ngày một lần)",
}


class MailError(Exception):
    pass


# ---------------------------------------------------------------- cấu hình

def load_settings(conn):
    out = {k: v[1] for k, v in MAIL_SETTINGS.items()}
    out.update({f"event.{e}": "1" for e in EVENTS})
    for r in conn.execute("SELECT key, value FROM settings WHERE key LIKE 'mail.%'"):
        out[r["key"][5:]] = r["value"]
    if os.environ.get("HRM_SMTP_PASSWORD"):
        out["password"] = os.environ["HRM_SMTP_PASSWORD"]
    return out


def _valid_email(addr):
    name, email = parseaddr(addr or "")
    return "@" in email and "." in email.split("@")[-1] and " " not in email


def save_settings(conn, form):
    values = {}
    for key in MAIL_SETTINGS:
        if key == "password":
            continue
        values[key] = (form.get(key) or "").strip()
    values["enabled"] = "1" if form.get("enabled") else "0"
    if values["security"] not in SECURITY:
        raise MailError("Kiểu bảo mật không hợp lệ.")
    if not values["port"].isdigit() or not 0 < int(values["port"]) < 65536:
        raise MailError("Cổng SMTP không hợp lệ.")
    for key in ("sender", "admin_email"):
        if values[key] and not _valid_email(values[key]):
            raise MailError(f"{MAIL_SETTINGS[key][0]}: địa chỉ email không hợp lệ.")
    if values["enabled"] == "1" and not (values["host"] and values["sender"]):
        raise MailError("Cần nhập máy chủ SMTP và địa chỉ gửi trước khi bật gửi email.")
    if values["base_url"] and not values["base_url"].startswith(("http://", "https://")):
        raise MailError("Địa chỉ web phải bắt đầu bằng http:// hoặc https://")
    values["base_url"] = values["base_url"].rstrip("/")
    if form.get("password"):
        values["password"] = form.get("password")
    elif form.get("clear_password"):
        values["password"] = ""
    for e in EVENTS:
        values[f"event.{e}"] = "1" if form.get(f"event.{e}") else "0"
    for key, v in values.items():
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                     "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (f"mail.{key}", v))
    conn.commit()


# ---------------------------------------------------------------- gửi thư

def send_message(settings, to, subject, body, timeout=20):
    """Gửi ngay một thư. Báo MailError nếu lỗi."""
    if not settings["host"] or not settings["sender"]:
        raise MailError("Chưa cấu hình máy chủ SMTP / địa chỉ gửi.")
    msg = EmailMessage()
    msg["From"] = formataddr((settings.get("sender_name") or "HRMi", settings["sender"]))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    port = int(settings["port"] or 0)
    try:
        if settings["security"] == "ssl":
            server = smtplib.SMTP_SSL(settings["host"], port or 465, timeout=timeout,
                                      context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(settings["host"], port or 587, timeout=timeout)
        with server:
            if settings["security"] == "starttls":
                server.starttls(context=ssl.create_default_context())
            if settings["username"]:
                server.login(settings["username"], settings["password"])
            server.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(f"{type(exc).__name__}: {exc}") from exc


def process_outbox(conn, now=None, sender=send_message, limit=20):
    """Gửi các thư đến hạn. Trả về (số gửi được, số lỗi)."""
    settings = load_settings(conn)
    if settings["enabled"] != "1":
        return 0, 0
    now = now or datetime.now()
    rows = conn.execute("SELECT * FROM email_outbox WHERE status = 'pending' AND next_try <= ? "
                        "ORDER BY id LIMIT ?", (now.strftime(TS), limit)).fetchall()
    sent = failed = 0
    for row in rows:
        try:
            sender(settings, row["recipient"], row["subject"], row["body"])
        except MailError as exc:
            attempts = row["attempts"] + 1
            status = "failed" if attempts >= MAX_ATTEMPTS else "pending"
            conn.execute("UPDATE email_outbox SET attempts = ?, status = ?, error = ?, next_try = ? "
                         "WHERE id = ?", (attempts, status, str(exc)[:500],
                                          (now + timedelta(minutes=2 ** attempts)).strftime(TS), row["id"]))
            failed += 1
        else:
            conn.execute("UPDATE email_outbox SET status = 'sent', attempts = attempts + 1, error = NULL, "
                         "sent_at = ? WHERE id = ?", (now.strftime(TS), row["id"]))
            sent += 1
        conn.commit()
    return sent, failed


def retry_failed(conn):
    conn.execute("UPDATE email_outbox SET status = 'pending', attempts = 0, "
                 "next_try = datetime('now', 'localtime') WHERE status = 'failed'")
    conn.commit()


class Mailer(threading.Thread):
    """Luồng nền gửi thư trong hàng đợi."""

    def __init__(self, db_path, interval=20):
        super().__init__(name="mailer", daemon=True)
        self.db_path, self.interval = db_path, interval
        self._halt = threading.Event()
        self._wake = threading.Event()

    def wake(self):
        self._wake.set()

    def stop(self):
        self._halt.set()
        self._wake.set()

    def run(self):
        last_daily = None
        while not self._halt.is_set():
            try:
                conn = connect(self.db_path)
                try:
                    if last_daily != date.today():  # việc nhắc hằng ngày
                        last_daily = date.today()
                        contract_reminders(conn, last_daily)
                    sent, failed = process_outbox(conn)
                    if sent or failed:
                        log.info("Email: đã gửi %d, lỗi %d", sent, failed)
                finally:
                    conn.close()
            except Exception:  # không để luồng chết vì một lỗi bất ngờ
                log.exception("Lỗi luồng gửi email")
            self._wake.wait(self.interval)
            self._wake.clear()


# ---------------------------------------------------------------- tạo thư theo sự kiện

def _employee(conn, emp_id):
    return conn.execute("SELECT * FROM employees WHERE id = ?", (emp_id,)).fetchone()


def _approver_emails(conn, employee, settings):
    """Email cấp trên trực tiếp; không có thì quản trị."""
    from .timesheet import reviewer_id
    rid = reviewer_id(conn, employee)
    if rid:
        boss = _employee(conn, rid)
        if boss and boss["email"] and _valid_email(boss["email"]):
            return [boss["email"]]
    out = [settings["admin_email"]] if settings["admin_email"] else []
    for r in conn.execute("SELECT e.email FROM users u JOIN employees e ON e.id = u.employee_id "
                          "WHERE u.role = 'admin' AND e.email IS NOT NULL AND e.id != ?", (employee["id"],)):
        if _valid_email(r["email"]) and r["email"] not in out:
            out.append(r["email"])
    return out


def _admin_emails(conn, settings):
    out = [settings["admin_email"]] if settings["admin_email"] else []
    for r in conn.execute("SELECT e.email FROM users u JOIN employees e ON e.id = u.employee_id "
                          "WHERE u.role = 'admin' AND e.status = 'active' AND e.email IS NOT NULL"):
        if _valid_email(r["email"]) and r["email"] not in out:
            out.append(r["email"])
    return out


def _queue(conn, settings, event, recipients, subject, lines, path, greeting=None):
    if settings["enabled"] != "1" or settings.get(f"event.{event}") != "1":
        return 0
    base = settings["base_url"]
    if not base and has_request_context():
        base = request.host_url.rstrip("/")  # địa chỉ người dùng đang mở web
    link = f"{base}{path}" if base else None
    n = 0
    for to in dict.fromkeys(r for r in recipients if r and _valid_email(r)):
        body = "\n".join([f"Xin chào {greeting or ''}".rstrip() + ",", "", *lines, ""]
                         + ([f"Xem chi tiết: {link}", ""] if link else [])
                         + ["—", "HRMi · email tự động, vui lòng không trả lời."])
        conn.execute("INSERT INTO email_outbox (recipient, subject, body, event) VALUES (?, ?, ?, ?)",
                     (to, subject[:200], body, event))
        n += 1
    conn.commit()
    return n


def _range(start, end):
    fmt = lambda d: f"{d[8:10]}/{d[5:7]}/{d[:4]}"
    return fmt(start) if start == end else f"{fmt(start)} → {fmt(end)}"


def leave_created(conn, leave_id):
    s = load_settings(conn)
    lv = conn.execute("SELECT * FROM leave_requests WHERE id = ?", (leave_id,)).fetchone()
    emp = _employee(conn, lv["employee_id"])
    kind = LEAVE_TYPES[lv["leave_type"]]
    return _queue(conn, s, "leave_new", _approver_emails(conn, emp, s),
                  f"[HRMi] Đơn {kind.lower()} của {emp['full_name']} cần duyệt",
                  [f"{emp['full_name']} ({emp['code']}) gửi đơn {kind.lower()} "
                   f"{_range(lv['start_date'], lv['end_date'])} ({lv['days']:g} ngày).",
                   f"Lý do: {lv['reason'] or '—'}"], "/leaves")


def leave_reviewed(conn, leave_id):
    s = load_settings(conn)
    lv = conn.execute("SELECT * FROM leave_requests WHERE id = ?", (leave_id,)).fetchone()
    emp = _employee(conn, lv["employee_id"])
    verdict = "được duyệt" if lv["status"] == "approved" else "bị từ chối"
    kind = LEAVE_TYPES[lv["leave_type"]]
    return _queue(conn, s, "leave_reviewed", [emp["email"]],
                  f"[HRMi] Đơn {kind.lower()} {_range(lv['start_date'], lv['end_date'])} {verdict}",
                  [f"Đơn {kind.lower()} {_range(lv['start_date'], lv['end_date'])} của bạn đã {verdict}."]
                  + ([f"Ghi chú: {lv['review_note']}"] if lv["review_note"] else []),
                  "/leaves?status=all", emp["full_name"])


def request_created(conn, req_id):
    from .day_requests import REQ_TYPES
    s = load_settings(conn)
    r = conn.execute("SELECT * FROM attendance_requests WHERE id = ?", (req_id,)).fetchone()
    emp = _employee(conn, r["employee_id"])
    kind = REQ_TYPES[r["req_type"]]
    times = f" {r['time_from'] or '--:--'} → {r['time_to'] or '--:--'}" if r["time_from"] or r["time_to"] else ""
    return _queue(conn, s, "request_new", _approver_emails(conn, emp, s),
                  f"[HRMi] Đơn {kind.lower()} của {emp['full_name']} cần duyệt",
                  [f"{emp['full_name']} ({emp['code']}) gửi đơn {kind.lower()} ngày "
                   f"{_range(r['day'], r['day'])}{times}.", f"Lý do: {r['reason'] or '—'}"], "/requests")


def request_reviewed(conn, req_id):
    from .day_requests import REQ_TYPES
    s = load_settings(conn)
    r = conn.execute("SELECT * FROM attendance_requests WHERE id = ?", (req_id,)).fetchone()
    emp = _employee(conn, r["employee_id"])
    verdict = "được duyệt" if r["status"] == "approved" else "bị từ chối"
    kind = REQ_TYPES[r["req_type"]]
    return _queue(conn, s, "request_reviewed", [emp["email"]],
                  f"[HRMi] Đơn {kind.lower()} ngày {_range(r['day'], r['day'])} {verdict}",
                  [f"Đơn {kind.lower()} ngày {_range(r['day'], r['day'])} của bạn đã {verdict}."]
                  + ([f"Ghi chú: {r['review_note']}"] if r["review_note"] else []),
                  "/requests?status=all", emp["full_name"])


def timesheet_event(conn, event, employee_id, month, note=None):
    s = load_settings(conn)
    emp = _employee(conn, employee_id)
    label = f"{month[5:]}/{month[:4]}"
    path = f"/timesheets/{employee_id}/{month}"
    if event == "timesheet_submitted":
        return _queue(conn, s, event, _approver_emails(conn, emp, s),
                      f"[HRMi] Bảng công {label} của {emp['full_name']} chờ duyệt",
                      [f"{emp['full_name']} ({emp['code']}) đã xác nhận bảng công tháng {label} và gửi duyệt."]
                      + ([f"Ghi chú: {note}"] if note else []), path)
    text = {
        "timesheet_sent": (f"[HRMi] Bảng công {label} cần bạn xác nhận",
                           f"Bảng công tháng {label} đã sẵn sàng. Hãy kiểm tra, giải trình ngày có vấn đề "
                           "(nếu có) và bấm \"Xác nhận & gửi duyệt\"."),
        "timesheet_returned": (f"[HRMi] Bảng công {label} bị trả lại",
                               f"Cấp trên đã trả lại bảng công tháng {label}, cần bạn bổ sung."),
        "timesheet_confirmed": (f"[HRMi] Bảng công {label} đã chốt",
                                f"Bảng công tháng {label} của bạn đã được chốt, dùng làm căn cứ tính lương."),
    }[event]
    return _queue(conn, s, event, [emp["email"]], text[0],
                  [text[1]] + ([f"Ghi chú: {note}"] if note else []), path, emp["full_name"])


def contract_reminders(conn, today=None):
    """Gửi quản trị danh sách hợp đồng sắp hết hạn chưa từng được nhắc; mỗi hợp đồng nhắc một lần."""
    from .profiles import CONTRACT_TYPES, hr_alerts
    today = today or date.today()
    settings = load_settings(conn)
    due = [c for c in hr_alerts(conn, today)["expiring"] if not c["reminded_at"]]
    if not due or settings["enabled"] != "1" or settings.get("event.contract_expiring") != "1":
        return 0
    lines = [f"Có {len(due)} hợp đồng sắp hết hạn trong 30 ngày tới:", ""]
    lines += [f"- {c['code']} {c['full_name']}: {CONTRACT_TYPES[c['type']].lower()} "
              f"{c['number'] or ''}, hết hạn {_range(c['end_date'], c['end_date'])} (còn {c['days_left']} ngày)" for c in due]
    lines += ["", "Hãy ký hợp đồng tiếp theo hoặc chuẩn bị thủ tục nghỉ việc."]
    n = _queue(conn, settings, "contract_expiring", _admin_emails(conn, settings),
               f"[HRMi] {len(due)} hợp đồng sắp hết hạn", lines, "/contracts?state=expiring")
    conn.executemany("UPDATE contracts SET reminded_at = ? WHERE id = ?",
                     [(today.isoformat(), c["id"]) for c in due])
    conn.commit()
    return n
