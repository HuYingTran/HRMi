"""Hợp đồng lao động, quá trình công tác, người phụ thuộc, giấy tờ, nghỉ việc, thông tin công ty."""
from datetime import date, timedelta

from flask import abort, flash, g, redirect, render_template, request, send_file, url_for

from . import permissions, profiles, services, workrules
from .db import get_db
from .services import ServiceError
from .views import ALWAYS, ENDPOINT_PERMS, _get_employee, bp, cfg, hardware, login_required

# Người được sửa hồ sơ (kèm quyền thông tin nhạy cảm) quản lý người phụ thuộc & giấy tờ của nhóm;
# chính nhân viên xem / tải được giấy tờ và in hợp đồng của mình. Còn lại chỉ dành cho admin.
ENDPOINT_PERMS.update({
    "main.dependent_add": ("employees.edit",),
    "main.dependent_delete": ("employees.edit",),
    "main.document_upload": ("employees.edit",),
    "main.document_delete": ("employees.edit",),
})
ALWAYS.update({"main.document_download", "main.contract_print"})


def _back(emp_id, anchor):
    return redirect(url_for("main.employee_detail", emp_id=emp_id) + "#" + anchor)


def _require_edit_sensitive(emp_id):
    if not permissions.can_edit_sensitive(emp_id):
        abort(403)


def _contract_or_404(contract_id):
    try:
        return profiles.get_contract(get_db(), contract_id)
    except ServiceError:
        abort(404)


# ---------------------------------------------------------------- hợp đồng (admin)

@bp.route("/contracts")
@login_required
def contracts():
    state = request.args.get("state", "")
    if state and state not in profiles.CONTRACT_STATES:
        state = ""
    db = get_db()
    rows = profiles.all_contracts(db, state=state or None)
    if not request.args.get("all"):  # mặc định ẩn hợp đồng của người đã nghỉ
        rows = [c for c in rows if c["employee_status"] == "active" or state]
    counts = {}
    for c in profiles.all_contracts(db):
        if c["employee_status"] == "active":
            counts[c["state"]] = counts.get(c["state"], 0) + 1
    return render_template("contracts.html", rows=rows, state=state, counts=counts,
                           alerts=profiles.hr_alerts(db), P=profiles)


def _contract_form(emp, contract=None):
    db = get_db()
    if request.method == "POST":
        try:
            cid, warnings = profiles.save_contract(db, emp["id"], request.form, g.user["id"],
                                                   contract["id"] if contract else None)
            upload = request.files.get("file")
            if upload and upload.filename:
                doc_id = profiles.save_document(db, cfg()["DOCUMENT_DIR"], emp["id"], upload, "contract",
                                                f"Hợp đồng {request.form.get('number') or ''}".strip(),
                                                g.user["id"])
                profiles.attach_contract_document(db, cid, doc_id)
            for w in warnings:
                flash(w, "warning")
            flash("Đã lưu hợp đồng.", "success")
            return _back(emp["id"], "contracts")
        except ServiceError as exc:
            flash(str(exc), "error")
        form = request.form.to_dict()
    elif contract:
        form = {**contract, "allowances": profiles.allowances_text(contract["allowances"]),
                "salary": profiles.money(contract["salary"]),
                "insurance_salary": profiles.money(contract["insurance_salary"])}
    else:
        # hợp đồng mới: nối tiếp hợp đồng gần nhất, giữ mức lương & phụ cấp
        last = next(iter(profiles.contracts_of(db, emp["id"])), None)
        if last and last["end_date"]:
            start = date.fromisoformat(last["end_date"]) + timedelta(days=1)
        else:
            start = date.fromisoformat(emp["hire_date"] or date.today().isoformat())
        form = {"type": "probation" if not last else "fixed", "start_date": start.isoformat(),
                "sign_date": date.today().isoformat(), "position": emp["position"] or ""}
        if last:
            form.update(salary=profiles.money(last["salary"]),
                        insurance_salary=profiles.money(last["insurance_salary"]),
                        allowances=profiles.allowances_text(last["allowances"]))
    return render_template("contract_form.html", emp=emp, form=form, contract=contract, P=profiles)


