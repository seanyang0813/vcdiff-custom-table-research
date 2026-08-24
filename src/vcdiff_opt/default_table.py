from __future__ import annotations

from .model import ADD, COPY, NOOP, RUN, CodeEntry

TABLE_SIZE = 256
TABLE_STRING_SIZE = 6 * TABLE_SIZE
DEFAULT_NEAR = 4
DEFAULT_SAME = 3
DEFAULT_MODES = 2 + DEFAULT_NEAR + DEFAULT_SAME
PAIR_BANK_START = 163
PAIR_BANK_CAPACITY = TABLE_SIZE - PAIR_BANK_START


def build_default_table() -> tuple[CodeEntry, ...]:
    table: list[CodeEntry] = [CodeEntry(RUN, 0, 0)]
    table.extend(CodeEntry(ADD, size, 0) for size in range(0, 18))

    for mode in range(DEFAULT_MODES):
        table.append(CodeEntry(COPY, 0, mode))
        table.extend(CodeEntry(COPY, size, mode) for size in range(4, 19))

    for mode in range(0, 6):
        for add_size in range(1, 5):
            for copy_size in range(4, 7):
                table.append(
                    CodeEntry(ADD, add_size, 0, COPY, copy_size, mode)
                )

    for mode in range(6, 9):
        for add_size in range(1, 5):
            table.append(CodeEntry(ADD, add_size, 0, COPY, 4, mode))

    for mode in range(DEFAULT_MODES):
        table.append(CodeEntry(COPY, 4, mode, ADD, 1, 0))

    if len(table) != TABLE_SIZE:
        raise AssertionError(f"RFC default table has {len(table)} entries")
    return tuple(table)


DEFAULT_TABLE = build_default_table()


def table_to_bytes(table: tuple[CodeEntry, ...] | list[CodeEntry]) -> bytes:
    if len(table) != TABLE_SIZE:
        raise ValueError(f"a code table must have {TABLE_SIZE} entries")
    fields = (
        (entry.inst1 for entry in table),
        (entry.inst2 for entry in table),
        (entry.size1 for entry in table),
        (entry.size2 for entry in table),
        (entry.mode1 for entry in table),
        (entry.mode2 for entry in table),
    )
    encoded = bytes(value for field in fields for value in field)
    if len(encoded) != TABLE_STRING_SIZE:
        raise AssertionError("bad table serialization length")
    return encoded


DEFAULT_TABLE_BYTES = table_to_bytes(DEFAULT_TABLE)


def validate_table(table: tuple[CodeEntry, ...] | list[CodeEntry], max_mode: int = 8) -> None:
    if len(table) != TABLE_SIZE:
        raise ValueError(f"a code table must contain {TABLE_SIZE} entries")
    required = {(RUN, 0), (ADD, 0)} | {(COPY, mode) for mode in range(max_mode + 1)}
    available: set[tuple[int, int]] = set()
    for entry in table:
        if entry.mode1 > max_mode or entry.mode2 > max_mode:
            raise ValueError("code table uses an unavailable COPY mode")
        if entry.size1 == 0 and entry.inst2 == NOOP:
            available.add((entry.inst1, entry.mode1))
    missing = sorted(required - available)
    if missing:
        raise ValueError(f"code table lacks generic entries: {missing}")

