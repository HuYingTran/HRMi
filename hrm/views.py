"""Các trang web và API."""
import calendar
import csv
import io
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Blueprint, Response, abort, current_app, flash, g, jsonify,
                   redirect, render_template, request, send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from . import permissions, photos, services, timesheet
from .db import get_db
from .services import ServiceError

bp = Blueprint("main", __name__)

EMPLOYEE_FIELDS = ("code", "full_name", "gender", "dob", "phone", "email", "address",
                   "department_id", "position", "hire_date", "status",
                   "annual_leave_days", "rfid_uid")


def hardware():
    return current_app.extensions["hardware"]


def cfg():
    return current_app.config


# ---------------------------------------------------------------- đăng nhập

# Trang mọi tài khoản đăng nhập đều vào được.
ALWAYS = {"main.logout", "main.account", "main.photo", "main.my_timesheet", "main.my_profile"}
# Trang vào được khi có ít nhất một trong các quyền (xem permissions.PERMS); từng view còn
# kiểm tra quyền trên đúng nhân viên đang thao tác. Trang không có ở đây chỉ dành cho admin.
ENDPOINT_PERMS = {
    "main.employees": ("employees.view",),
    "main.employee_detail": ("employees.view",),
    "main.employee_edit": ("employees.edit",),
    "main.attendance": ("attendance.view",),
    "main.report": ("attendance.view",),
    "main.report_csv": ("attendance.view",),
    "main.attendance_manual": ("attendance.edit",),
    "main.attendance_log_delete": ("attendance.edit",),
    "main.leaves": ("leaves.approve", "self.leave"),
    "main.leave_new": ("leaves.approve", "self.leave"),
    "main.leave_action": ("leaves.approve", "self.leave"),
    "main.timesheets": ("timesheets.review",),
    **{f"main.timesheet_{x}": ("self.timesheet", "timesheets.review")
       for x in ("detail", "explain", "explain_delete", "submit", "review", "return", "confirm", "reopen")},
}


@bp.before_app_request
def load_user():
    uid = session.get("user_id")
    g.user = g.employee = None
    if uid:
        db = get_db()
        g.user = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if g.user and g.user["employee_id"]:
            g.employee = db.execute("SELECT * FROM employees WHERE id = ?",
                                    (g.user["employee_id"],)).fetchone()


def presence_of(emp_id):
    """Trạng thái có mặt cho macro avatar; tính một lần cho mỗi request."""
    if "presence" not in g:
        g.presence = services.presence_map(get_db())
    return g.presence.get(emp_id, "absent")


is_admin = permissions.is_admin
can = permissions.can


def _in_clause(ids):
    """(" AND col IN (...)", params) — ids=None nghĩa là không lọc."""
    if ids is None:
        return "", ()
    ids = tuple(ids) or (-1,)
    return f" IN ({','.join('?' * len(ids))})", ids


def _count(sql, ids):
    if ids is not None and not ids:
        return 0
    clause, params = _in_clause(ids)
    return get_db().execute(sql.format(ids=clause or " IS NOT NULL"), params).fetchone()[0]


@bp.app_context_processor
def inject_shell():
    if g.get("user") is None:
        return {}
    db = get_db()
    ctx = {"is_admin": is_admin(), "is_manager": permissions.is_manager(),
           "nav_pending": _count("SELECT COUNT(*) FROM leave_requests WHERE status = 'pending' "
                                 "AND employee_id{ids}", permissions.visible_ids("leaves.approve")),
           "nav_review": _count("SELECT COUNT(*) FROM timesheets WHERE status = 'submitted' "
                                "AND employee_id{ids}", permissions.visible_ids("timesheets.review"))}
    if is_admin():
        ctx["nav_hw"] = hardware().online()
    if g.user["employee_id"]:
        ctx["nav_mine"] = db.execute("SELECT COUNT(*) FROM timesheets WHERE employee_id = ? "
                                     "AND status IN ('sent', 'returned')", (g.user["employee_id"],)).fetchone()[0]
    return ctx


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if request.path.startswith("/api/"):
                return jsonify(error="unauthorized"), 401
            return redirect(url_for("main.login", next=request.full_path))
        own_profile = (request.endpoint == "main.employee_detail"
                       and (request.view_args or {}).get("emp_id") == g.user["employee_id"])
        if not is_admin() and not own_profile and request.endpoint not in ALWAYS and not any(
                can(p) for p in ENDPOINT_PERMS.get(request.endpoint, ())):
            if request.path.startswith("/api/"):
                return jsonify(error="forbidden"), 403
            if request.method == "GET" and request.endpoint != "main.dashboard":
                flash("Bạn không có quyền vào trang này.", "error")
            return redirect(url_for("main.my_timesheet"))
        return view(*args, **kwargs)
    return wrapped


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (request.form.get("username", ""),)
        ).fetchone()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            if user["employee_id"]:
                emp = get_db().execute("SELECT status FROM employees WHERE id = ?",
                                       (user["employee_id"],)).fetchone()
                if emp is None or emp["status"] != "active":
                    flash("Tài khoản đã bị khoá do nhân viên nghỉ việc.", "error")
                    return render_template("login.html")
            session.clear()
            session["user_id"] = user["id"]
            nxt = request.args.get("next", "")
            home = url_for("main.dashboard" if user["role"] == "admin" else "main.my_timesheet")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else home)
        flash("Sai tên đăng nhập hoặc mật khẩu.", "error")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("main.login"))


@bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        current = request.form.get("current", "")
        new = request.form.get("new", "")
        if not check_password_hash(g.user["password_hash"], current):
            flash("Mật khẩu hiện tại không đúng.", "error")
        elif len(new) < 6:
            flash("Mật khẩu mới phải có ít nhất 6 ký tự.", "error")
        elif new != request.form.get("confirm"):
            flash("Xác nhận mật khẩu không khớp.", "error")
        else:
            db = get_db()
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                       (generate_password_hash(new), g.user["id"]))
            db.commit()
            flash("Đã đổi mật khẩu.", "success")
            return redirect(url_for("main.dashboard"))
    return render_template("account.html")


# ---------------------------------------------------------------- tổng quan

@bp.route("/")
@login_required
def dashboard():
    db = get_db()
    today = date.today()
    rows = services.daily_attendance(db, today, cfg())
    counts = {k: 0 for k in services.DAY_STATUSES}
    for r in rows:
        counts[r["status"]] += 1
    pending = db.execute(
        "SELECT l.*, e.full_name, e.code, e.photo FROM leave_requests l "
        "JOIN employees e ON e.id = l.employee_id WHERE l.status = 'pending' "
        "ORDER BY l.start_date LIMIT 10"
    ).fetchall()
    on_leave = [r for r in rows if r["leave"]]
    recent = db.execute(
        "SELECT a.ts, a.method, e.id, e.code, e.full_name, e.photo FROM attendance_logs a "
        "JOIN employees e ON e.id = a.employee_id ORDER BY a.ts DESC LIMIT 8"
    ).fetchall()
    late_rank = sorted(
        (r for r in services.monthly_report(db, today.year, today.month, cfg()) if r["late"]),
        key=lambda r: (-r["late"], -r["late_minutes"]),
    )[:5]
    return render_template(
        "dashboard.html", today=today, total=len(rows), counts=counts, rows=rows,
        checked_in=sum(1 for r in rows if r["first_in"]),
        pending=pending, on_leave=on_leave, recent=recent, late_rank=late_rank,
        # 2 tuần theo lịch: tuần trước (T2 -> CN) và tuần này
        trend=services.attendance_trend(
            db, today - timedelta(days=today.weekday() + 7),
            today + timedelta(days=6 - today.weekday()), cfg(), today=today),
        events=list(reversed(hardware().events_after(0)))[:8],
        hw=hardware().online(),
    )


# ---------------------------------------------------------------- nhân viên

def _departments():
    return get_db().execute("SELECT * FROM departments ORDER BY name").fetchall()


def _get_employee(emp_id):
    emp = get_db().execute(
        "SELECT e.*, d.name AS department FROM employees e "
        "LEFT JOIN departments d ON d.id = e.department_id WHERE e.id = ?", (emp_id,)
    ).fetchone()
    if emp is None:
        abort(404)
    return emp


