"""Standard-library UUIDv7 identifiers."""

from __future__ import annotations

import secrets
import threading
import time
import uuid


_UUID7_LOCK = threading.Lock()
_LAST_UNIX_MS = -1
_LAST_RANDOM = -1
_RANDOM_BITS = 74
_RANDOM_MASK = (1 << _RANDOM_BITS) - 1


def generate_id() -> uuid.UUID:
    """Return a process-monotonic UUIDv7 compatible with Python 3.13."""

    global _LAST_UNIX_MS, _LAST_RANDOM
    with _UUID7_LOCK:
        unix_ms = time.time_ns() // 1_000_000
        if unix_ms > _LAST_UNIX_MS:
            random_bits = secrets.randbits(_RANDOM_BITS)
        else:
            unix_ms = _LAST_UNIX_MS
            random_bits = _LAST_RANDOM + 1
            if random_bits > _RANDOM_MASK:
                unix_ms += 1
                random_bits = secrets.randbits(_RANDOM_BITS)

        _LAST_UNIX_MS = unix_ms
        _LAST_RANDOM = random_bits

    rand_a = random_bits >> 62
    rand_b = random_bits & ((1 << 62) - 1)
    value = (
        ((unix_ms & ((1 << 48) - 1)) << 80)
        | (0x7 << 76)
        | (rand_a << 64)
        | (0b10 << 62)
        | rand_b
    )
    return uuid.UUID(int=value)


def encode_id(value: uuid.UUID | str) -> str:
    """Encode an identifier in canonical UUID text form."""

    return str(parse_id(value))


def parse_id(value: uuid.UUID | str) -> uuid.UUID:
    """Parse a UUID object or canonical textual UUID."""

    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
