"""Trang bảng công: nhân viên xác nhận / giải trình, cấp trên duyệt / chốt."""
import csv
import io
import secrets
from datetime import date, timedelta

from flask import Response, abort, flash, g, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from . import services, timesheet
from .db import get_db
from .services import ServiceError
from .views import _get_employee, bp, cfg, is_admin, login_required


def _last_month():
    return (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")


def _month_arg(value=None):
    month = value or request.values.get("month") or _last_month()
    try:
        services.parse_month(month)
    except ServiceError:
        abort(400)
    return month


def _back(emp_id, month):
    return redirect(url_for("main.timesheet_detail", emp_id=emp_id, month=month))


def _context(emp_id, month):
    """Nhân viên, bảng công và quyền của người đang xem; 403 nếu không có quyền xem."""
    db = get_db()
    emp = _get_employee(emp_id)
    is_self = g.user["employee_id"] == emp_id
    can_review = timesheet.can_review(db, g.user, emp) and not (is_self and not is_admin())
    if not (is_self or can_review):
        abort(403)
    return emp, timesheet.get(db, emp_id, month), is_self, can_review


def _run(action, emp_id, month, ok_message):
    try:
        action()
        flash(ok_message, "success")
    except ServiceError as exc:
        flash(str(exc), "error")
    return _back(emp_id, month)


# ---------------------------------------------------------------- danh sách

@bp.route("/my/timesheet")
@login_required
def my_timesheet():
    if g.user["employee_id"] is None:
        return redirect(url_for("main.timesheets"))
    return timesheet_detail(g.user["employee_id"], _month_arg())


@bp.route("/timesheets")
@login_required
def timesheets():
    month = _month_arg()
    db = get_db()
    first = services.parse_month(month)
    if is_admin():
        allowed = None
    else:
        from .permissions import visible_ids
        allowed = visible_ids("timesheets.review") or set()
        if not allowed:
            return redirect(url_for("main.my_timesheet"))
    states = timesheet.of_month(db, month)
    pending = timesheet.pending_counts(db, month)
    rows = []
    for r in services.monthly_report(db, first.year, first.month, cfg()):
        emp = r["employee"]
        if allowed is not None and emp["id"] not in allowed:
            continue
        ts = states.get(emp["id"])
        live = {k: r[k] for k in services.TIMESHEET_FIELDS}
        rows.append({
            "employee": emp,
            "timesheet": ts,
            "status": ts["status"] if ts else None,
            "data": ts["data"] if ts and ts["data"] else live,
            "issues": [] if ts and ts["status"] == "confirmed" else services.issues_of(r),
            "pending": pending.get(ts["id"], 0) if ts else 0,
        })
    return render_template("timesheets.html", rows=rows, month=month, ended=services.month_ended(month),
                           STATUSES=timesheet.STATUSES)


@bp.route("/timesheets/<int:emp_id>/<month>")
@login_required
def timesheet_detail(emp_id, month):
    month = _month_arg(month)
    emp, _ts, is_self, can_review = _context(emp_id, month)
    info = timesheet.detail(get_db(), emp_id, month, cfg())
    return render_template("timesheet_detail.html", emp=emp, month=month, is_self=is_self,
                           can_review=can_review, ended=services.month_ended(month),
                           STATUSES=timesheet.STATUSES, FLAGGED=timesheet.FLAGGED,
                           today=date.today(), **info)


# ---------------------------------------------------------------- nhân viên

@bp.route("/timesheets/<int:emp_id>/<month>/explain", methods=["POST"])
@login_required
def timesheet_explain(emp_id, month):
    emp, ts, is_self, _ = _context(emp_id, month)
    if not is_self:
        abort(403)
    f = request.form
    return _run(lambda: timesheet.explain(get_db(), ts, f.get("day", ""), f.get("reason", "").strip(),
                                          f.get("proposed_in"), f.get("proposed_out")),
                emp_id, month, "Đã lưu giải trình.")


@bp.route("/timesheets/<int:emp_id>/<month>/explain/<day>/delete", methods=["POST"])
@login_required
def timesheet_explain_delete(emp_id, month, day):
    emp, ts, is_self, _ = _context(emp_id, month)
    if not is_self:
        abort(403)
    return _run(lambda: timesheet.remove_explanation(get_db(), ts, day), emp_id, month, "Đã xoá giải trình.")


@bp.route("/timesheets/<int:emp_id>/<month>/submit", methods=["POST"])
@login_required
def timesheet_submit(emp_id, month):
    emp, ts, is_self, _ = _context(emp_id, month)
    if not is_self:
        abort(403)
    note = request.form.get("note", "").strip() or None
    return _run(lambda: timesheet.submit(get_db(), ts, note), emp_id, month, "Đã gửi cấp trên duyệt.")


# ---------------------------------------------------------------- cấp trên / admin

@bp.route("/timesheets/send", methods=["POST"])
@login_required
def timesheet_send():
    month = _month_arg()
    db = get_db()
    if request.form.get("employee_id"):
        ids = [request.form.get("employee_id", type=int)]
    else:
        first = services.parse_month(month)
        ids = [r["employee"]["id"] for r in services.monthly_report(db, first.year, first.month, cfg())]
    try:
        n = timesheet.send(db, ids, month)
        flash(f"Đã gửi bảng công cho {n} nhân viên." if n else "Không có bảng công mới để gửi.",
              "success" if n else "warning")
    except ServiceError as exc:
        flash(str(exc), "error")
    return redirect(request.referrer or url_for("main.timesheets", month=month))


@bp.route("/timesheets/<int:emp_id>/<month>/review/<day>", methods=["POST"])
@login_required
def timesheet_review(emp_id, month, day):
    emp, ts, _, can_review = _context(emp_id, month)
    if not can_review:
        abort(403)
    accept = request.form.get("action") == "accept"
    reply = request.form.get("reply", "").strip() or None
    return _run(lambda: timesheet.review_explanation(get_db(), ts, day, accept, reply, cfg()),
                emp_id, month, "Đã chấp nhận giải trình." if accept else "Đã từ chối giải trình.")


@bp.route("/timesheets/<int:emp_id>/<month>/return", methods=["POST"])
@login_required
def timesheet_return(emp_id, month):
    emp, ts, _, can_review = _context(emp_id, month)
    if not can_review:
        abort(403)
    note = request.form.get("note", "").strip()
    return _run(lambda: timesheet.return_to_employee(get_db(), ts, note), emp_id, month,
                "Đã trả lại cho nhân viên.")


@bp.route("/timesheets/<int:emp_id>/<month>/confirm", methods=["POST"])
@login_required
def timesheet_confirm(emp_id, month):
    emp, ts, _, can_review = _context(emp_id, month)
    if not can_review:
        abort(403)
    note = request.form.get("note", "").strip() or None
    return _run(lambda: timesheet.confirm(get_db(), emp_id, month, g.user, cfg(), note=note,
                                          force=is_admin()), emp_id, month, "Đã chốt công.")


@bp.route("/timesheets/confirm-bulk", methods=["POST"])
@login_required
def timesheet_confirm_bulk():
    """Admin chốt hàng loạt các bảng công đã gửi duyệt, không còn giải trình chờ xử lý."""
    month = _month_arg()
    db = get_db()
    pending = timesheet.pending_counts(db, month)
    done, errors = 0, set()
    for emp_id, ts in timesheet.of_month(db, month).items():
        if ts["status"] != "submitted" or pending.get(ts["id"]):
            continue
        try:
            timesheet.confirm(db, emp_id, month, g.user, cfg())
            done += 1
        except ServiceError as exc:
            errors.add(str(exc))
    flash(f"Đã chốt công {done} nhân viên." if done else "Không có bảng công nào sẵn sàng chốt.",
          "success" if done else "warning")
    for e in sorted(errors):
        flash(e, "error")
    return redirect(url_for("main.timesheets", month=month))


@bp.route("/timesheets/<int:emp_id>/<month>/reopen", methods=["POST"])
@login_required
def timesheet_reopen(emp_id, month):
    emp, ts, _, can_review = _context(emp_id, month)
    if not can_review:
        abort(403)
    return _run(lambda: timesheet.reopen(get_db(), ts), emp_id, month, "Đã mở lại bảng công.")


@bp.route("/timesheets.csv")
@login_required
def timesheets_csv():
    month = _month_arg()
    db = get_db()
    first = services.parse_month(month)
    states = timesheet.of_month(db, month)
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf)
    w.writerow(["Tháng", "Mã NV", "Họ tên", "Phòng ban", "Trạng thái", "Người chốt", "Thời điểm chốt",
                "Công chuẩn", "Ngày đi làm", "Công tác", "Nghỉ có lương", "Nghỉ ốm/không lương",
                "Vắng", "Số lần muộn", "Phút muộn", "Phút về sớm", "Giờ công", "Ngày OT", "Giờ OT",
                "Công tính lương"])
    for r in services.monthly_report(db, first.year, first.month, cfg()):
        e, t = r["employee"], states.get(r["employee"]["id"])
        d = t["data"] if t and t["data"] else r
        w.writerow([month, e["code"], e["full_name"], e["department"] or "",
                    timesheet.STATUSES[t["status"] if t else None],
                    (t or {}).get("confirmed_by_name") or "", (t or {}).get("confirmed_at") or "",
                    d["workdays"], d["present"], d["business"], d["paid_leave"], d["unpaid_leave"],
                    d["absent"], d["late"], d["late_minutes"], d["early_minutes"], d["hours"],
                    d["ot_days"], d["ot_hours"], d["payable_days"]])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=bang-cong-{month}.csv"})