def _employee_form():
    data = {f: (request.form.get(f) or "").strip() for f in EMPLOYEE_FIELDS}
    errors = []
    if not data["code"]:
        errors.append("Mã nhân viên là bắt buộc.")
    if not data["full_name"]:
        errors.append("Họ tên là bắt buộc.")
    if data["status"] not in ("active", "inactive"):
        data["status"] = "active"
    try:
        data["annual_leave_days"] = float(data["annual_leave_days"] or cfg()["DEFAULT_ANNUAL_LEAVE_DAYS"])
        if data["annual_leave_days"] < 0:
            raise ValueError
    except ValueError:
        errors.append("Số ngày phép năm không hợp lệ.")
    data["department_id"] = int(data["department_id"]) if data["department_id"].isdigit() else None
    data["rfid_uid"] = data["rfid_uid"].replace(" ", "").replace(":", "").upper()
    for key in ("gender", "dob", "phone", "email", "address", "position", "hire_date", "rfid_uid"):
        data[key] = data[key] or None
    return data, errors


def _unique_error(exc):
    msg = str(exc)
    if "employees.code" in msg:
        return "Mã nhân viên đã tồn tại."
    if "employees.rfid_uid" in msg:
        return "Mã thẻ RFID đã được gán cho nhân viên khác."
    return "Dữ liệu bị trùng: " + msg


@bp.route("/employees")
@login_required
def employees():
    q = request.args.get("q", "").strip()
    dept = request.args.get("department", "")
    status = request.args.get("status", "active")
    sql = ("SELECT e.*, d.name AS department FROM employees e "
           "LEFT JOIN departments d ON d.id = e.department_id WHERE 1=1")
    params = []
    # ô tìm kiếm lọc ngay trên trình duyệt (gõ tới đâu lọc tới đó, không phân biệt dấu);
    # q chỉ để giữ từ khoá trên URL khi tải lại trang
    if dept.isdigit():
        sql += " AND e.department_id = ?"
        params.append(int(dept))
    if status in ("active", "inactive"):
        sql += " AND e.status = ?"
        params.append(status)
    clause, ids = _in_clause(permissions.visible_ids("employees.view"))
    if clause:
        sql += " AND e.id" + clause
        params += ids
    rows = get_db().execute(sql + " ORDER BY e.code", params).fetchall()
    return render_template("employees.html", employees=rows, departments=_departments(),
                           q=q, dept=dept, status=status)


def _apply_photo(db, emp_id, old_name):
    """Xử lý ảnh từ form sau khi đã lưu hồ sơ: thay ảnh mới hoặc xoá ảnh."""
    upload = request.files.get("photo")
    new_name = old_name
    if upload and upload.filename:
        try:
            new_name = photos.save_photo(upload, cfg()["PHOTO_DIR"], emp_id)
        except ServiceError as exc:
            flash(str(exc), "error")
            return
    elif request.form.get("remove_photo"):
        new_name = None
    if new_name != old_name:
        db.execute("UPDATE employees SET photo = ? WHERE id = ?", (new_name, emp_id))
        db.commit()
        photos.delete_photo(cfg()["PHOTO_DIR"], old_name)


@bp.route("/photos/<name>")
@login_required
def photo(name):
    # tên file không đổi khi ảnh không đổi nên cho trình duyệt cache lâu
    return send_from_directory(cfg()["PHOTO_DIR"], name, max_age=30 * 86400)


@bp.app_errorhandler(413)
def too_large(_exc):
    flash("Ảnh quá lớn (tối đa 8 MB).", "error")
    return redirect(request.referrer or url_for("main.employees"))


@bp.route("/employees/new", methods=["GET", "POST"])
@login_required
def employee_new():
    emp = {"status": "active", "annual_leave_days": cfg()["DEFAULT_ANNUAL_LEAVE_DAYS"],
           "hire_date": date.today().isoformat()}
    if request.method == "POST":
        data, errors = _employee_form()
        if not errors:
            db = get_db()
            try:
                cur = db.execute(
                    f"INSERT INTO employees ({', '.join(EMPLOYEE_FIELDS)}) "
                    f"VALUES ({', '.join('?' * len(EMPLOYEE_FIELDS))})",
                    [data[f] for f in EMPLOYEE_FIELDS],
                )
                db.commit()
                _apply_photo(db, cur.lastrowid, None)
                flash("Đã tạo hồ sơ.", "success")
                return redirect(url_for("main.employee_detail", emp_id=cur.lastrowid))
            except sqlite3.IntegrityError as exc:
                errors.append(_unique_error(exc))
        for e in errors:
            flash(e, "error")
        emp = data
    return render_template("employee_form.html", emp=emp, departments=_departments(), is_new=True)


