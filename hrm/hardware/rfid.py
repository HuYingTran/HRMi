"""Đầu đọc thẻ RFID/NFC PN532 qua I2C."""


class RFIDReader:
    def __init__(self):
        import board
        import busio
        from adafruit_pn532.i2c import PN532_I2C

        i2c = busio.I2C(board.SCL, board.SDA)
        self._pn532 = PN532_I2C(i2c, debug=False)
        ic, ver, rev, _support = self._pn532.firmware_version
        self.firmware = f"PN5{ic:02x} v{ver}.{rev}"
        self._pn532.SAM_configuration()

    def read_uid(self, timeout=0.2):
        """Trả về UID dạng chuỗi hex in hoa, hoặc None nếu không có thẻ."""
        uid = self._pn532.read_passive_target(timeout=timeout)
        return bytes(uid).hex().upper() if uid else None
