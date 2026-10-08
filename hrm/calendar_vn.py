"""Âm lịch Việt Nam (múi giờ +7) và danh sách ngày nghỉ lễ gợi ý theo Bộ luật Lao động 2019.

Thuật toán đổi âm - dương lịch của Hồ Ngọc Đức (tính điểm sóc và trung khí theo thiên văn).
"""
import math
from datetime import date, timedelta

TZ = 7.0


def _jd_from_date(d, m, y):
    a = (14 - m) // 12
    y2 = y + 4800 - a
    m2 = m + 12 * a - 3
    jd = d + (153 * m2 + 2) // 5 + 365 * y2 + y2 // 4 - y2 // 100 + y2 // 400 - 32045
    if jd < 2299161:
        jd = d + (153 * m2 + 2) // 5 + 365 * y2 + y2 // 4 - 32083
    return jd


def _jd_to_date(jd):
    if jd > 2299160:
        a = jd + 32044
        b = (4 * a + 3) // 146097
        c = a - (b * 146097) // 4
    else:
        b, c = 0, jd + 32082
    d = (4 * c + 3) // 1461
    e = c - (1461 * d) // 4
    m = (5 * e + 2) // 153
    return date(b * 100 + d - 4800 + m // 10, m + 3 - 12 * (m // 10), e - (153 * m + 2) // 5 + 1)


def _new_moon(k):
    """Thời điểm (ngày Julius, giờ UT) của điểm sóc thứ k tính từ 1/1/1900."""
    t = k / 1236.85
    t2, t3 = t * t, t * t * t
    dr = math.pi / 180
    jd1 = 2415020.75933 + 29.53058868 * k + 0.0001178 * t2 - 0.000000155 * t3
    jd1 += 0.00033 * math.sin((166.56 + 132.87 * t - 0.009173 * t2) * dr)
    m = 359.2242 + 29.10535608 * k - 0.0000333 * t2 - 0.00000347 * t3
    mpr = 306.0253 + 385.81691806 * k + 0.0107306 * t2 + 0.00001236 * t3
    f = 21.2964 + 390.67050646 * k - 0.0016528 * t2 - 0.00000239 * t3
    c1 = (0.1734 - 0.000393 * t) * math.sin(m * dr) + 0.0021 * math.sin(2 * dr * m)
    c1 = c1 - 0.4068 * math.sin(mpr * dr) + 0.0161 * math.sin(dr * 2 * mpr)
    c1 = c1 - 0.0004 * math.sin(dr * 3 * mpr)
    c1 = c1 + 0.0104 * math.sin(dr * 2 * f) - 0.0051 * math.sin(dr * (m + mpr))
    c1 = c1 - 0.0074 * math.sin(dr * (m - mpr)) + 0.0004 * math.sin(dr * (2 * f + m))
    c1 = c1 - 0.0004 * math.sin(dr * (2 * f - m)) - 0.0006 * math.sin(dr * (2 * f + mpr))
    c1 = c1 + 0.0010 * math.sin(dr * (2 * f - mpr)) + 0.0005 * math.sin(dr * (2 * mpr + m))
    if t < -11:
        delta = 0.001 + 0.000839 * t + 0.0002261 * t2 - 0.00000845 * t3 - 0.000000081 * t * t3
    else:
        delta = -0.000278 + 0.000265 * t + 0.000262 * t2
    return jd1 + c1 - delta


def _new_moon_day(k):
    return math.floor(_new_moon(k) + 0.5 + TZ / 24)


def _sun_longitude(jdn):
    """Cung hoàng đạo (0..11, mỗi cung 30°) của mặt trời lúc 0h giờ địa phương ngày jdn."""
    t = (jdn - 0.5 - TZ / 24 - 2451545.0) / 36525
    t2 = t * t
    dr = math.pi / 180
    m = 357.52910 + 35999.05030 * t - 0.0001559 * t2 - 0.00000048 * t * t2
    l0 = 280.46645 + 36000.76983 * t + 0.0003032 * t2
    dl = (1.914600 - 0.004817 * t - 0.000014 * t2) * math.sin(dr * m)
    dl += (0.019993 - 0.000101 * t) * math.sin(dr * 2 * m) + 0.000290 * math.sin(dr * 3 * m)
    lon = (l0 + dl) * dr
    lon -= math.pi * 2 * math.floor(lon / (math.pi * 2))
    return math.floor(lon / math.pi * 6)


def _lunar_month11(y):
    """Ngày bắt đầu tháng 11 âm lịch (tháng chứa Đông chí) của năm dương lịch y."""
    off = _jd_from_date(31, 12, y) - 2415021
    k = math.floor(off / 29.530588853)
    nm = _new_moon_day(k)
    if _sun_longitude(nm) >= 9:
        nm = _new_moon_day(k - 1)
    return nm


def _leap_month_offset(a11):
    k = math.floor((a11 - 2415021.076998695) / 29.530588853 + 0.5)
    i = 1
    arc = _sun_longitude(_new_moon_day(k + i))
    while True:
        last = arc
        i += 1
        arc = _sun_longitude(_new_moon_day(k + i))
        if arc == last or i >= 14:
            break
    return i - 1


def lunar_to_solar(day, month, year, leap=False):
    """Ngày dương lịch của ngày `day` tháng `month` (âm lịch) năm âm lịch `year`."""
    if month < 11:
        a11, b11 = _lunar_month11(year - 1), _lunar_month11(year)
    else:
        a11, b11 = _lunar_month11(year), _lunar_month11(year + 1)
    k = math.floor(0.5 + (a11 - 2415021.076998695) / 29.530588853)
    off = month - 11
    if off < 0:
        off += 12
    if b11 - a11 > 365:
        leap_off = _leap_month_offset(a11)
        leap_month = leap_off - 2
        if leap_month < 0:
            leap_month += 12
        if leap and month != leap_month:
            raise ValueError("Năm này không có tháng nhuận đó.")
        if leap or off >= leap_off:
            off += 1
    return _jd_to_date(_new_moon_day(k + off) + day - 1)


def suggested_holidays(year, work_days):
    """Ngày nghỉ lễ hưởng nguyên lương (Điều 112 BLLĐ 2019) trong năm dương lịch `year`.

    Trả về [(ngày, tên)], kèm ngày nghỉ bù khi ngày lễ trùng ngày nghỉ hằng tuần.
    Lịch nghỉ Tết và ngày nghỉ liền kề Quốc khánh do Thủ tướng quyết định hằng năm,
    nên đây chỉ là gợi ý: 1 ngày cuối năm âm + mùng 1-4, và ngày 1/9.
    """
    tet = lunar_to_solar(1, 1, year)
    days = [(date(year, 1, 1), "Tết Dương lịch")]
    days.append((tet - timedelta(days=1), "Tết Âm lịch (cuối năm)"))
    days += [(tet + timedelta(days=i), f"Tết Âm lịch (mùng {i + 1})") for i in range(4)]
    days += [
        (lunar_to_solar(10, 3, year), "Giỗ Tổ Hùng Vương"),
        (date(year, 4, 30), "Ngày Chiến thắng"),
        (date(year, 5, 1), "Quốc tế Lao động"),
        (date(year, 9, 1), "Quốc khánh (ngày liền kề)"),
        (date(year, 9, 2), "Quốc khánh"),
    ]
    taken = {d for d, _ in days}
    out = []
    for d, name in sorted(days):
        out.append((d, name))
        if d.weekday() not in work_days:
            # nghỉ bù vào ngày làm việc kế tiếp chưa phải ngày lễ
            sub = d + timedelta(days=1)
            while sub.weekday() not in work_days or sub in taken:
                sub += timedelta(days=1)
            taken.add(sub)
            out.append((sub, f"Nghỉ bù {name}"))
    return sorted(d for d in out if d[0].year == year)
