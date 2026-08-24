from __future__ import annotations


def encode_varint(value: int) -> bytes:
    """Encode RFC 3284's big-endian base-128 unsigned integer."""
    if value < 0:
        raise ValueError("VCDIFF integers are unsigned")
    digits = [value & 0x7F]
    value >>= 7
    while value:
        digits.append(value & 0x7F)
        value >>= 7
    digits.reverse()
    for index in range(len(digits) - 1):
        digits[index] |= 0x80
    return bytes(digits)


def varint_size(value: int) -> int:
    return len(encode_varint(value))


def decode_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    value = 0
    start = offset
    while True:
        if offset >= len(data):
            raise ValueError("truncated VCDIFF integer")
        byte = data[offset]
        offset += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, offset
        if offset - start > 10:
            raise ValueError("oversized VCDIFF integer")

