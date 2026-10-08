"""Trang cấu hình (ngày lễ, OT, giờ làm & ca, nghỉ phép, email) và đơn trong ngày."""
import os
from datetime import date

from flask import abort, flash, g, redirect, render_template, request, url_for

from . import day_requests, notify, permissions, services, workrules
from .db import get_db
from .services import ServiceError
from .views import _in_clause, bp, can, cfg, login_required, mail_wake
from .workrules import RuleError

DOW = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]


# ---------------------------------------------------------------- quy định công (admin)

def _year():
    year = request.values.get("year", type=int) or date.today().year
    if not 2000 <= year <= 2100:
        abort(400)
    return year


def _back_rules(year):
    return redirect(url_for("main.work_rules", year=year))


@bp.route("/work-rules")
@login_required
def work_rules():
    year = _year()
    db = get_db()
    holidays = workrules.holidays_of_year(db, year)
    work_days = cfg()["WORK_DAYS"]
    paid = sum(1 for h in holidays if h["kind"] == "holiday"
               and date.fromisoformat(h["day"]).weekday() in work_days)
    return render_template("work_rules.html", year=year, holidays=holidays, paid=paid,
                           rules=workrules.load_rules(db), RULES=workrules.RULES,
                           HOLIDAY_KINDS=workrules.HOLIDAY_KINDS, OT_APPROVAL=workrules.OT_APPROVAL,
                           DOW=DOW, today=date.today())


@bp.route("/work-rules/ot", methods=["POST"])
@login_required
def work_rules_ot():
    try:
        workrules.save_rules(get_db(), request.form, workrules.OT_KEYS)
        flash("Đã lưu quy định làm thêm giờ.", "success")
    except RuleError as exc:
        flash(str(exc), "error")
    return redirect(url_for("main.work_rules", year=_year()) + "#ot")


# ---------------------------------------------------------------- giờ làm việc & ca (admin)

@bp.route("/work-time")
@login_required
def work_time():
    db = get_db()
    sch = workrules.schedules(db, cfg())
    shifts = workrules.shifts(db)
    usage = {}
    for r in db.execute("SELECT shift_id, COUNT(*) FROM employees WHERE status = 'active' "
                        "AND shift_id IS NOT NULL GROUP BY shift_id"):
        usage[r[0]] = {"employees": r[1]}
    for r in db.execute("SELECT shift_id, GROUP_CONCAT(name, ', ') FROM departments "
                        "WHERE shift_id IS NOT NULL GROUP BY shift_id"):
        usage.setdefault(r[0], {})["departments"] = r[1]
    edit = request.args.get("edit", type=int)
    return render_template("work_time.html", default=sch.default, shifts=shifts, usage=usage,
                           edit=next((s for s in shifts if s["id"] == edit), None),
                           WEEKDAYS=workrules.WEEKDAYS, schedule_label=workrules.schedule_label,
                           shift_schedule=workrules.shift_schedule)


@bp.route("/work-time/default", methods=["POST"])
@login_required
def work_time_default():
    try:
        workrules.save_default_schedule(get_db(), request.form)
        flash("Đã lưu giờ làm việc mặc định.", "success")
    except RuleError as exc:
        flash(str(exc), "error")
    return redirect(url_for("main.work_time"))


@bp.route("/work-time/shifts", methods=["POST"])
@login_required
def work_time_shift():
    shift_id = request.form.get("id", type=int)
    try:
        workrules.save_shift(get_db(), request.form, shift_id)
        flash("Đã lưu ca làm việc.", "success")
    except RuleError as exc:
        flash(str(exc), "error")
        return redirect(url_for("main.work_time", edit=shift_id) if shift_id else url_for("main.work_time"))
    return redirect(url_for("main.work_time"))


@bp.route("/work-time/shifts/<int:shift_id>/delete", methods=["POST"])
@login_required
def work_time_shift_delete(shift_id):
    workrules.delete_shift(get_db(), shift_id)
    flash("Đã xoá ca. Nhân viên / phòng ban dùng ca này chuyển về giờ làm mặc định.", "success")
    return redirect(url_for("main.work_time"))


