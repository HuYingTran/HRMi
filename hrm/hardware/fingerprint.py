"""Cảm biến vân tay AS608 (giao thức tương thích R30x) qua UART."""
import time


class FingerprintError(Exception):
    pass


class FingerprintSensor:
    def __init__(self, port, baudrate):
        import serial
        import adafruit_fingerprint as af

        self._af = af
        uart = serial.Serial(port, baudrate=baudrate, timeout=1)
        self._finger = af.Adafruit_Fingerprint(uart)
        if self._finger.read_sysparam() != af.OK:
            raise FingerprintError("Không đọc được thông số cảm biến")
        self.library_size = self._finger.library_size

    # --------------------------------------------------------- tra cứu

    def finger_present(self):
        return self._finger.get_image() == self._af.OK

    def identify(self):
        """Chụp và tìm vân tay. Gọi khi finger_present() vừa trả về True.

        Trả về (slot, confidence), hoặc (None, 0) nếu không khớp.
        """
        if self._finger.image_2_tz(1) != self._af.OK:
            return None, 0
        if self._finger.finger_search() != self._af.OK:
            return None, 0
        return self._finger.finger_id, self._finger.confidence

    def used_slots(self):
        if self._finger.read_templates() != self._af.OK:
            raise FingerprintError("Không đọc được danh sách mẫu vân tay")
        return set(self._finger.templates)

    def template_count(self):
        if self._finger.count_templates() != self._af.OK:
            return None
        return self._finger.template_count

    def delete(self, slot):
        if self._finger.delete_model(slot) != self._af.OK:
            raise FingerprintError(f"Không xoá được mẫu vân tay #{slot}")

    # --------------------------------------------------------- đăng ký

    def _wait_finger(self, deadline, cancelled):
        while time.monotonic() < deadline:
            if cancelled():
                raise FingerprintError("Đã huỷ")
            if self._finger.get_image() == self._af.OK:
                return
            time.sleep(0.05)
        raise FingerprintError("Hết thời gian chờ đặt ngón tay")

    def _wait_removed(self, deadline, cancelled):
        while time.monotonic() < deadline:
            if cancelled():
                raise FingerprintError("Đã huỷ")
            if self._finger.get_image() == self._af.NOFINGER:
                return
            time.sleep(0.05)
        raise FingerprintError("Hết thời gian chờ nhấc ngón tay")

    def enroll(self, slot, timeout, progress, cancelled):
        """Đăng ký vân tay vào vị trí `slot` (ghi đè nếu đã có).

        `progress(msg)` được gọi ở mỗi bước, `cancelled()` trả True để dừng.
        Trả về slot cũ nếu vân tay này đã có trong thư viện (để báo trùng),
        ngược lại trả None sau khi lưu thành công.
        """
        deadline = time.monotonic() + timeout
        for step in (1, 2):
            progress(f"Đặt ngón tay lên cảm biến (lần {step}/2)")
            self._wait_finger(deadline, cancelled)
            if self._finger.image_2_tz(step) != self._af.OK:
                raise FingerprintError("Ảnh vân tay không rõ, hãy thử lại")
            if step == 1:
                if self._finger.finger_search() == self._af.OK and self._finger.finger_id != slot:
                    return self._finger.finger_id
                progress("Nhấc ngón tay ra")
                self._wait_removed(deadline, cancelled)

        progress("Đang tạo mẫu vân tay...")
        if self._finger.create_model() != self._af.OK:
            raise FingerprintError("Hai lần quét không khớp nhau, hãy thử lại")
        if self._finger.store_model(slot) != self._af.OK:
            raise FingerprintError("Không lưu được mẫu vào cảm biến")
        return None