@bp.route("/employees/<int:emp_id>/contracts/new", methods=["GET", "POST"])
@login_required
def contract_new(emp_id):
    return _contract_form(_get_employee(emp_id))


@bp.route("/contracts/<int:contract_id>/edit", methods=["GET", "POST"])
@login_required
def contract_edit(contract_id):
    contract = _contract_or_404(contract_id)
    return _contract_form(_get_employee(contract["employee_id"]), contract)


@bp.route("/contracts/<int:contract_id>/terminate", methods=["POST"])
@login_required
def contract_terminate(contract_id):
    contract = _contract_or_404(contract_id)
    try:
        profiles.terminate_contract(get_db(), contract_id, request.form.get("day", ""))
        flash(f"Đã chấm dứt hợp đồng {contract['number'] or ''}.", "success")
    except ServiceError as exc:
        flash(str(exc), "error")
    return _back(contract["employee_id"], "contracts")


@bp.route("/contracts/<int:contract_id>/delete", methods=["POST"])
@login_required
def contract_delete(contract_id):
    contract = _contract_or_404(contract_id)
    profiles.delete_contract(get_db(), contract_id)
    flash(f"Đã xoá hợp đồng {contract['number'] or ''}.", "success")
    return _back(contract["employee_id"], "contracts")


@bp.route("/contracts/<int:contract_id>/print")
@login_required
def contract_print(contract_id):
    contract = _contract_or_404(contract_id)
    if not permissions.can_sensitive(contract["employee_id"]):
        abort(403)
    db = get_db()
    emp = _get_employee(contract["employee_id"])
    return render_template("contract_print.html", c=contract, emp=emp, company=profiles.load_company(db),
                           schedule=workrules.schedules(db, cfg()).schedule_for(emp),
                           schedule_label=workrules.schedule_label, P=profiles)


# ---------------------------------------------------------------- quá trình công tác (admin)

@bp.route("/employees/<int:emp_id>/history", methods=["POST"])
@login_required
def history_add(emp_id):
    emp = _get_employee(emp_id)
    try:
        profiles.record_decision(get_db(), emp, request.form, g.user["id"])
        flash("Đã ghi quyết định.", "success")
    except ServiceError as exc:
        flash(str(exc), "error")
    return _back(emp_id, "history")


@bp.route("/employees/<int:emp_id>/history/<int:history_id>/delete", methods=["POST"])
@login_required
def history_delete(emp_id, history_id):
    profiles.delete_history(get_db(), emp_id, history_id)
    flash("Đã xoá dòng quá trình công tác (hồ sơ hiện tại không đổi).", "success")
    return _back(emp_id, "history")


# ---------------------------------------------------------------- người phụ thuộc

@bp.route("/employees/<int:emp_id>/dependents", methods=["POST"])
@login_required
def dependent_add(emp_id):
    _get_employee(emp_id)
    _require_edit_sensitive(emp_id)
    try:
        profiles.add_dependent(get_db(), emp_id, request.form)
        flash("Đã thêm người phụ thuộc.", "success")
    except ServiceError as exc:
        flash(str(exc), "error")
    return _back(emp_id, "dependents")


@bp.route("/employees/<int:emp_id>/dependents/<int:dep_id>/delete", methods=["POST"])
@login_required
def dependent_delete(emp_id, dep_id):
    _require_edit_sensitive(emp_id)
    profiles.delete_dependent(get_db(), emp_id, dep_id)
    flash("Đã xoá người phụ thuộc.", "success")
    return _back(emp_id, "dependents")


# ---------------------------------------------------------------- giấy tờ

