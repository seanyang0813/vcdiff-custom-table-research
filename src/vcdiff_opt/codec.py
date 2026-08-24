from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .default_table import (
    DEFAULT_NEAR,
    DEFAULT_SAME,
    DEFAULT_TABLE,
    DEFAULT_TABLE_BYTES,
    PAIR_BANK_CAPACITY,
    PAIR_BANK_START,
    TABLE_SIZE,
    TABLE_STRING_SIZE,
    table_to_bytes,
    validate_table,
)
from .model import ADD, COPY, RUN, Atom, CodeEntry, Instruction, Pattern, WindowTrace
from .parser import ParseResult, encode_instruction_section, optimal_parse
from .varint import encode_varint

VCDIFF_MAGIC = bytes((0xD6, 0xC3, 0xC4, 0x00))
VCD_CODETABLE = 0x02
VCD_SOURCE = 0x01


@dataclass(frozen=True)
class WindowEncoding:
    encoded: bytes
    data_length: int
    instruction_length: int
    address_length: int
    parse: ParseResult


@dataclass(frozen=True)
class FileEncoding:
    encoded: bytes
    file_header_length: int
    table_delta_length: int
    windows: tuple[WindowEncoding, ...]


def build_custom_table(
    selected: Sequence[Pattern], physical_slots: int
) -> tuple[CodeEntry, ...]:
    if not 1 <= physical_slots <= PAIR_BANK_CAPACITY:
        raise ValueError(
            f"physical_slots must be in [1, {PAIR_BANK_CAPACITY}]"
        )
    unique = tuple(sorted(set(selected)))
    if not unique:
        raise ValueError("a custom table needs at least one selected pattern")
    if len(unique) > physical_slots:
        raise ValueError("more selected patterns than physical table slots")
    table = list(DEFAULT_TABLE)
    entries = [CodeEntry.from_pattern(pattern) for pattern in unique]
    entries.extend([entries[0]] * (physical_slots - len(entries)))
    table[PAIR_BANK_START : PAIR_BANK_START + physical_slots] = entries
    validate_table(table)
    return tuple(table)


def _encode_address_section(window: WindowTrace) -> bytes:
    near = [0] * DEFAULT_NEAR
    same = [0] * (DEFAULT_SAME * 256)
    next_slot = 0
    output = bytearray()
    for instruction in window.instructions:
        if instruction.type_id != COPY:
            continue
        if instruction.address is None:
            raise ValueError("COPY address missing")
        address = instruction.address
        here = window.source_length + instruction.position
        mode = instruction.mode
        same_start = 2 + DEFAULT_NEAR
        if address >= here:
            raise ValueError(
                f"COPY at {instruction.position} has non-backward address {address}"
            )
        if mode == 0:
            output.extend(encode_varint(address))
        elif mode == 1:
            output.extend(encode_varint(here - address))
        elif mode < same_start:
            slot = mode - 2
            if address < near[slot]:
                raise ValueError("negative NEAR delta in trace")
            output.extend(encode_varint(address - near[slot]))
        elif mode < same_start + DEFAULT_SAME:
            same_slot = (mode - same_start) * 256 + (address % 256)
            if same[same_slot] != address:
                raise ValueError("trace requests a SAME-cache miss")
            output.append(address % 256)
        else:
            raise ValueError(f"COPY mode {mode} exceeds the configured caches")

        near[next_slot] = address
        next_slot = (next_slot + 1) % DEFAULT_NEAR
        same[address % len(same)] = address
    return bytes(output)


def _encode_data_section(window: WindowTrace, target: bytes) -> bytes:
    output = bytearray()
    for instruction in window.instructions:
        absolute = window.target_offset + instruction.position
        if instruction.type_id == ADD:
            output.extend(target[absolute : absolute + instruction.size])
        elif instruction.type_id == RUN:
            if instruction.run_byte is None:
                raise ValueError("RUN byte missing")
            expected = bytes((instruction.run_byte,)) * instruction.size
            if target[absolute : absolute + instruction.size] != expected:
                raise ValueError("trace RUN does not reproduce target bytes")
            output.append(instruction.run_byte)
    return bytes(output)


def replay_window(window: WindowTrace, source: bytes, target: bytes) -> bytes:
    source_segment = (
        source[window.source_position : window.source_position + window.source_length]
        if window.source_used
        else b""
    )
    if len(source_segment) != window.source_length:
        raise ValueError("source window lies outside the source file")
    output = bytearray()
    for instruction in window.instructions:
        absolute = window.target_offset + instruction.position
        if instruction.type_id == ADD:
            output.extend(target[absolute : absolute + instruction.size])
        elif instruction.type_id == RUN:
            if instruction.run_byte is None:
                raise ValueError("RUN byte missing")
            output.extend(bytes((instruction.run_byte,)) * instruction.size)
        elif instruction.type_id == COPY:
            if instruction.address is None:
                raise ValueError("COPY address missing")
            address = instruction.address
            from_source = address < window.source_length
            if from_source != instruction.source_copy:
                raise ValueError("COPY provenance disagrees with its RFC address")
            if from_source:
                end = address + instruction.size
                if end > len(source_segment):
                    raise ValueError("source COPY exceeds source segment")
                output.extend(source_segment[address:end])
            else:
                target_address = address - window.source_length
                if target_address >= len(output):
                    raise ValueError("target COPY is not backward")
                for offset in range(instruction.size):
                    output.append(output[target_address + offset])
        else:
            raise ValueError("unknown instruction type")
    expected = target[
        window.target_offset : window.target_offset + window.target_length
    ]
    if bytes(output) != expected:
        raise ValueError(f"logical trace does not reproduce target window {window.index}")
    return bytes(output)