@bp.route("/employees/<int:emp_id>/edit", methods=["GET", "POST"])
@login_required
def employee_edit(emp_id):
    emp = _get_employee(emp_id)
    if not can("employees.edit", emp_id):
        abort(403)
    if request.method == "POST":
        data, errors = _employee_form()
        if not errors:
            db = get_db()
            try:
                db.execute(
                    f"UPDATE employees SET {', '.join(f + ' = ?' for f in EMPLOYEE_FIELDS)} "
                    "WHERE id = ?",
                    [data[f] for f in EMPLOYEE_FIELDS] + [emp_id],
                )
                db.commit()
                _apply_photo(db, emp_id, emp["photo"])
                flash("Đã lưu.", "success")
                return redirect(url_for("main.employee_detail", emp_id=emp_id))
            except sqlite3.IntegrityError as exc:
                errors.append(_unique_error(exc))
        for e in errors:
            flash(e, "error")
        emp = {**dict(emp), **data}
    return render_template("employee_form.html", emp=emp, departments=_departments(), is_new=False)


@bp.route("/me")
@login_required
def my_profile():
    """Hồ sơ của chính người đăng nhập (ai cũng xem được hồ sơ của mình)."""
    if g.user["employee_id"] is None:
        return redirect(url_for("main.account"))
    return _employee_page(g.user["employee_id"])


@bp.route("/employees/<int:emp_id>")
@login_required
def employee_detail(emp_id):
    if emp_id == g.user["employee_id"] and not is_admin():
        return redirect(url_for("main.my_profile", **request.args))
    if not can("employees.view", emp_id):
        abort(403)
    return _employee_page(emp_id)


def _employee_page(emp_id):
    emp = _get_employee(emp_id)
    db = get_db()
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    try:
        year, mon = (int(x) for x in month.split("-"))
        start = date(year, mon, 1)
    except ValueError:
        abort(400)
    end = date(year, mon, calendar.monthrange(year, mon)[1])
    days = services.employee_period(db, emp_id, start, end, cfg())
    leaves = db.execute(
        "SELECT * FROM leave_requests WHERE employee_id = ? ORDER BY start_date DESC LIMIT 20",
        (emp_id,),
    ).fetchall()
    logs = db.execute(
        "SELECT * FROM attendance_logs WHERE employee_id = ? AND ts LIKE ? "
        "ORDER BY ts DESC LIMIT 10", (emp_id, month + "%")
    ).fetchall()
    return render_template(
        "employee_detail.html", emp=emp, days=days, month=month, leaves=leaves, logs=logs,
        today=date.today(), timesheet=timesheet.get(db, emp_id, month),
        is_self=emp_id == g.user["employee_id"],
        org=timesheet.org_around(db, emp_id),
        account=db.execute("SELECT * FROM users WHERE employee_id = ?", (emp_id,)).fetchone(),
        balance=services.leave_balance(db, emp, date.today().year),
        hw=hardware().status(), task=hardware().task_for(emp_id),
    )


@bp.route("/employees/<int:emp_id>/delete", methods=["POST"])
@login_required
def employee_delete(emp_id):
    emp = _get_employee(emp_id)
    if emp["fingerprint_id"] is not None:
        hardware().delete_fingerprint(emp["fingerprint_id"])
    db = get_db()
    db.execute("DELETE FROM employees WHERE id = ?", (emp_id,))
    db.commit()
    photos.delete_photo(cfg()["PHOTO_DIR"], emp["photo"])
    flash(f"Đã xoá {emp['full_name']}.", "success")
    return redirect(url_for("main.employees"))


@bp.route("/employees/<int:emp_id>/enroll/<kind>", methods=["POST"])
@login_required
def employee_enroll(emp_id, kind):
    _get_employee(emp_id)
    if kind not in ("rfid", "fingerprint"):
        abort(404)
    try:
        hardware().request_enroll(kind, emp_id)
    except ServiceError as exc:
        flash(str(exc), "error")
    return redirect(url_for("main.employee_detail", emp_id=emp_id) + "#credentials")


@bp.route("/employees/<int:emp_id>/enroll/cancel", methods=["POST"])
@login_required
def employee_enroll_cancel(emp_id):
    hardware().cancel_task()
    return redirect(url_for("main.employee_detail", emp_id=emp_id) + "#credentials")


@bp.route("/api/employees/<int:emp_id>/enroll")
@login_required
def api_enroll_status(emp_id):
    return jsonify(task=hardware().task_for(emp_id))