@bp.route("/employees/<int:emp_id>/documents", methods=["POST"])
@login_required
def document_upload(emp_id):
    _get_employee(emp_id)
    _require_edit_sensitive(emp_id)
    try:
        profiles.save_document(get_db(), cfg()["DOCUMENT_DIR"], emp_id, request.files.get("file"),
                               request.form.get("kind"), request.form.get("title"), g.user["id"])
        flash("Đã tải lên giấy tờ.", "success")
    except ServiceError as exc:
        flash(str(exc), "error")
    return _back(emp_id, "documents")


def _document_or_404(doc_id):
    try:
        return profiles.get_document(get_db(), doc_id)
    except ServiceError:
        abort(404)


@bp.route("/documents/<int:doc_id>")
@login_required
def document_download(doc_id):
    doc = _document_or_404(doc_id)
    if not permissions.can_sensitive(doc["employee_id"]):
        abort(403)
    path = profiles.document_path(cfg()["DOCUMENT_DIR"], doc)
    if not path.exists():
        abort(404)
    # ảnh / PDF mở ngay trên trình duyệt, loại khác tải về
    inline = path.suffix.lower() in (".pdf", ".jpg", ".jpeg", ".png", ".webp", ".txt")
    return send_file(path, download_name=doc["filename"], as_attachment=not inline, max_age=0)


@bp.route("/documents/<int:doc_id>/delete", methods=["POST"])
@login_required
def document_delete(doc_id):
    doc = _document_or_404(doc_id)
    _require_edit_sensitive(doc["employee_id"])
    profiles.delete_document(get_db(), cfg()["DOCUMENT_DIR"], doc)
    flash(f"Đã xoá {doc['title']}.", "success")
    return _back(doc["employee_id"], "documents")


# ---------------------------------------------------------------- nghỉ việc / nhận lại (admin)

@bp.route("/employees/<int:emp_id>/offboard", methods=["GET", "POST"])
@login_required
def employee_offboard(emp_id):
    emp = _get_employee(emp_id)
    db = get_db()
    if emp["status"] != "active":
        flash("Nhân viên đã nghỉ việc.", "warning")
        return _back(emp_id, "history")
    if emp_id == g.user["employee_id"]:
        flash("Không thể tự làm thủ tục nghỉ việc cho chính mình.", "error")
        return _back(emp_id, "history")
    if request.method == "POST":
        try:
            done, warnings = profiles.offboard(db, emp, request.form, g.user["id"],
                                               hardware().delete_fingerprint)
            for w in warnings:
                flash(w, "warning")
            flash(f"{emp['full_name']} đã nghỉ việc." + (" Đã: " + ", ".join(done).lower() + "." if done else ""),
                  "success")
            return _back(emp_id, "history")
        except ServiceError as exc:
            flash(str(exc), "error")
    today = date.today()
    return render_template("offboard.html", emp=emp, info=profiles.offboarding_info(db, emp), today=today,
                           form=request.form, balance=services.leave_balance(db, emp, today.year, cfg()),
                           P=profiles)


@bp.route("/employees/<int:emp_id>/rehire", methods=["POST"])
@login_required
def employee_rehire(emp_id):
    emp = _get_employee(emp_id)
    try:
        profiles.rehire(get_db(), emp, request.form, g.user["id"])
        flash(f"Đã nhận lại {emp['full_name']}. Hãy cấp lại thẻ / vân tay và ký hợp đồng mới.", "success")
    except ServiceError as exc:
        flash(str(exc), "error")
    return _back(emp_id, "history")


# ---------------------------------------------------------------- thông tin công ty (admin)

@bp.route("/settings/company", methods=["GET", "POST"])
@login_required
def company_settings():
    db = get_db()
    if request.method == "POST":
        profiles.save_company(db, request.form)
        flash("Đã lưu thông tin công ty.", "success")
        return redirect(url_for("main.company_settings"))
    return render_template("company.html", company=profiles.load_company(db), FIELDS=profiles.COMPANY_FIELDS)