# ---------------------------------------------------------------- tài khoản nhân viên (admin)

@bp.route("/employees/<int:emp_id>/account", methods=["POST"])
@login_required
def employee_account(emp_id):
    emp = _get_employee(emp_id)
    db = get_db()
    password = secrets.token_urlsafe(6)
    user = db.execute("SELECT * FROM users WHERE employee_id = ?", (emp_id,)).fetchone()
    if request.form.get("action") == "toggle_admin" and user:
        role = "employee" if user["role"] == "admin" else "admin"
        db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user["id"]))
        db.commit()
        flash(f"{user['username']}: {'đã cấp quyền quản trị' if role == 'admin' else 'đã bỏ quyền quản trị'}.",
              "success")
    elif request.form.get("action") == "delete" and user:
        db.execute("DELETE FROM users WHERE id = ?", (user["id"],))
        db.commit()
        flash("Đã xoá tài khoản đăng nhập.", "success")
    elif user:
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                   (generate_password_hash(password), user["id"]))
        db.commit()
        flash(f"Mật khẩu mới của {user['username']}: {password}", "success")
    else:
        username = emp["code"].lower()
        if db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            flash(f"Tên đăng nhập {username} đã được dùng.", "error")
        else:
            db.execute("INSERT INTO users (username, password_hash, role, employee_id) "
                       "VALUES (?, ?, 'employee', ?)", (username, generate_password_hash(password), emp_id))
            db.commit()
            flash(f"Đã tạo tài khoản {username} / mật khẩu: {password}", "success")
    return redirect(url_for("main.employee_detail", emp_id=emp_id) + "#account")


