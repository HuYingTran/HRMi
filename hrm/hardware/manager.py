"""Luồng nền điều khiển phần cứng.

Một luồng duy nhất sở hữu cả đầu đọc RFID và cảm biến vân tay, luân phiên hỏi
từng thiết bị. Khi web yêu cầu đăng ký thẻ/vân tay, luồng chuyển sang chế độ
đăng ký cho đến khi xong, lỗi, huỷ hoặc hết thời gian.
"""
import itertools
import logging
import threading
import time
from collections import deque
from datetime import datetime

from .. import services
from ..db import connect

log = logging.getLogger(__name__)


class HardwareManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.rfid = None
        self.finger = None
        self.rfid_error = None
        self.finger_error = None
        self.events = deque(maxlen=100)
        self._event_ids = itertools.count(1)
        self._task = None
        self._task_lock = threading.Lock()
        self._device_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._last_uid = None
        self._finger_down = False

    # ------------------------------------------------------------ vòng đời

    def start(self):
        enabled = self.cfg["HARDWARE_ENABLED"]
        if enabled and self.cfg["RFID_ENABLED"]:
            try:
                from .rfid import RFIDReader
                self.rfid = RFIDReader()
                log.info("PN532 sẵn sàng (%s)", self.rfid.firmware)
            except Exception as exc:  # thiết bị chưa cắm, sai dây...
                self.rfid_error = str(exc) or exc.__class__.__name__
                log.warning("Không khởi tạo được PN532: %s", self.rfid_error)
        if enabled and self.cfg["FINGERPRINT_ENABLED"]:
            try:
                from .fingerprint import FingerprintSensor
                self.finger = FingerprintSensor(
                    self.cfg["FINGERPRINT_PORT"], self.cfg["FINGERPRINT_BAUDRATE"]
                )
                log.info("AS608 sẵn sàng (dung lượng %s mẫu)", self.finger.library_size)
            except Exception as exc:
                self.finger_error = str(exc) or exc.__class__.__name__
                log.warning("Không khởi tạo được AS608: %s", self.finger_error)

        self._thread = threading.Thread(target=self._run, name="hardware", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def online(self):
        """Trạng thái kết nối, không đụng tới thiết bị (dùng cho mọi trang)."""
        return {"rfid": self.rfid is not None, "fingerprint": self.finger is not None}

    def status(self):
        with self._task_lock:
            task = dict(self._task) if self._task else None
        count = None
        # Không chờ khoá lâu: khi đang đăng ký vân tay, luồng phần cứng giữ khoá.
        if self.finger and self._device_lock.acquire(timeout=0.5):
            try:
                count = self.finger.template_count()
            finally:
                self._device_lock.release()
        return {
            "rfid": {"ok": self.rfid is not None, "error": self.rfid_error,
                     "info": self.rfid.firmware if self.rfid else None},
            "fingerprint": {"ok": self.finger is not None, "error": self.finger_error,
                            "templates": count,
                            "capacity": self.finger.library_size if self.finger else None},
            "task": task,
        }

    # ------------------------------------------------------------ sự kiện

    def _push(self, kind, **data):
        event = {"id": next(self._event_ids), "kind": kind,
                 "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), **data}
        self.events.append(event)
        return event

    def events_after(self, after_id=0):
        return [e for e in list(self.events) if e["id"] > after_id]

    # ------------------------------------------------------------ yêu cầu từ web

    def request_enroll(self, kind, employee_id):
        if kind == "rfid" and not self.rfid:
            raise services.ServiceError("Đầu đọc RFID chưa sẵn sàng.")
        if kind == "fingerprint" and not self.finger:
            raise services.ServiceError("Cảm biến vân tay chưa sẵn sàng.")
        with self._task_lock:
            if self._task and self._task["state"] in ("waiting", "running"):
                raise services.ServiceError("Thiết bị đang bận với một yêu cầu đăng ký khác.")
            self._task = {
                "kind": kind,
                "employee_id": employee_id,
                "state": "waiting",
                "message": "Đang chuẩn bị...",
                "started": time.monotonic(),
                "cancel": False,
            }

    def cancel_task(self):
        with self._task_lock:
            if self._task and self._task["state"] in ("waiting", "running"):
                self._task["cancel"] = True

    def task_for(self, employee_id):
        with self._task_lock:
            if self._task and self._task["employee_id"] == employee_id:
                return {k: v for k, v in self._task.items() if k != "started"}
        return None

    def simulate_scan(self, conn, employee, method):
        """Giả lập một lượt quét (thử nghiệm khi chưa có phần cứng)."""
        result = services.record_scan(conn, employee, method, self.cfg, note="mô phỏng")
        return self._push("scan", simulated=True, **result)

    def delete_fingerprint(self, slot):
        if not self.finger or not self._device_lock.acquire(timeout=3):
            return False
        try:
            self.finger.delete(slot)
            return True
        except Exception as exc:
            log.warning("Xoá vân tay #%s thất bại: %s", slot, exc)
            return False
        finally:
            self._device_lock.release()

    def _update_task(self, **changes):
        with self._task_lock:
            if self._task:
                self._task.update(changes)

    def _task_cancelled(self):
        with self._task_lock:
            return bool(self._task and self._task["cancel"])

    # ------------------------------------------------------------ vòng lặp

    def _run(self):
        conn = connect(self.cfg["DATABASE"])
        while not self._stop.is_set():
            try:
                with self._task_lock:
                    task = self._task if self._task and self._task["state"] == "waiting" else None
                    if task:
                        task["state"] = "running"
                if task:
                    self._run_task(conn, task)
                    continue
                with self._device_lock:
                    self._poll_rfid(conn)
                    self._poll_finger(conn)
            except Exception:
                log.exception("Lỗi trong vòng lặp phần cứng")
                time.sleep(1)
            if not self.rfid:  # read_uid của PN532 đã tự chờ, các trường hợp khác thì nghỉ
                time.sleep(0.1 if self.finger else 0.5)
        conn.close()

    def _poll_rfid(self, conn):
        if not self.rfid:
            return
        uid = self.rfid.read_uid(timeout=0.15)
        if uid is None:
            self._last_uid = None
            return
        if uid == self._last_uid:  # thẻ vẫn đang đặt trên đầu đọc
            return
        self._last_uid = uid
        employee = services.find_employee_by_rfid(conn, uid)
        if employee is None:
            self._push("unknown", method="rfid", uid=uid)
            return
        self._push("scan", **services.record_scan(conn, employee, "rfid", self.cfg))

    def _poll_finger(self, conn):
        if not self.finger:
            return
        present = self.finger.finger_present()
        if not present:
            self._finger_down = False
            return
        if self._finger_down:  # chưa nhấc tay sau lần quét trước
            return
        self._finger_down = True
        slot, confidence = self.finger.identify()
        employee = services.find_employee_by_fingerprint(conn, slot) if slot is not None else None
        if employee is None:
            self._push("unknown", method="fingerprint", slot=slot)
            return
        result = services.record_scan(conn, employee, "fingerprint", self.cfg)
        self._push("scan", confidence=confidence, **result)

    # ------------------------------------------------------------ đăng ký

    def _run_task(self, conn, task):
        try:
            employee = conn.execute(
                "SELECT * FROM employees WHERE id = ?", (task["employee_id"],)
            ).fetchone()
            if employee is None:
                raise services.ServiceError("Nhân viên không tồn tại.")
            with self._device_lock:
                if task["kind"] == "rfid":
                    message = self._enroll_rfid(conn, employee)
                else:
                    message = self._enroll_finger(conn, employee)
            self._update_task(state="done", message=message)
            self._push("enrolled", method=task["kind"], name=employee["full_name"],
                       code=employee["code"])
        except Exception as exc:
            self._update_task(state="error", message=str(exc) or exc.__class__.__name__)

    def _enroll_rfid(self, conn, employee):
        self._update_task(message="Đưa thẻ nhân viên lại gần đầu đọc")
        deadline = time.monotonic() + self.cfg["ENROLL_TIMEOUT_SECONDS"]
        while time.monotonic() < deadline:
            if self._task_cancelled():
                raise services.ServiceError("Đã huỷ")
            uid = self.rfid.read_uid(timeout=0.3)
            if not uid:
                continue
            owner = conn.execute(
                "SELECT code, full_name FROM employees WHERE rfid_uid = ? AND id != ?",
                (uid, employee["id"]),
            ).fetchone()
            if owner:
                raise services.ServiceError(
                    f"Thẻ {uid} đã gán cho {owner['code']} - {owner['full_name']}."
                )
            conn.execute("UPDATE employees SET rfid_uid = ? WHERE id = ?", (uid, employee["id"]))
            conn.commit()
            self._last_uid = uid  # tránh chấm công ngay khi thẻ còn trên đầu đọc
            return f"Đã gán thẻ {uid}"
        raise services.ServiceError("Hết thời gian chờ quét thẻ")

    def _enroll_finger(self, conn, employee):
        slot = employee["fingerprint_id"]
        if slot is None:
            used = self.finger.used_slots()
            used |= {r[0] for r in conn.execute(
                "SELECT fingerprint_id FROM employees WHERE fingerprint_id IS NOT NULL")}
            free = [s for s in range(1, self.finger.library_size) if s not in used]
            if not free:
                raise services.ServiceError("Bộ nhớ cảm biến vân tay đã đầy.")
            slot = free[0]

        duplicate = self.finger.enroll(
            slot,
            self.cfg["ENROLL_TIMEOUT_SECONDS"],
            progress=lambda msg: self._update_task(message=msg),
            cancelled=self._task_cancelled,
        )
        if duplicate is not None:
            owner = services.find_employee_by_fingerprint(conn, duplicate)
            who = f"{owner['code']} - {owner['full_name']}" if owner else f"mẫu #{duplicate}"
            raise services.ServiceError(f"Vân tay này đã được đăng ký cho {who}.")

        conn.execute("UPDATE employees SET fingerprint_id = ? WHERE id = ?", (slot, employee["id"]))
        conn.commit()
        self._finger_down = True  # tránh chấm công khi ngón tay còn trên cảm biến
        return f"Đã lưu vân tay vào vị trí #{slot}"
