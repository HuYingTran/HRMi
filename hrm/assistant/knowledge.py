"""Kho hướng dẫn hrm/help/*.md và danh mục trang theo quyền người dùng.

Mỗi file là một chủ đề, đầu file có khối khai báo:

    ---
    title: Xin nghỉ phép
    group: Nghỉ phép
    roles: all                       # hoặc [employee, manager, admin]
    pages: [main.leave_new, main.leaves]
    keywords: [nghỉ nửa ngày, xin phép]
    ask: [Làm sao xin nghỉ nửa ngày?]
    ---
    Đoạn trả lời ngắn (hiện trong khung chat).

    ## Chi tiết
    Phần còn lại chỉ hiện ở trang /help/<tên file>.

Nội dung viết bằng markdown tối giản: đoạn văn, "- " danh sách, "1. " danh sách đánh số,
"## " tiêu đề, **đậm**, `mã`, và [[main.endpoint]] để chèn liên kết tới trang (chỉ thành link khi
người đọc có quyền vào trang đó).
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from flask import g, url_for
from markupsafe import Markup, escape

from .. import navigation, permissions
from .search import Index, strip_accents

HELP_DIR = Path(__file__).resolve().parent.parent / "help"
ROLES = ("employee", "manager", "admin")
ROLE_LABELS = {"admin": "quản trị", "manager": "trưởng phòng", "employee": "nhân viên"}

# Trang không nằm trên menu nhưng hay được hỏi tới
EXTRA_PAGES = {
    "main.leave_new": "Tạo đơn nghỉ / công tác",
    "main.request_new": "Tạo đơn trong ngày",
    "main.account": "Đổi mật khẩu",
    "main.employee_new": "Thêm nhân viên",
    "main.kiosk": "Màn hình kiosk",
    "main.help_index": "Hướng dẫn sử dụng",
}
# Tên gọi khác của trang, để câu như "mở trang lương hợp đồng" tìm được trang
PAGE_ALIASES = {
    "main.leaves": ["đơn nghỉ", "nghỉ phép", "duyệt đơn nghỉ", "công tác"],
    "main.requests_list": ["đơn trong ngày", "đơn đi muộn", "đơn quên chấm"],
    "main.timesheets": ["chốt công", "duyệt bảng công"],
    "main.my_timesheet": ["bảng công của tôi", "bảng công"],
    "main.my_profile": ["hồ sơ của tôi", "hồ sơ"],
    "main.attendance": ["chấm công theo ngày", "chấm công hôm nay"],
    "main.report": ["báo cáo tháng", "báo cáo"],
    "main.employees": ["danh sách nhân viên", "nhân viên"],
    "main.contracts": ["hợp đồng"],
    "main.departments": ["phòng ban", "sơ đồ tổ chức"],
    "main.permissions_page": ["phân quyền"],
    "main.work_rules": ["ngày lễ", "làm thêm giờ", "hệ số ot"],
    "main.work_time": ["giờ làm", "ca làm việc"],
    "main.leave_rules": ["quy định phép", "cài đặt nghỉ phép"],
    "main.email_settings": ["email", "thông báo email", "smtp"],
    "main.company_settings": ["thông tin công ty"],
    "main.device": ["thiết bị", "đầu đọc thẻ", "cảm biến vân tay"],
    "main.dashboard": ["tổng quan", "trang chủ"],
    "main.leave_new": ["tạo đơn nghỉ", "xin nghỉ"],
    "main.request_new": ["tạo đơn trong ngày"],
    "main.account": ["đổi mật khẩu", "mật khẩu"],
    "main.employee_new": ["thêm nhân viên"],
    "main.kiosk": ["kiosk"],
    "main.help_index": ["hướng dẫn", "trợ giúp"],
}
PUBLIC = {"main.kiosk"}                                   # không cần đăng nhập
NEEDS_EMPLOYEE = {"main.my_timesheet", "main.my_profile"}  # cần tài khoản gắn với nhân viên


@dataclass
class Topic:
    slug: str
    title: str
    group: str
    roles: tuple
    pages: tuple
    keywords: tuple
    ask: tuple
    summary: str          # phần trước "## " đầu tiên: câu trả lời ngắn
    body: str             # toàn bộ nội dung
    order: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def has_more(self):
        return self.body.strip() != self.summary.strip()


# ---------------------------------------------------------------- đọc kho

def _parse_value(raw):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return tuple(x.strip() for x in raw[1:-1].split(",") if x.strip())
    return raw


def parse_topic(slug, text):
    meta, body = {}, text
    if text.startswith("---"):
        head, _, body = text[3:].partition("\n---")
        for line in head.strip().splitlines():
            key, sep, value = line.partition(":")
            if sep and not line.lstrip().startswith("#"):
                meta[key.strip()] = _parse_value(value.split("  #")[0])
        body = body.lstrip("-").lstrip("\n")
    roles = meta.get("roles", "all")
    roles = ROLES if roles in ("all", ("all",)) else tuple(roles if isinstance(roles, tuple) else (roles,))
    as_tuple = lambda v: v if isinstance(v, tuple) else ((v,) if v else ())
    summary = re.split(r"^## ", body, maxsplit=1, flags=re.M)[0].strip()
    return Topic(slug=slug, title=meta.get("title", slug), group=meta.get("group", "Khác"), roles=roles,
                 pages=as_tuple(meta.get("pages")), keywords=as_tuple(meta.get("keywords")),
                 ask=as_tuple(meta.get("ask")), summary=summary, body=body.strip(),
                 order=int(meta.get("order", 0) or 0))


_cache = {}


def load(help_dir=HELP_DIR):
    """{slug: Topic} + chỉ mục tìm kiếm; đọc lại khi file trong thư mục thay đổi."""
    files = sorted(Path(help_dir).glob("*.md"))
    stamp = tuple((f.name, f.stat().st_mtime_ns) for f in files)
    hit = _cache.get(str(help_dir))
    if hit and hit[0] == stamp:
        return hit[1], hit[2]
    topics = {}
    for f in files:
        t = parse_topic(f.stem, f.read_text(encoding="utf-8"))
        topics[t.slug] = t
    index = Index([(t.slug, [(t.title, 4), (" ".join(t.keywords), 3), (" ".join(t.ask), 2),
                             (t.group, 1), (t.body, 1)]) for t in topics.values()])
    _cache[str(help_dir)] = (stamp, topics, index)
    return topics, index


# ---------------------------------------------------------------- người dùng & trang

def current_role():
    if permissions.is_admin():
        return "admin"
    return "manager" if permissions.is_manager() else "employee"


def can_open(endpoint):
    """Người đang đăng nhập vào được trang (không tham số) này không — cùng luật với login_required."""
    from ..views import ALWAYS, ENDPOINT_PERMS
    if endpoint in PUBLIC:
        return True
    if g.get("user") is None:
        return False
    if endpoint in NEEDS_EMPLOYEE and g.user["employee_id"] is None:
        return False
    if permissions.is_admin() or endpoint in ALWAYS:
        return True
    return any(permissions.can(p) for p in ENDPOINT_PERMS.get(endpoint, ()))


def page_label(endpoint):
    for mod in navigation.MODULES:
        for p in mod.pages:
            if p.endpoint == endpoint:
                return p.label_for() if p.label_for else p.label
    return EXTRA_PAGES.get(endpoint, endpoint)


def page_link(endpoint, **args):
    """{'label', 'url', 'endpoint'} nếu người dùng mở được trang, ngược lại None."""
    if not can_open(endpoint):
        return None
    try:
        url = url_for(endpoint, **args)
    except Exception:  # endpoint sai hoặc cần tham số: bỏ qua thay vì làm hỏng câu trả lời
        return None
    return {"label": page_label(endpoint), "url": url, "endpoint": endpoint}


def page_catalog():
    """Mọi trang có tên gọi (menu + trang phụ) mà người dùng mở được."""
    endpoints = [p.endpoint for m in navigation.MODULES for p in m.pages] + list(EXTRA_PAGES)
    out = []
    for ep in dict.fromkeys(endpoints):
        link = page_link(ep)
        if link:
            names = [link["label"], *PAGE_ALIASES.get(ep, [])]
            out.append({**link, "names": [strip_accents(n) for n in names]})
    return out


def visible_topics(topics, role=None):
    role = role or current_role()
    return {s: t for s, t in topics.items() if role in t.roles}


# ---------------------------------------------------------------- hiển thị markdown tối giản

def _inline(text):
    html = str(escape(text))
    html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html)
    html = re.sub(r"`(.+?)`", r"<code>\1</code>", html)

    def page(m):
        ep = m.group(1)
        link = page_link(ep)
        label = m.group(2) or (link["label"] if link else page_label(ep))
        if link:
            return f'<a href="{escape(link["url"])}">{escape(label)}</a>'
        return f"<b>{escape(label)}</b>"
    # [[main.x]] hoặc [[main.x|nhãn]] (sau escape, dấu | vẫn giữ nguyên)
    return re.sub(r"\[\[(main\.[a-z_]+)(?:\|([^\]]+))?\]\]", page, html)


def render(text):
    """Markdown tối giản -> HTML an toàn (mọi văn bản đều được escape trước)."""
    out, para, list_tag = [], [], None

    def flush_para():
        if para:
            out.append("<p>" + " ".join(_inline(x) for x in para) + "</p>")
            para.clear()

    def close_list():
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    for line in text.splitlines():
        s = line.strip()
        m_ul, m_ol = re.match(r"^[-*] (.+)", s), re.match(r"^\d+[.)] (.+)", s)
        if not s:
            flush_para()
            close_list()
        elif s.startswith("## "):
            flush_para()
            close_list()
            out.append(f"<h3>{_inline(s[3:])}</h3>")
        elif m_ul or m_ol:
            flush_para()
            tag = "ul" if m_ul else "ol"
            if list_tag != tag:
                close_list()
                out.append(f"<{tag}>")
                list_tag = tag
            out.append(f"<li>{_inline((m_ul or m_ol).group(1))}</li>")
        elif list_tag and line.startswith("  "):
            out[-1] = out[-1][:-5] + " " + _inline(s) + "</li>"  # dòng tiếp của mục danh sách
        else:
            close_list()
            para.append(s)
    flush_para()
    close_list()
    return Markup("\n".join(out))
