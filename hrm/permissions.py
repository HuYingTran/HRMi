"""Cây phân quyền theo sơ đồ phòng ban.

- admin: toàn quyền trên toàn công ty.
- Trưởng phòng: quyền "nhóm" trên cả nhánh phòng ban mình quản lý (phòng đó + mọi phòng con,
  cháu...), trừ chính mình (không tự duyệt cho mình).
- Mọi nhân viên: quyền "cá nhân" trên dữ liệu của chính mình.

Quyền nào bật cho trưởng phòng / nhân viên do admin cấu hình ở trang Phân quyền (bảng settings).
"""
from flask import g

from .db import get_db

# key: (nhãn, phạm vi, mặc định cho trưởng phòng, mặc định cho nhân viên)
#   phạm vi "team": áp dụng cho nhân viên trong nhánh quản lý; "self": cho chính mình
PERMS = {
    "employees.view":    ("Xem hồ sơ nhân viên", "team", True, False),
    "employees.edit":    ("Sửa hồ sơ nhân viên", "team", False, False),
    "attendance.view":   ("Xem chấm công ngày & báo cáo tháng", "team", True, False),
    "attendance.edit":   ("Thêm / xoá chấm công thủ công", "team", True, False),
    "leaves.approve":    ("Duyệt đơn nghỉ / công tác", "team", True, False),
    "timesheets.review": ("Duyệt & chốt bảng công", "team", True, False),
    "self.timesheet":    ("Xem & giải trình bảng công của mình", "self", True, True),
    "self.leave":        ("Tự tạo đơn nghỉ / công tác", "self", True, True),
}
ROLES = {"manager": "Trưởng phòng", "employee": "Nhân viên"}
LOCKED = {("employee", "self.timesheet"), ("manager", "self.timesheet")}  # luôn bật


# ---------------------------------------------------------------- cấu hình

def settings(conn):
    """{(role, perm): bool} theo cấu hình, mặc định lấy từ PERMS."""
    out = {}
    for key, (_label, scope, mgr, emp) in PERMS.items():
        out[("manager", key)] = mgr
        out[("employee", key)] = emp if scope == "self" else False
    for r in conn.execute("SELECT key, value FROM settings WHERE key LIKE 'perm.%'"):
        _, role, key = r["key"].split(".", 2)
        if (role, key) in out and (role, key) not in LOCKED:
            out[(role, key)] = r["value"] == "1"
    return out


def save_settings(conn, enabled):
    """enabled: tập (role, perm) được bật."""
    for key, (_label, scope, _m, _e) in PERMS.items():
        for role in ROLES:
            if (role, key) in LOCKED or (role == "employee" and scope == "team"):
                continue
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                         "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                         (f"perm.{role}.{key}", "1" if (role, key) in enabled else "0"))
    conn.commit()


# ---------------------------------------------------------------- cây phòng ban

def subtree(conn, dept_ids):
    """Các phòng ban trong nhánh của dept_ids (gồm chính chúng)."""
    children = {}
    for r in conn.execute("SELECT id, parent_id FROM departments"):
        children.setdefault(r["parent_id"], []).append(r["id"])
    out, stack = set(), list(dept_ids)
    while stack:
        d = stack.pop()
        if d not in out:
            out.add(d)
            stack.extend(children.get(d, []))
    return out


def managed_departments(conn, employee_id):
    """Nhánh phòng ban mà nhân viên này là trưởng (của phòng gốc nhánh)."""
    roots = [r[0] for r in conn.execute("SELECT id FROM departments WHERE manager_id = ?", (employee_id,))]
    return subtree(conn, roots) if roots else set()


def team_ids(conn, employee_id):
    """Nhân viên thuộc nhánh quản lý (không gồm chính mình)."""
    depts = managed_departments(conn, employee_id)
    if not depts:
        return set()
    q = ",".join("?" * len(depts))
    return {r[0] for r in conn.execute(
        f"SELECT id FROM employees WHERE department_id IN ({q}) AND id != ?", (*depts, employee_id))}


# ---------------------------------------------------------------- kiểm tra quyền (theo request)

def _ctx():
    """Cache theo request: cấu hình quyền + phạm vi nhóm của người đang đăng nhập."""
    if "perm_ctx" not in g:
        conn = get_db()
        user = g.get("user")
        emp_id = user["employee_id"] if user else None
        team = team_ids(conn, emp_id) if emp_id else set()
        g.perm_ctx = {"settings": settings(conn), "team": team}
    return g.perm_ctx


def is_admin():
    return g.get("user") is not None and g.user["role"] == "admin"


def is_manager():
    return bool(g.get("user")) and bool(_ctx()["team"])


def can(perm, employee_id=None):
    """Người đang đăng nhập có quyền `perm` (trên nhân viên employee_id, nếu có) không.

    employee_id=None: có quyền này với ít nhất một người không (dùng cho menu / chặn trang).
    """
    user = g.get("user")
    if user is None:
        return False
    if user["role"] == "admin":
        return True
    ctx = _ctx()
    scope = PERMS[perm][1]
    me = user["employee_id"]
    if scope == "self":
        role = "manager" if ctx["team"] else "employee"
        ok = ctx["settings"][(role, perm)]
        return ok and me is not None and (employee_id is None or employee_id == me)
    if not ctx["team"] or not ctx["settings"][("manager", perm)]:
        return False
    return employee_id is None or employee_id in ctx["team"]


def visible_ids(perm):
    """Tập nhân viên được thao tác theo quyền nhóm `perm`; None nghĩa là tất cả (admin)."""
    if is_admin():
        return None
    return set(_ctx()["team"]) if can(perm) else set()