# ---------------------------------------------------------------- phân quyền (admin)

@bp.route("/permissions", methods=["GET", "POST"])
@login_required
def permissions_page():
    from . import permissions as P
    db = get_db()
    if request.method == "POST":
        enabled = {tuple(v.split(":", 1)) for v in request.form.getlist("perm")}
        P.save_settings(db, enabled)
        flash("Đã lưu phân quyền.", "success")
        return redirect(url_for("main.permissions_page"))

    emps = {e["id"]: e for e in db.execute("SELECT * FROM employees")}
    counts = {}
    for e in emps.values():
        if e["status"] == "active":
            counts[e["department_id"]] = counts.get(e["department_id"], 0) + 1
    nodes = []
    for d in db.execute("SELECT * FROM departments ORDER BY name"):
        mgr = emps.get(d["manager_id"])
        team = P.team_ids(db, mgr["id"]) if mgr else set()
        boss = timesheet.reviewer_id(db, mgr) if mgr else None
        nodes.append({**dict(d), "manager": mgr, "members": counts.get(d["id"], 0),
                      "scope": len([i for i in team if emps[i]["status"] == "active"]),
                      "boss": emps.get(boss) if boss else None,
                      "account": db.execute("SELECT username, role FROM users WHERE employee_id = ?",
                                            (mgr["id"],)).fetchone() if mgr else None})
    children = {}
    for n in nodes:
        children.setdefault(n["parent_id"], []).append(n)

    def build(parent):
        return [{**n, "children": build(n["id"])} for n in children.get(parent, [])]

    admins = db.execute("SELECT u.username, e.full_name, e.id AS emp_id FROM users u "
                        "LEFT JOIN employees e ON e.id = u.employee_id WHERE u.role = 'admin' "
                        "ORDER BY u.id").fetchall()
    return render_template("permissions.html", tree=build(None), settings=P.settings(db),
                           PERMS=P.PERMS, ROLES=P.ROLES, LOCKED=P.LOCKED, admins=admins,
                           unassigned=counts.get(None, 0))