def encode_window(
    window: WindowTrace,
    source: bytes,
    target: bytes,
    table: Sequence[CodeEntry],
) -> WindowEncoding:
    replay_window(window, source, target)
    parse = optimal_parse(window.instructions, table)
    data = _encode_data_section(window, target)
    instructions = encode_instruction_section(window.instructions, table, parse)
    addresses = _encode_address_section(window)

    delta_header = b"".join(
        (
            encode_varint(window.target_length),
            b"\x00",
            encode_varint(len(data)),
            encode_varint(len(instructions)),
            encode_varint(len(addresses)),
        )
    )
    delta_length = len(delta_header) + len(data) + len(instructions) + len(addresses)
    window_header = bytearray((VCD_SOURCE if window.source_used else 0,))
    if window.source_used:
        window_header.extend(encode_varint(window.source_length))
        window_header.extend(encode_varint(window.source_position))
    window_header.extend(encode_varint(delta_length))
    encoded = bytes(window_header) + delta_header + data + instructions + addresses
    return WindowEncoding(
        encoded=encoded,
        data_length=len(data),
        instruction_length=len(instructions),
        address_length=len(addresses),
        parse=parse,
    )


def _table_delta_trace(custom_table_bytes: bytes, physical_slots: int) -> WindowTrace:
    if len(custom_table_bytes) != TABLE_STRING_SIZE:
        raise ValueError("bad custom table string length")
    if not 1 <= physical_slots <= PAIR_BANK_CAPACITY:
        raise ValueError("bad physical slot count")

    for field in range(6):
        field_start = field * TABLE_SIZE
        changed_start = field_start + PAIR_BANK_START
        changed_end = changed_start + physical_slots
        if (
            custom_table_bytes[field_start:changed_start]
            != DEFAULT_TABLE_BYTES[field_start:changed_start]
        ):
            raise ValueError("canonical table delta changed bytes before its bank")
        if custom_table_bytes[changed_end : field_start + TABLE_SIZE] != DEFAULT_TABLE_BYTES[
            changed_end : field_start + TABLE_SIZE
        ]:
            raise ValueError("canonical table delta changed bytes after its bank")

    instructions: list[Instruction] = []
    position = 0

    def append_copy(size: int, address: int) -> None:
        nonlocal position
        if size == 0:
            return
        instructions.append(
            Instruction(
                position=position,
                type_id=COPY,
                size=size,
                mode=0,
                address=address,
                source_copy=True,
            )
        )
        position += size

    def append_add(size: int) -> None:
        nonlocal position
        instructions.append(Instruction(position=position, type_id=ADD, size=size))
        position += size

    append_copy(PAIR_BANK_START, 0)
    for field in range(6):
        append_add(physical_slots)
        if field < 5:
            append_copy(
                TABLE_SIZE - physical_slots,
                field * TABLE_SIZE + PAIR_BANK_START + physical_slots,
            )
        else:
            append_copy(
                TABLE_SIZE - PAIR_BANK_START - physical_slots,
                field * TABLE_SIZE + PAIR_BANK_START + physical_slots,
            )
    if position != TABLE_STRING_SIZE:
        raise AssertionError("canonical table delta does not cover 1536 bytes")
    return WindowTrace(
        index=0,
        target_offset=0,
        target_length=TABLE_STRING_SIZE,
        source_used=True,
        source_position=0,
        source_length=TABLE_STRING_SIZE,
        instructions=tuple(instructions),
    )


def encode_table_delta(
    custom_table: Sequence[CodeEntry], physical_slots: int
) -> bytes:
    custom_bytes = table_to_bytes(tuple(custom_table))
    trace = _table_delta_trace(custom_bytes, physical_slots)
    window = encode_window(trace, DEFAULT_TABLE_BYTES, custom_bytes, DEFAULT_TABLE)
    return VCDIFF_MAGIC + b"\x00" + window.encoded


def encode_file_header(
    table: Sequence[CodeEntry] = DEFAULT_TABLE,
    physical_slots: int = 0,
) -> tuple[bytes, int]:
    """Return the RFC file header and nested table-delta byte count."""
    table_tuple = tuple(table)
    if physical_slots == 0:
        if table_tuple != DEFAULT_TABLE:
            raise ValueError("a non-default table requires physical slots")
        return VCDIFF_MAGIC + b"\x00", 0
    nested = encode_table_delta(table_tuple, physical_slots)
    code_table_data_length = 2 + len(nested)
    header = b"".join(
        (
            VCDIFF_MAGIC,
            bytes((VCD_CODETABLE,)),
            encode_varint(code_table_data_length),
            bytes((DEFAULT_NEAR, DEFAULT_SAME)),
            nested,
        )
    )
    return header, len(nested)


def encode_file(
    windows: Sequence[WindowTrace],
    source: bytes,
    target: bytes,
    *,
    table: Sequence[CodeEntry] = DEFAULT_TABLE,
    physical_slots: int = 0,
) -> FileEncoding:
    table_tuple = tuple(table)
    file_header, table_delta_length = encode_file_header(
        table_tuple, physical_slots
    )

    encoded_windows = tuple(
        encode_window(window, source, target, table_tuple) for window in windows
    )
    encoded = file_header + b"".join(window.encoded for window in encoded_windows)
    return FileEncoding(
        encoded=encoded,
        file_header_length=len(file_header),
        table_delta_length=table_delta_length,
        windows=encoded_windows,
    )