@bp.route("/employees/<int:emp_id>/credentials/<kind>/clear", methods=["POST"])
@login_required
def employee_clear_credential(emp_id, kind):
    emp = _get_employee(emp_id)
    db = get_db()
    if kind == "rfid":
        db.execute("UPDATE employees SET rfid_uid = NULL WHERE id = ?", (emp_id,))
        flash("Đã gỡ thẻ RFID.", "success")
    elif kind == "fingerprint":
        if emp["fingerprint_id"] is not None and not hardware().delete_fingerprint(emp["fingerprint_id"]):
            flash(f"Đã gỡ vân tay khỏi hồ sơ, nhưng chưa xoá được mẫu #{emp['fingerprint_id']} "
              "trên cảm biến.", "warning")
        else:
            flash("Đã xoá vân tay.", "success")
        db.execute("UPDATE employees SET fingerprint_id = NULL WHERE id = ?", (emp_id,))
    else:
        abort(404)
    db.commit()
    return redirect(url_for("main.employee_detail", emp_id=emp_id) + "#credentials")


# ---------------------------------------------------------------- phòng ban

def _descendants(rows, dept_id):
    """Tập id các phòng ban con cháu của dept_id (để chặn chọn cấp trên tạo vòng lặp)."""
    children = {}
    for r in rows:
        children.setdefault(r["parent_id"], []).append(r["id"])
    out, stack = set(), [dept_id]
    while stack:
        for c in children.get(stack.pop(), []):
            if c not in out:
                out.add(c)
                stack.append(c)
    return out


@bp.route("/departments", methods=["GET", "POST"])
@login_required
def departments():
    db = get_db()
    rows = db.execute("SELECT * FROM departments ORDER BY name").fetchall()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        dept_id = request.form.get("id", type=int)
        parent_id = request.form.get("parent_id", type=int)
        manager_id = request.form.get("manager_id", type=int)
        if not name:
            flash("Thiếu tên phòng ban.", "error")
        elif dept_id and parent_id and (parent_id == dept_id or parent_id in _descendants(rows, dept_id)):
            flash("Không thể chọn phòng ban con làm cấp trên.", "error")
        else:
            try:
                if dept_id:
                    db.execute("UPDATE departments SET name = ?, parent_id = ?, manager_id = ? "
                               "WHERE id = ?", (name, parent_id, manager_id, dept_id))
                else:
                    db.execute("INSERT INTO departments (name, parent_id, manager_id) VALUES (?, ?, ?)",
                               (name, parent_id, manager_id))
                db.commit()
                flash("Đã lưu.", "success")
            except sqlite3.IntegrityError:
                flash("Tên phòng ban đã tồn tại.", "error")
        return redirect(url_for("main.departments"))

    employees = db.execute(
        "SELECT id, code, full_name, position, department_id, photo FROM employees "
        "WHERE status = 'active' ORDER BY code"
    ).fetchall()
    by_id = {e["id"]: e for e in employees}
    members = {}
    for e in employees:
        members.setdefault(e["department_id"], []).append(e)

    depts = []
    for r in rows:
        mgr = by_id.get(r["manager_id"])
        staff = members.get(r["id"], [])
        # trưởng phòng đứng đầu danh sách thành viên
        staff = sorted(staff, key=lambda e: e["id"] != r["manager_id"])
        depts.append({**dict(r), "manager": mgr, "members": staff,
                      "parent_name": next((p["name"] for p in rows if p["id"] == r["parent_id"]), None),
                      "blocked": _descendants(rows, r["id"]) | {r["id"]}})

    children = {}
    for d in depts:
        children.setdefault(d["parent_id"], []).append(d)

    def build(parent_id):
        return [{**d, "children": build(d["id"])} for d in children.get(parent_id, [])]

    return render_template("departments.html", departments=depts, tree=build(None),
                           employees=employees, unassigned=members.get(None, []))


@bp.route("/departments/<int:dept_id>/delete", methods=["POST"])
@login_required
def department_delete(dept_id):
    db = get_db()
    db.execute("DELETE FROM departments WHERE id = ?", (dept_id,))
    db.commit()
    flash("Đã xoá phòng ban.", "success")
    return redirect(url_for("main.departments"))


# ---------------------------------------------------------------- chấm công

@bp.route("/attendance")
@login_required
def attendance():
    day = request.args.get("date") or date.today().isoformat()
    try:
        day = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        abort(400)
    rows = _scoped(services.daily_attendance(get_db(), day, cfg()), "attendance.view")
    return render_template("attendance.html", rows=rows, day=day)


