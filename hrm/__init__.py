"""Mini HRM: hồ sơ nhân viên, chấm công RFID/vân tay, nghỉ phép."""
import logging
import secrets

from flask import Flask
from werkzeug.security import generate_password_hash

from . import db, services
from .config import INSTANCE_DIR, Config

log = logging.getLogger(__name__)


def _secret_key():
    path = INSTANCE_DIR / "secret_key"
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip()


def _ensure_admin(conn, cfg):
    if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        return
    conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (cfg["ADMIN_USERNAME"], generate_password_hash(cfg["ADMIN_PASSWORD"])),
    )
    conn.commit()
    log.warning("Đã tạo tài khoản quản trị '%s'. Hãy đổi mật khẩu sau khi đăng nhập.",
                cfg["ADMIN_USERNAME"])


def create_app(config=None, start_hardware=True):
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config["SECRET_KEY"] = _secret_key()
    if config:
        app.config.update(config)

    conn = db.init_db(app.config["DATABASE"])
    _ensure_admin(conn, app.config)
    conn.close()
    app.teardown_appcontext(db.close_db)

    from .hardware.manager import HardwareManager
    app.extensions["hardware"] = HardwareManager(app.config)
    if start_hardware:
        app.extensions["hardware"].start()

    from .views import bp, presence_of
    from . import views_timesheet  # noqa: F401  (đăng ký thêm route bảng công vào bp)
    app.register_blueprint(bp)
    app.jinja_env.globals["presence_of"] = presence_of
    from . import permissions
    app.jinja_env.globals["can"] = permissions.can

    @app.template_filter("hm")
    def _hm(value):
        return value.strftime("%H:%M") if value else ""

    @app.template_filter("d")
    def _d(value):
        """Hiển thị ngày dạng dd/mm/yyyy, nhận cả chuỗi ISO lẫn đối tượng date."""
        if not value:
            return ""
        if isinstance(value, str):
            value = value[:10].split("-")
            return "/".join(reversed(value)) if len(value) == 3 else "-".join(value)
        return value.strftime("%d/%m/%Y")

    @app.template_filter("initials")
    def _initials(name):
        """Chữ cái đầu của họ và tên: 'Nguyễn Văn An' -> 'NA'."""
        parts = (name or "?").split()
        return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()

    @app.template_filter("num")
    def _num(value):
        return f"{value:g}" if isinstance(value, (int, float)) else value

    app.jinja_env.globals.update(
        LEAVE_TYPES=services.LEAVE_TYPES,
        LEAVE_STATUSES=services.LEAVE_STATUSES,
        DAY_STATUSES=services.DAY_STATUSES,
        PRESENCE=services.PRESENCE,
    )
    return app
