"""Trợ lý HRMi (tầng offline) và trang Hướng dẫn sử dụng."""
from flask import abort, jsonify, render_template, request

from . import assistant
from .assistant import knowledge
from .assistant.search import strip_accents
from .views import ALWAYS, bp, login_required

# mọi tài khoản đăng nhập đều dùng được; nội dung tự lọc theo vai trò và quyền
ALWAYS.update({"main.help_index", "main.help_topic", "main.api_assistant"})


@bp.app_context_processor
def inject_assistant():
    return {"assistant_suggestions": assistant.suggestions}


@bp.route("/help")
@login_required
def help_index():
    topics, _ = knowledge.load()
    visible = sorted(knowledge.visible_topics(topics).values(), key=lambda t: (t.order, t.title))
    groups = {}
    for name in ("Bắt đầu", "Chấm công", "Đơn từ", "Bảng công", "Nhân sự", "Cài đặt"):
        groups[name] = []
    for t in visible:
        groups.setdefault(t.group, []).append(t)
    return render_template("help.html", groups={k: v for k, v in groups.items() if v},
                           q=request.args.get("q", ""), render=knowledge.render, strip_accents=strip_accents)


@bp.route("/help/<slug>")
@login_required
def help_topic(slug):
    topics, _ = knowledge.load()
    topic = knowledge.visible_topics(topics).get(slug)
    if topic is None:
        abort(404)
    links = [l for l in (knowledge.page_link(ep) for ep in topic.pages) if l]
    same_group = [t for t in knowledge.visible_topics(topics).values() if t.group == topic.group and t.slug != slug]
    return render_template("help_topic.html", topic=topic, html=knowledge.render(topic.body), links=links,
                           related=sorted(same_group, key=lambda t: (t.order, t.title)))


@bp.route("/api/assistant", methods=["POST"])
@login_required
def api_assistant():
    data = request.get_json(silent=True) or {}
    question = data.get("q")
    if not isinstance(question, str):
        return jsonify(error="Thiếu câu hỏi."), 400
    page = data.get("page") if isinstance(data.get("page"), str) else None
    return jsonify(assistant.answer(question, page))
