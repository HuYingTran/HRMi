"""Trợ lý HRMi, tầng 1: trả lời offline từ kho hướng dẫn, không cần Internet hay mô hình AI.

answer() trả về dict để widget hiển thị:
    {"mode", "title", "html", "links": [{label, url}], "related": [{title, q}], "more_url", "suggestions"}
"""
from flask import url_for
from markupsafe import escape

from .knowledge import (ROLE_LABELS, current_role, load, page_catalog, page_link, render,
                        visible_topics)
from .search import contains_phrase, words

MAX_QUESTION = 500
MATCH_SCORE = 2.5        # điểm BM25 tối thiểu để coi là tìm thấy chủ đề
MIN_COVERAGE = 0.5       # tỉ lệ từ của câu hỏi phải có trong chủ đề
OTHER_ROLE_MARGIN = 0.75  # chủ đề được phép phải đạt ít nhất 75% điểm chủ đề của vai trò khác
NAV_VERBS = ("mo", "vao", "toi", "den", "chuyen", "trang", "di")
GREETINGS = {"xin chao", "chao", "chao ban", "hello", "hi", "alo", "hey", "chao tro ly"}

DEFAULT_SUGGESTIONS = {
    "employee": ["Làm sao xin nghỉ phép?", "Quên chấm công thì làm gì?", "Xác nhận bảng công thế nào?"],
    "manager": ["Duyệt đơn nghỉ ở đâu?", "Duyệt và chốt bảng công thế nào?", "Thêm chấm công thủ công?"],
    "admin": ["Thêm nhân viên mới thế nào?", "Đăng ký thẻ RFID cho nhân viên?", "Chốt công cuối tháng làm sao?"],
}


def _reply(html, title=None, links=(), related=(), more_url=None, suggestions=()):
    return {"mode": "offline", "title": title, "html": str(html), "links": list(links)[:4],
            "related": list(related)[:3], "more_url": more_url, "suggestions": list(suggestions)[:3]}


def suggestions(page=None):
    """Câu hỏi gợi ý theo trang đang mở, sau đó tới gợi ý chung của vai trò."""
    topics, _ = load()
    role = current_role()
    out = [t.ask[0] for t in visible_topics(topics, role).values() if page in t.pages and t.ask]
    out += DEFAULT_SUGGESTIONS[role]
    return list(dict.fromkeys(out))[:3]


def _match_pages(qwords):
    """Trang có tên / tên gọi khác nằm trong câu hỏi; tên dài (cụ thể hơn) xếp trước."""
    found = []
    for page in page_catalog():
        best = max((len(n.split()) for n in page["names"] if contains_phrase(qwords, n.split())), default=0)
        if best:
            found.append((best, page))
    found.sort(key=lambda x: -x[0])
    return [{"label": p["label"], "url": p["url"]} for _, p in found]


def _topic_links(topic):
    return [{"label": l["label"], "url": l["url"]} for l in (page_link(ep) for ep in topic.pages) if l]


def _dedupe(links):
    seen, out = set(), []
    for l in links:
        if l["url"] not in seen:
            seen.add(l["url"])
            out.append(l)
    return out


def answer(question, page=None):
    q = (question or "").strip()[:MAX_QUESTION]
    qwords = words(q)
    role = current_role()
    sugg = suggestions(page)
    if not qwords:
        return _reply("<p>Bạn muốn hỏi gì? Ví dụ:</p>", suggestions=sugg)
    joined = " ".join(qwords)
    if joined in GREETINGS:
        return _reply(f"<p>Chào bạn! Mình là trợ lý HRMi, hướng dẫn cách dùng hệ thống và đưa bạn tới đúng "
                      f"trang. Bạn đang dùng với vai trò <b>{ROLE_LABELS[role]}</b>.</p>", suggestions=sugg)
    if "cam on" in joined and len(qwords) <= 6:
        return _reply("<p>Không có gì! Cần gì cứ hỏi mình nhé.</p>", suggestions=sugg)

    topics, index = load()
    allowed = visible_topics(topics, role)
    # chủ đề phải đủ điểm và chứa ít nhất một nửa số từ của câu hỏi ("thời tiết hôm nay" không khớp
    # hướng dẫn chấm công chỉ vì có chữ "hôm nay")
    hits = [(s, sc) for s, sc in index.search(q, limit=8)
            if sc >= MATCH_SCORE and index.coverage(q, s) >= MIN_COVERAGE]
    ok_hits = [(s, sc) for s, sc in hits if s in allowed]
    # chủ đề của vai trò khác khớp rõ hơn hẳn: báo việc này cần quyền khác thay vì trả lời lạc đề
    other = hits[0] if hits and hits[0][0] not in allowed else None
    if other and ok_hits and ok_hits[0][1] >= other[1] * OTHER_ROLE_MARGIN:
        other = None
    pages = _match_pages(qwords)
    nav_intent = qwords[0] in NAV_VERBS

    # 1. muốn mở trang ("mở trang hợp đồng") hoặc chỉ nhắc tới tên trang mà không khớp hướng dẫn nào
    if pages and (nav_intent or not (ok_hits or other)):
        related = [{"title": topics[s].title, "q": topics[s].title} for s, _ in ok_hits[:2]]
        return _reply(f"<p>Mở trang <b>{escape(pages[0]['label'])}</b>:</p>", links=pages[:3], related=related,
                      suggestions=sugg)

    # 2. có hướng dẫn phù hợp
    if ok_hits and not other:
        topic = topics[ok_hits[0][0]]
        links = _dedupe(_topic_links(topic) + pages)
        related = [{"title": topics[s].title, "q": topics[s].title} for s, sc in ok_hits[1:3]
                   if sc >= ok_hits[0][1] * 0.5]
        more = url_for("main.help_topic", slug=topic.slug) if topic.has_more else None
        return _reply(render(topic.summary), title=topic.title, links=links, related=related, more_url=more)

    # 3. khớp hướng dẫn của vai trò khác: nói rõ ai làm việc này
    if other:
        t = topics[other[0]]
        who = ", ".join(ROLE_LABELS[r] for r in t.roles)
        return _reply(f"<p>Việc <b>{escape(t.title.lower())}</b> do <b>{who}</b> thực hiện, tài khoản của bạn không "
                      "có quyền này. Bạn hãy liên hệ cấp trên hoặc quản trị hệ thống.</p>", suggestions=sugg)

    # 4. không tìm thấy
    help_link = page_link("main.help_index")
    return _reply("<p>Mình chưa tìm thấy hướng dẫn cho câu này. Bạn thử hỏi ngắn gọn hơn, dùng tên chức năng "
                  "(ví dụ: <i>đơn nghỉ</i>, <i>bảng công</i>, <i>hợp đồng</i>), hoặc xem danh sách hướng dẫn.</p>",
                  links=[help_link] if help_link else [], suggestions=sugg)
