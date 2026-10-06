"""Lưu ảnh nhân viên: cắt vuông, thu nhỏ, chuyển sang JPEG."""
import secrets
from pathlib import Path

from .services import ServiceError

SIZE = 512


def save_photo(upload, photo_dir, emp_id):
    """Lưu file upload, trả về tên file mới. Tên có chuỗi ngẫu nhiên để trình duyệt
    không dùng lại ảnh cũ trong cache khi đổi ảnh."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        img = Image.open(upload.stream)
        img = ImageOps.exif_transpose(img)  # ảnh chụp điện thoại thường bị xoay
        img = img.convert("RGB")
    except (UnidentifiedImageError, OSError):
        raise ServiceError("File không phải ảnh hợp lệ.")
    return save_image(img, photo_dir, emp_id)


def save_image(img, photo_dir, emp_id):
    """Cắt vuông, thu nhỏ và lưu một ảnh PIL; trả về tên file."""
    from PIL import Image, ImageOps

    img = ImageOps.fit(img.convert("RGB"), (SIZE, SIZE), Image.LANCZOS)
    Path(photo_dir).mkdir(parents=True, exist_ok=True)
    name = f"{emp_id}-{secrets.token_hex(4)}.jpg"
    img.save(Path(photo_dir) / name, "JPEG", quality=85, optimize=True)
    return name


def delete_photo(photo_dir, name):
    if name:
        (Path(photo_dir) / name).unlink(missing_ok=True)
