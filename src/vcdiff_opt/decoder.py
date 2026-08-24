from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .codec import VCDIFF_MAGIC, VCD_CODETABLE, VCD_SOURCE
from .default_table import (
    DEFAULT_NEAR,
    DEFAULT_SAME,
    DEFAULT_TABLE,
    DEFAULT_TABLE_BYTES,
    TABLE_SIZE,
    TABLE_STRING_SIZE,
    validate_table,
)
from .model import ADD, COPY, NOOP, RUN, CodeEntry
from .varint import decode_varint


def table_from_bytes(data: bytes) -> tuple[CodeEntry, ...]:
    if len(data) != TABLE_STRING_SIZE:
        raise ValueError("decoded custom table is not 1536 bytes")
    fields = [data[index * TABLE_SIZE : (index + 1) * TABLE_SIZE] for index in range(6)]
    table = tuple(
        CodeEntry(
            inst1=fields[0][index],
            inst2=fields[1][index],
            size1=fields[2][index],
            size2=fields[3][index],
            mode1=fields[4][index],
            mode2=fields[5][index],
        )
        for index in range(TABLE_SIZE)
    )
    return table


@dataclass
class _Reader:
    data: bytes
    offset: int = 0

    def byte(self) -> int:
        if self.offset >= len(self.data):
            raise ValueError("truncated VCDIFF input")
        value = self.data[self.offset]
        self.offset += 1
        return value

    def integer(self) -> int:
        value, self.offset = decode_varint(self.data, self.offset)
        return value

    def take(self, size: int) -> bytes:
        end = self.offset + size
        if end > len(self.data):
            raise ValueError("truncated VCDIFF section")
        value = self.data[self.offset:end]
        self.offset = end
        return value


def _decode_address(
    reader: _Reader,
    mode: int,
    here: int,
    near: list[int],
    same: list[int],
) -> int:
    same_start = 2 + len(near)
    if mode < same_start:
        value = reader.integer()
        if mode == 0:
            address = value
        elif mode == 1:
            if value > here:
                raise ValueError("HERE address underflow")
            address = here - value
        else:
            address = near[mode - 2] + value
    else:
        same_mode = mode - same_start
        if same_mode >= len(same) // 256:
            raise ValueError("COPY mode exceeds SAME cache")
        encoded = reader.byte()
        address = same[same_mode * 256 + encoded]
    return address


def _decode_half(
    inst: int,
    encoded_size: int,
    mode: int,
    instruction_reader: _Reader,
    data_reader: _Reader,
    address_reader: _Reader,
    source_segment: bytes,
    output: bytearray,
    near: list[int],
    same: list[int],
    next_slot: int,
) -> int:
    if inst == NOOP:
        return next_slot
    size = encoded_size or instruction_reader.integer()
    if size <= 0:
        raise ValueError("zero-sized VCDIFF instruction")
    if inst == ADD:
        output.extend(data_reader.take(size))
    elif inst == RUN:
        output.extend(bytes((data_reader.byte(),)) * size)
    elif inst == COPY:
        here = len(source_segment) + len(output)
        address = _decode_address(address_reader, mode, here, near, same)
        if address >= here:
            raise ValueError("COPY address is not backward")
        for offset in range(size):
            cursor = address + offset
            if cursor < len(source_segment):
                output.append(source_segment[cursor])
            else:
                target_cursor = cursor - len(source_segment)
                if target_cursor >= len(output):
                    raise ValueError("COPY exceeds available target bytes")
                output.append(output[target_cursor])
        if near:
            near[next_slot] = address
            next_slot = (next_slot + 1) % len(near)
        if same:
            same[address % len(same)] = address
    else:
        raise ValueError(f"unknown VCDIFF instruction {inst}")
    return next_slot


def decode_file(
    patch: bytes,
    source: bytes,
    *,
    expected_target_size: int | None = None,
) -> bytes:
    reader = _Reader(patch)
    if reader.take(4) != VCDIFF_MAGIC:
        raise ValueError("bad VCDIFF magic/version")
    header_indicator = reader.byte()
    if header_indicator & ~VCD_CODETABLE:
        raise ValueError("unsupported VCDIFF header feature")

    table: Sequence[CodeEntry] = DEFAULT_TABLE
    near_size = DEFAULT_NEAR
    same_size = DEFAULT_SAME
    if header_indicator & VCD_CODETABLE:
        code_table_data_length = reader.integer()
        code_table_start = reader.offset
        near_size = reader.byte()
        same_size = reader.byte()
        nested_size = code_table_data_length - 2
        if nested_size <= 0:
            raise ValueError("empty custom code-table delta")
        nested = reader.take(nested_size)
        if reader.offset - code_table_start != code_table_data_length:
            raise ValueError("custom code-table length mismatch")
        decoded_table = decode_file(
            nested,
            DEFAULT_TABLE_BYTES,
            expected_target_size=TABLE_STRING_SIZE,
        )
        table = table_from_bytes(decoded_table)
        validate_table(table, 1 + near_size + same_size)

    output_file = bytearray()
    while reader.offset < len(patch):
        window_indicator = reader.byte()
        if window_indicator & ~VCD_SOURCE:
            raise ValueError("unsupported VCDIFF window feature")
        if window_indicator & VCD_SOURCE:
            source_length = reader.integer()
            source_position = reader.integer()
            source_segment = source[source_position : source_position + source_length]
            if len(source_segment) != source_length:
                raise ValueError("VCD_SOURCE segment exceeds dictionary")
        else:
            source_segment = b""

        delta_length = reader.integer()
        delta_start = reader.offset
        target_length = reader.integer()
        if reader.byte() != 0:
            raise ValueError("secondary-compressed sections are unsupported")
        data_length = reader.integer()
        instruction_length = reader.integer()
        address_length = reader.integer()
        data_reader = _Reader(reader.take(data_length))
        instruction_reader = _Reader(reader.take(instruction_length))
        address_reader = _Reader(reader.take(address_length))
        if reader.offset - delta_start != delta_length:
            raise ValueError("delta encoding length mismatch")

        window_output = bytearray()
        near = [0] * near_size
        same = [0] * (same_size * 256)
        next_slot = 0
        while instruction_reader.offset < len(instruction_reader.data):
            opcode = instruction_reader.byte()
            entry = table[opcode]
            next_slot = _decode_half(
                entry.inst1,
                entry.size1,
                entry.mode1,
                instruction_reader,
                data_reader,
                address_reader,
                source_segment,
                window_output,
                near,
                same,
                next_slot,
            )
            next_slot = _decode_half(
                entry.inst2,
                entry.size2,
                entry.mode2,
                instruction_reader,
                data_reader,
                address_reader,
                source_segment,
                window_output,
                near,
                same,
                next_slot,
            )
        if len(window_output) != target_length:
            raise ValueError("decoded target window has the wrong length")
        if data_reader.offset != len(data_reader.data):
            raise ValueError("unused data-section bytes")
        if address_reader.offset != len(address_reader.data):
            raise ValueError("unused address-section bytes")
        output_file.extend(window_output)

    if expected_target_size is not None and len(output_file) != expected_target_size:
        raise ValueError("decoded target file has the wrong length")
    return bytes(output_file)