@bp.route("/attendance/manual", methods=["POST"])
@login_required
def attendance_manual():
    db = get_db()
    emp = _get_employee(request.form.get("employee_id", type=int) or 0)
    try:
        ts = datetime.strptime(
            f"{request.form['date']} {request.form['time']}", "%Y-%m-%d %H:%M"
        )
    except (KeyError, ValueError):
        flash("Ngày giờ không hợp lệ.", "error")
        return redirect(request.referrer or url_for("main.attendance"))
    note = request.form.get("note", "").strip() or None
    if not can("attendance.edit", emp["id"]):
        abort(403)
    try:
        services.ensure_unlocked(db, emp["id"], ts.date())
    except ServiceError as exc:
        flash(str(exc), "error")
        return redirect(request.referrer or url_for("main.attendance"))
    services.record_scan(db, emp, "manual", cfg(), now=ts, note=note)
    flash(f"Đã thêm {ts:%H:%M %d/%m} cho {emp['full_name']}.", "success")
    return redirect(request.referrer or url_for("main.attendance", date=ts.date().isoformat()))


@bp.route("/attendance/logs/<int:log_id>/delete", methods=["POST"])
@login_required
def attendance_log_delete(log_id):
    db = get_db()
    log = db.execute("SELECT * FROM attendance_logs WHERE id = ?", (log_id,)).fetchone()
    if log is None:
        abort(404)
    if not can("attendance.edit", log["employee_id"]):
        abort(403)
    try:
        services.ensure_unlocked(db, log["employee_id"], log["ts"][:10])
    except ServiceError as exc:
        flash(str(exc), "error")
        return redirect(request.referrer or url_for("main.attendance"))
    db.execute("DELETE FROM attendance_logs WHERE id = ?", (log_id,))
    db.commit()
    flash("Đã xoá.", "success")
    return redirect(request.referrer or url_for("main.attendance"))


def _report_month():
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    try:
        year, mon = (int(x) for x in month.split("-"))
        date(year, mon, 1)
    except ValueError:
        abort(400)
    return month, year, mon


def _scoped(rows, perm):
    """Lọc các dòng {'employee': ...} theo phạm vi quyền."""
    ids = permissions.visible_ids(perm)
    return rows if ids is None else [r for r in rows if r["employee"]["id"] in ids]


@bp.route("/report")
@login_required
def report():
    month, year, mon = _report_month()
    rows = _scoped(services.monthly_report(get_db(), year, mon, cfg()), "attendance.view")
    return render_template("report.html", rows=rows, month=month)


@bp.route("/report.csv")
@login_required
def report_csv():
    month, year, mon = _report_month()
    rows = _scoped(services.monthly_report(get_db(), year, mon, cfg()), "attendance.view")
    buf = io.StringIO()
    buf.write("﻿")  # BOM để Excel đọc đúng tiếng Việt
    w = csv.writer(buf)
    w.writerow(["Mã NV", "Họ tên", "Phòng ban", "Ngày công chuẩn", "Ngày đi làm", "Số lần muộn",
                "Phút muộn", "Phút về sớm", "Thiếu giờ ra", "Ngày công tác", "Ngày nghỉ phép",
                "Vắng", "Tổng giờ", "Ngày OT", "Giờ OT"])
    for r in rows:
        e = r["employee"]
        w.writerow([e["code"], e["full_name"], e["department"] or "", r["workdays"], r["present"],
                    r["late"], r["late_minutes"], r["early_minutes"], r["missing_out"],
                    r["business"], r["leave_days"], r["absent"], r["hours"],
                    r["ot_days"], r["ot_hours"]])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=cham-cong-{month}.csv"})


# ---------------------------------------------------------------- nghỉ phép

@bp.route("/leaves")
@login_required
def leaves():
    status = request.args.get("status", "pending")
    sql = ("SELECT l.*, e.full_name, e.code, e.photo FROM leave_requests l "
           "JOIN employees e ON e.id = l.employee_id")
    sql += " WHERE 1=1"
    params = []
    if status in services.LEAVE_STATUSES:
        sql += " AND l.status = ?"
        params.append(status)
    clause, ids = _in_clause(_leave_ids())
    if clause:
        sql += " AND l.employee_id" + clause
        params += ids
    rows = get_db().execute(sql + " ORDER BY l.start_date DESC, l.id DESC", params).fetchall()
    return render_template("leaves.html", leaves=rows, status=status)


