"""Thanh điều hướng: các trang được gom thành module.

Thanh bên chỉ hiện module; bấm vào module mở trang đầu tiên người dùng được xem, các trang
còn lại của module hiện thành hàng tab phía trên nội dung. Thêm trang mới: khai báo vào MODULES.
"""
from flask import g, request, url_for

from .permissions import can, is_admin


class Page:
    def __init__(self, endpoint, label, visible, match=None, exclude=(), count=None, args=None, label_for=None):
        self.endpoint = endpoint
        self.label = label
        self.visible = visible          # () -> bool
        self.match = (endpoint, *(match or ()))  # endpoint thuộc trang này (khớp tên hoặc tiền tố "x_")
        self.exclude = exclude
        self.count = count              # tên biến đếm trong ngữ cảnh menu (vd. nav_pending)
        self.args = args or (lambda: {})
        self.label_for = label_for      # () -> nhãn thay đổi theo người dùng

    def matches(self, endpoint):
        return (any(endpoint == m or endpoint.startswith(m + "_") for m in self.match)
                and endpoint not in self.exclude)


class Module:
    def __init__(self, key, label, icon, pages, team=False):
        self.key, self.label, self.icon, self.pages, self.team = key, label, icon, pages, team


def _admin():
    return is_admin()


def _not_admin():
    return not is_admin() and g.user["employee_id"] is not None


def _is_own_timesheet():
    """Đang xem bảng công / hồ sơ của chính mình (thuộc module "Của tôi")."""
    ep = request.endpoint or ""
    return (not is_admin() and ep.startswith("main.timesheet_")
            and (request.view_args or {}).get("emp_id") == g.user["employee_id"])


MODULES = [
    Module("me", "Của tôi", "user-check", [
        Page("main.my_timesheet", "Bảng công của tôi", _not_admin, count="nav_mine"),
        Page("main.my_profile", "Hồ sơ của tôi", _not_admin),
    ]),
    Module("dashboard", "Tổng quan", "grid", [
        Page("main.dashboard", "Tổng quan", _admin),
    ]),
    Module("forms", "Đơn từ", "umbrella", [
        Page("main.leaves", "Nghỉ phép · công tác", lambda: can("leaves.approve") or can("self.leave"),
             match=("main.leave",), exclude=("main.leave_rules",), count="nav_pending",
             args=lambda: {} if can("leaves.approve") else {"status": "all"}),
        Page("main.requests_list", "Đơn trong ngày", lambda: can("requests.approve") or can("self.request"),
             match=("main.requests_list", "main.request_new", "main.request_action"), count="nav_requests",
             args=lambda: {} if can("requests.approve") else {"status": "all"}),
    ]),
    Module("people", "Nhân sự", "users", [
        Page("main.employees", "Nhân viên", lambda: can("employees.view"), match=("main.employee",)),
        Page("main.contracts", "Hợp đồng", _admin, match=("main.contract",)),
        Page("main.departments", "Phòng ban", _admin, match=("main.department",)),
        Page("main.permissions_page", "Phân quyền", _admin),
    ], team=True),
    Module("attendance", "Chấm công", "clock", [
        Page("main.attendance", "Theo ngày", lambda: can("attendance.view")),
        Page("main.report", "Báo cáo tháng", lambda: can("attendance.view"), match=("main.report",)),
        Page("main.timesheets", "Chốt công", lambda: can("timesheets.review"), match=("main.timesheet",),
             count="nav_review", label_for=lambda: "Chốt công" if is_admin() else "Duyệt bảng công"),
    ], team=True),
    Module("settings", "Cài đặt", "key", [
        Page("main.work_rules", "Ngày lễ & OT", _admin),
        Page("main.work_time", "Giờ làm & ca", _admin),
        Page("main.leave_rules", "Nghỉ phép", _admin),
        Page("main.email_settings", "Email", _admin, match=("main.email_settings", "main.email_test",
                                                            "main.email_retry")),
        Page("main.company_settings", "Công ty", _admin),
        Page("main.device", "Thiết bị", _admin),
    ]),
    Module("help", "Hướng dẫn", "help", [
        Page("main.help_index", "Hướng dẫn", lambda: True, match=("main.help",)),
    ]),
]


def build(counts):
    """-> (modules hiển thị trên thanh bên, tab của module đang mở)."""
    ep = request.endpoint or ""
    own = _is_own_timesheet()
    out, tabs = [], []
    for mod in MODULES:
        pages = []
        for p in mod.pages:
            if not p.visible():
                continue
            active = p.matches(ep) and not (own and mod.key != "me")
            if mod.key == "me" and p.endpoint == "main.my_timesheet":
                active = active or own
            pages.append({"label": p.label_for() if p.label_for else p.label,
                          "url": url_for(p.endpoint, **p.args()), "active": active,
                          "count": counts.get(p.count, 0) if p.count else 0, "endpoint": p.endpoint})
        if not pages:
            continue
        item = {"key": mod.key, "label": mod.label, "icon": mod.icon, "team": mod.team and not is_admin(),
                "url": pages[0]["url"], "pages": pages, "active": any(p["active"] for p in pages),
                "count": sum(p["count"] for p in pages)}
        if mod.key == "me" and len(pages) == 1:
            item["label"] = pages[0]["label"]
        out.append(item)
        # tab chỉ hiện ở trang danh sách của module (không hiện ở trang chi tiết / biểu mẫu)
        if item["active"] and len(pages) > 1 and any(p["active"] and p["endpoint"] == ep for p in pages):
            tabs = pages
    return out, tabs