# ---------------------------------------------------------------- quy định phép (admin)

@bp.route("/leave-rules", methods=["GET", "POST"])
@login_required
def leave_rules():
    db = get_db()
    if request.method == "POST":
        try:
            workrules.save_rules(db, request.form, workrules.LEAVE_KEYS)
            flash("Đã lưu quy định nghỉ phép.", "success")
        except RuleError as exc:
            flash(str(exc), "error")
        return redirect(url_for("main.leave_rules"))
    return render_template("leave_rules.html", rules=workrules.load_rules(db), RULES=workrules.RULES,
                           LEAVE_POLICY=workrules.LEAVE_POLICY, LEAVE_ACCRUAL=workrules.LEAVE_ACCRUAL)


# ---------------------------------------------------------------- thông báo email (admin)

@bp.route("/settings/email", methods=["GET", "POST"])
@login_required
def email_settings():
    db = get_db()
    if request.method == "POST":
        try:
            notify.save_settings(db, request.form)
            flash("Đã lưu cấu hình email.", "success")
            mail_wake()
        except notify.MailError as exc:
            flash(str(exc), "error")
        return redirect(url_for("main.email_settings"))
    outbox = db.execute("SELECT * FROM email_outbox ORDER BY id DESC LIMIT 30").fetchall()
    counts = dict(db.execute("SELECT status, COUNT(*) FROM email_outbox GROUP BY status").fetchall())
    missing = db.execute("SELECT COUNT(*) FROM employees WHERE status = 'active' "
                         "AND (email IS NULL OR email = '')").fetchone()[0]
    return render_template("email_settings.html", s=notify.load_settings(db), outbox=outbox,
                           counts=counts, missing=missing, MAIL_SETTINGS=notify.MAIL_SETTINGS,
                           SECURITY=notify.SECURITY, EVENTS=notify.EVENTS,
                           env_password=bool(os.environ.get("HRM_SMTP_PASSWORD")))


@bp.route("/settings/email/test", methods=["POST"])
@login_required
def email_test():
    to = (request.form.get("to") or "").strip()
    try:
        if not notify._valid_email(to):
            raise notify.MailError("Địa chỉ nhận thử không hợp lệ.")
        notify.send_message(notify.load_settings(get_db()), to, "[HRMi] Thư thử nghiệm",
                            "Cấu hình gửi email của HRMi hoạt động bình thường.")
        flash(f"Đã gửi thư thử tới {to}.", "success")
    except notify.MailError as exc:
        flash(f"Gửi thử thất bại: {exc}", "error")
    return redirect(url_for("main.email_settings"))


@bp.route("/settings/email/retry", methods=["POST"])
@login_required
def email_retry():
    notify.retry_failed(get_db())
    mail_wake()
    flash("Đã đưa các thư lỗi vào hàng đợi gửi lại.", "success")
    return redirect(url_for("main.email_settings"))


@bp.route("/work-rules/holidays", methods=["POST"])
@login_required
def work_rules_holiday():
    f = request.form
    try:
        workrules.save_holiday(get_db(), f.get("day"), f.get("name"), f.get("kind", "holiday"), cfg())
        flash("Đã lưu ngày lễ.", "success")
    except RuleError as exc:
        flash(str(exc), "error")
    return _back_rules(_year())


@bp.route("/work-rules/holidays/<day>/delete", methods=["POST"])
@login_required
def work_rules_holiday_delete(day):
    try:
        workrules.delete_holiday(get_db(), day, cfg())
        flash("Đã xoá.", "success")
    except RuleError as exc:
        flash(str(exc), "error")
    return _back_rules(_year())


@bp.route("/work-rules/holidays/suggest", methods=["POST"])
@login_required
def work_rules_suggest():
    year = _year()
    n, skipped = workrules.load_suggested(get_db(), year, cfg())
    if n:
        flash(f"Đã thêm {n} ngày lễ năm {year}. Hãy đối chiếu với lịch nghỉ Tết, Quốc khánh "
              "chính phủ công bố.", "success")
    elif not skipped:
        flash(f"Lịch năm {year} đã có đủ các ngày lễ theo luật.", "warning")
    if skipped:
        flash("Bỏ qua " + ", ".join(d.strftime("%d/%m") for d in skipped)
              + " vì tháng đã chốt công; mở lại bảng công nếu cần thêm.", "warning")
    return _back_rules(year)


