"""Writes assets/TalesPIP.ico from the icon drawn in tales_pip.py.

Run after changing icon_pixmap() so the exe icon stays in sync:
    python tools/make_icon.py
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QBuffer, QByteArray
from PyQt6.QtWidgets import QApplication

# A QApplication has to exist before any QPixmap; importing the app module
# afterwards keeps that order.
_app = QApplication(sys.argv)

import tales_pip  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "assets", "TalesPIP.ico")


def png_bytes(size):
    # QBuffer does not take ownership, so the QByteArray must outlive it.
    store = QByteArray()
    buffer = QBuffer(store)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    tales_pip.icon_pixmap(size).save(buffer, "PNG")
    buffer.close()
    return bytes(store)


def main():
    images = [(size, png_bytes(size)) for size in SIZES]

    header = struct.pack("<HHH", 0, 1, len(images))
    entries, blobs = b"", b""
    offset = len(header) + 16 * len(images)
    for size, data in images:
        dim = 0 if size >= 256 else size          # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32,
                                len(data), offset)
        blobs += data
        offset += len(data)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as f:
        f.write(header + entries + blobs)
    print("wrote %s (%d bytes, %d sizes)" % (OUT, os.path.getsize(OUT), len(images)))


if __name__ == "__main__":
    main()
