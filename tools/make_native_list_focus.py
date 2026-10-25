#!/usr/bin/env python3
"""Generate a tintable native-list 9-patch without added content padding."""
from pathlib import Path
import struct
import zlib


def render() -> bytes:
    size = 18
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            pixel = (0, 0, 0, 0)
            if 1 <= x <= 16 and 1 <= y <= 16:
                # Four-pixel rounded corners, with a broad stretchable centre.
                nearest_x = min(max(x, 5), 12)
                nearest_y = min(max(y, 5), 12)
                if (x - nearest_x) ** 2 + (y - nearest_y) ** 2 <= 16:
                    pixel = (255, 255, 255, 255)
            stretch = (y == 0 and 5 <= x <= 12) or (x == 0 and 5 <= y <= 12)
            content = (y == 17 and 1 <= x <= 16) or (x == 17 and 1 <= y <= 16)
            if stretch or content:
                pixel = (0, 0, 0, 255)
            row.extend(pixel)
        rows.append(b'\x00' + row)  # PNG filter 0 keeps pixel checks inspectable.

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b''))


if __name__ == '__main__':
    target = Path(__file__).resolve().parents[1] / 'images/ui/list_focus.9.png'
    target.write_bytes(render())
