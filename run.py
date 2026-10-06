"""Khởi động Mini HRM: web quản trị + luồng đọc RFID/vân tay.

    python run.py                          # chạy đầy đủ, tự nạp lại khi sửa code
    HRM_RELOAD=0 python run.py             # tắt tự nạp lại (chạy thật / systemd)
    HRM_HARDWARE_ENABLED=0 python run.py   # chạy không cần phần cứng (thử nghiệm)
"""
import logging
import os

from hrm import create_app
from hrm.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Khi tự nạp lại, Werkzeug chạy 2 tiến trình: tiến trình cha chỉ theo dõi file, tiến trình con
# (WERKZEUG_RUN_MAIN=true) mới phục vụ web. Chỉ tiến trình con được mở RFID / vân tay, nếu không
# hai tiến trình sẽ tranh nhau thiết bị. Mỗi lần nạp lại, tiến trình con cũ thoát và nhả thiết bị.
reload = Config.RELOAD
app = create_app(start_hardware=not reload or os.environ.get("WERKZEUG_RUN_MAIN") == "true")
if reload:
    app.config["TEMPLATES_AUTO_RELOAD"] = True  # sửa HTML là thấy ngay, không cần khởi động lại

if __name__ == "__main__":
    app.run(host=app.config["HOST"], port=app.config["PORT"], threaded=True,
            use_reloader=reload, reloader_type="stat",
            # chỉ theo dõi code của dự án, bỏ qua thư viện trong env/ cho nhẹ CPU
            exclude_patterns=["*/site-packages/*", "*/env/*"])
