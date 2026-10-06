"""Cấu hình hệ thống. Mọi giá trị đều có thể ghi đè bằng biến môi trường HRM_*."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"


def _env(name, default):
    return os.environ.get("HRM_" + name, default)


def _env_bool(name, default):
    return _env(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


class Config:
    DATABASE = _env("DATABASE", str(INSTANCE_DIR / "hrm.db"))
    PHOTO_DIR = _env("PHOTO_DIR", str(INSTANCE_DIR / "photos"))
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # giới hạn upload ảnh 8 MB

    # Ca làm việc
    WORK_START = _env("WORK_START", "08:00")
    WORK_END = _env("WORK_END", "17:00")
    LUNCH_START = _env("LUNCH_START", "12:00")
    LUNCH_END = _env("LUNCH_END", "13:00")
    LATE_GRACE_MINUTES = int(_env("LATE_GRACE_MINUTES", "5"))
    # 0 = thứ Hai ... 6 = Chủ nhật
    WORK_DAYS = [int(d) for d in _env("WORK_DAYS", "0,1,2,3,4").split(",")]

    # Bỏ qua các lần quét lặp lại của cùng một người trong khoảng này (giây)
    SCAN_COOLDOWN_SECONDS = int(_env("SCAN_COOLDOWN_SECONDS", "60"))

    DEFAULT_ANNUAL_LEAVE_DAYS = float(_env("DEFAULT_ANNUAL_LEAVE_DAYS", "12"))

    # Phần cứng
    HARDWARE_ENABLED = _env_bool("HARDWARE_ENABLED", True)
    RFID_ENABLED = _env_bool("RFID_ENABLED", True)
    FINGERPRINT_ENABLED = _env_bool("FINGERPRINT_ENABLED", True)
    FINGERPRINT_PORT = _env("FINGERPRINT_PORT", "/dev/serial0")
    FINGERPRINT_BAUDRATE = int(_env("FINGERPRINT_BAUDRATE", "57600"))
    ENROLL_TIMEOUT_SECONDS = int(_env("ENROLL_TIMEOUT_SECONDS", "30"))

    ADMIN_USERNAME = _env("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = _env("ADMIN_PASSWORD", "admin")

    # Tự khởi động lại server khi sửa file .py (và nạp lại template HTML). Tắt khi chạy thật.
    RELOAD = _env_bool("RELOAD", True)

    HOST = _env("HOST", "0.0.0.0")
    PORT = int(_env("PORT", "5000"))