def _leave_ids():
    """Nhân viên mà người đăng nhập xem / tạo đơn được: nhánh quản lý + bản thân. None = tất cả."""
    ids = permissions.visible_ids("leaves.approve")
    if ids is None:
        return None
    if can("self.leave"):
        ids.add(g.user["employee_id"])
    return ids


@bp.route("/leaves/new", methods=["GET", "POST"])
@login_required
def leave_new():
    db = get_db()
    form = request.form if request.method == "POST" else {
        "employee_id": request.args.get("employee_id", ""),
        "start_date": date.today().isoformat(), "end_date": date.today().isoformat(),
        "leave_type": "annual",
    }
    allowed = _leave_ids()
    if request.method == "POST":
        if allowed is not None and request.form.get("employee_id", type=int) not in allowed:
            abort(403)
        try:
            services.create_leave(
                db, request.form.get("employee_id", type=int), form.get("leave_type"),
                form.get("start_date"), form.get("end_date"), bool(form.get("half_day")),
                form.get("reason", "").strip() or None, cfg(),
            )
            flash("Đã gửi đơn.", "success")
            return redirect(url_for("main.leaves"))
        except ServiceError as exc:
            flash(str(exc), "error")
    employees = [e for e in db.execute(
        "SELECT id, code, full_name FROM employees WHERE status = 'active' ORDER BY code"
    ).fetchall() if allowed is None or e["id"] in allowed]
    return render_template("leave_form.html", employees=employees, form=form)


@bp.route("/leaves/<int:leave_id>/<action>", methods=["POST"])
@login_required
def leave_action(leave_id, action):
    db = get_db()
    note = request.form.get("note", "").strip() or None
    leave = db.execute("SELECT employee_id, status FROM leave_requests WHERE id = ?", (leave_id,)).fetchone()
    if leave is None:
        abort(404)
    own = leave["employee_id"] == g.user["employee_id"]
    own_cancel = action == "cancel" and own and leave["status"] == "pending" and can("self.leave")
    if not (can("leaves.approve", leave["employee_id"]) or own_cancel):
        abort(403)
    try:
        if action == "approve":
            services.review_leave(db, leave_id, True, note)
            flash("Đã duyệt.", "success")
        elif action == "reject":
            services.review_leave(db, leave_id, False, note)
            flash("Đã từ chối.", "success")
        elif action == "cancel":
            services.cancel_leave(db, leave_id)
            flash("Đã huỷ đơn.", "success")
        else:
            abort(404)
    except ServiceError as exc:
        flash(str(exc), "error")
    return redirect(request.referrer or url_for("main.leaves"))


# ---------------------------------------------------------------- thiết bị & kiosk

@bp.route("/device")
@login_required
def device():
    employees = get_db().execute(
        "SELECT id, code, full_name FROM employees WHERE status = 'active' ORDER BY code"
    ).fetchall()
    return render_template("device.html", hw=hardware().status(), employees=employees,
                           events=list(reversed(hardware().events_after(0))))


@bp.route("/device/simulate", methods=["POST"])
@login_required
def device_simulate():
    emp = _get_employee(request.form.get("employee_id", type=int) or 0)
    method = request.form.get("method")
    if method not in ("rfid", "fingerprint"):
        abort(400)
    if emp["status"] != "active":
        flash("Nhân viên đã nghỉ việc.", "error")
        return redirect(url_for("main.device"))
    event = hardware().simulate_scan(get_db(), emp, method)
    labels = {"check_in": "vào", "check_out": "ra", "duplicate": "quét lặp"}
    flash(f"{emp['full_name']}: {labels[event['type']]} {event['time'][:5]}", "success")
    return redirect(url_for("main.device"))


@bp.route("/kiosk")
def kiosk():
    """Màn hình đặt cạnh máy chấm công, không cần đăng nhập."""
    return render_template("kiosk.html")


@bp.route("/api/events")
def api_events():
    after = request.args.get("after", 0, type=int)
    events = hardware().events_after(after)
    # Kiosk công khai: chỉ trả các trường cần hiển thị.
    keep = ("id", "kind", "at", "method", "name", "code", "type", "time", "late_minutes", "ot")
    return jsonify(events=[{k: e[k] for k in keep if k in e} for e in events])
