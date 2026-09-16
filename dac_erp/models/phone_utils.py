import re


def normalize_phone_vn(phone):
    """Chuẩn hoá số điện thoại VN về dạng 0XXXXXXXXX.

    +84909333444 / 84909333444 / 0909333444 → 0909333444
    Trả về '' nếu không hợp lệ hoặc đầu vào rỗng.
    """
    if not phone:
        return ''
    digits = re.sub(r'\D', '', str(phone))
    if digits.startswith('84') and len(digits) in (11, 12):
        digits = '0' + digits[2:]
    if len(digits) < 9 or len(digits) > 12:
        return ''
    return digits