# ---------------------------------------------------------------- đơn trong ngày

def _request_ids():
    """Nhân viên mà người đăng nhập xem / tạo đơn được: nhánh quản lý + bản thân. None = tất cả."""
    ids = permissions.visible_ids("requests.approve")
    if ids is None:
        return None
    if can("self.request"):
        ids.add(g.user["employee_id"])
    return ids


@bp.route("/requests")
@login_required
def requests_list():
    status = request.args.get("status", "pending")
    sql = ("SELECT r.*, e.full_name, e.code, e.photo, u.username AS reviewer FROM attendance_requests r "
           "JOIN employees e ON e.id = r.employee_id LEFT JOIN users u ON u.id = r.reviewed_by WHERE 1=1")
    params = []
    if status in services.LEAVE_STATUSES:
        sql += " AND r.status = ?"
        params.append(status)
    clause, ids = _in_clause(_request_ids())
    if clause:
        sql += " AND r.employee_id" + clause
        params += ids
    rows = get_db().execute(sql + " ORDER BY r.day DESC, r.id DESC LIMIT 500", params).fetchall()
    return render_template("requests.html", rows=rows, status=status, REQ_TYPES=day_requests.REQ_TYPES)


@bp.route("/requests/new", methods=["GET", "POST"])
@login_required
def request_new():
    db = get_db()
    form = request.form if request.method == "POST" else {
        "employee_id": request.args.get("employee_id", "") or g.user["employee_id"] or "",
        "req_type": request.args.get("type", "late"),
        "day": request.args.get("day") or date.today().isoformat(),
    }
    allowed = _request_ids()
    if request.method == "POST":
        emp_id = request.form.get("employee_id", type=int)
        if allowed is not None and emp_id not in allowed:
            abort(403)
        try:
            req_id = day_requests.create(db, emp_id, form.get("req_type"), form.get("day"),
                                         form.get("time_from"), form.get("time_to"), form.get("reason"), cfg())
            if notify.request_created(db, req_id):
                mail_wake()
            flash("Đã gửi đơn.", "success")
            return redirect(url_for("main.requests_list"))
        except ServiceError as exc:
            flash(str(exc), "error")
    employees = [e for e in db.execute(
        "SELECT id, code, full_name FROM employees WHERE status = 'active' ORDER BY code"
    ).fetchall() if allowed is None or e["id"] in allowed]
    return render_template("request_form.html", employees=employees, form=form,
                           REQ_TYPES=day_requests.REQ_TYPES, TIME_LABELS=day_requests.TIME_LABELS,
                           HINTS=day_requests.HINTS)


@bp.route("/requests/<int:req_id>/<action>", methods=["POST"])
@login_required
def request_action(req_id, action):
    db = get_db()
    note = request.form.get("note", "").strip() or None
    req = db.execute("SELECT employee_id, status FROM attendance_requests WHERE id = ?", (req_id,)).fetchone()
    if req is None:
        abort(404)
    own_cancel = (action == "cancel" and req["employee_id"] == g.user["employee_id"]
                  and req["status"] == "pending" and can("self.request"))
    if not (can("requests.approve", req["employee_id"]) or own_cancel):
        abort(403)
    try:
        if action in ("approve", "reject"):
            day_requests.review(db, req_id, action == "approve", g.user, cfg(), note)
            if notify.request_reviewed(db, req_id):
                mail_wake()
            flash("Đã duyệt." if action == "approve" else "Đã từ chối.", "success")
        elif action == "cancel":
            day_requests.cancel(db, req_id)
            flash("Đã huỷ đơn.", "success")
        else:
            abort(404)
    except ServiceError as exc:
        flash(str(exc), "error")
    return redirect(request.referrer or url_for("main.requests_list"))
