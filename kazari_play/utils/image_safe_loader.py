"""图片安全加载工具 - 防止损坏/异常图片导致 PyQt 底层崩溃

主要风险：
1. 损坏图片：QPixmap(path) 直接加载可能导致 C++ 层 crash
2. 超大尺寸：>8192px 的图会导致内存爆炸或 Qt 内部限制
3. 异常格式：CMYK JPEG、16位 PNG、动图等可能解码失败
4. 文件过大：>20MB 的图占用内存过多

解决方案：
- 统一用 QImageReader 安全加载（比 QPixmap(path) 更稳）
- 加载前检查文件大小（>20MB 拒绝）
- 先 read() 出原图，再用 QImage.scaled 缩放（保持纵横比）
  注：不再使用 QImageReader.setScaledSize，因为它不保持纵横比，
  且与 setAutoTransform 组合在损坏 EXIF 上可能触发 Qt decoder
  内部递归导致 STATUS_STACK_BUFFER_OVERRUN。
- 转换为 ARGB32 格式（最安全的像素格式），转换后再次检查 isNull
- 全程 try/except，失败返回 None

注意：本模块只能防 Python 层异常，无法防 C++ 致命崩溃（如
STATUS_STACK_BUFFER_OVERRUN）。通过前置尺寸/格式检查降低触发概率。
"""
import os
from typing import Optional
from PyQt5.QtGui import QPixmap, QImage, QImageReader
from PyQt5.QtCore import Qt, QSize

# 图片大小限制
_MAX_FILE_BYTES = 20 * 1024 * 1024  # 20MB
# 图片单边尺寸限制（超过则缩小）
_MAX_DIMENSION = 8192


def safe_load_pixmap(path: str, max_dimension: int = _MAX_DIMENSION) -> Optional[QPixmap]:
    """安全加载图片为 QPixmap

    Args:
        path: 图片路径
        max_dimension: 单边最大像素，超过则等比缩小（默认 8192）

    Returns:
        QPixmap 或 None（加载失败）
    """
    if not path or not os.path.exists(path):
        return None

    # 参数防御
    if not isinstance(max_dimension, int) or max_dimension <= 0:
        max_dimension = _MAX_DIMENSION
    if max_dimension > _MAX_DIMENSION:
        max_dimension = _MAX_DIMENSION

    # 1. 文件大小检查
    try:
        file_size = os.path.getsize(path)
    except OSError:
        return None
    if file_size > _MAX_FILE_BYTES:
        return None

    # 2. 用 QImageReader 安全加载
    try:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        # 注：不再使用 setScaledSize（不保持纵横比且与 AutoTransform 组合有风险）
        # 注：不使用 canRead()，因为它在某些格式上返回 False 但实际可读
        img = reader.read()
        # QImageReader.ImageReaderError.NoError == 0
        if img.isNull() or reader.error() != 0:
            return None

        # 3. 等比缩小到 max_dimension 内（用 QImage.scaled，保持纵横比）
        w, h = img.width(), img.height()
        if w > max_dimension or h > max_dimension:
            img = img.scaled(
                max_dimension, max_dimension,
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            if img.isNull():
                return None

        # 4. 转换为 ARGB32 格式（最安全的像素格式），转换后再次检查
        if img.format() != QImage.Format_ARGB32:
            img = img.convertToFormat(QImage.Format_ARGB32)
            if img.isNull():
                return None

        # 5. QImage → QPixmap
        pm = QPixmap.fromImage(img)
        if pm.isNull():
            return None
        return pm
    except Exception:
        return None


def safe_load_pixmap_scaled(
    path: str,
    target_size: QSize,
    max_dimension: int = _MAX_DIMENSION
) -> Optional[QPixmap]:
    """安全加载图片并缩放到目标尺寸

    Args:
        path: 图片路径
        target_size: 目标尺寸
        max_dimension: 原图单边最大像素（解码时限制）

    Returns:
        QPixmap 或 None（加载失败）
    """
    # target_size 防御
    if (target_size is None or not target_size.isValid()
            or target_size.width() <= 0 or target_size.height() <= 0):
        return None
    pm = safe_load_pixmap(path, max_dimension)
    if pm is None:
        return None
    try:
        return pm.scaled(
            target_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
    except Exception:
        return None
