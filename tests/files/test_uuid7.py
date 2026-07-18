import uuid
from concurrent.futures import ThreadPoolExecutor

from app.shared.ids import encode_id, generate_id, parse_id


def test_uuid7_version_variant_and_round_trip():
    value = generate_id()
    assert value.version == 7
    assert value.variant == uuid.RFC_4122
    assert parse_id(encode_id(value)) == value


def test_uuid7_is_unique_and_process_monotonic_across_threads():
    def generate_batch(_):
        return [generate_id() for _ in range(100)]

    with ThreadPoolExecutor(max_workers=8) as pool:
        batches = list(pool.map(generate_batch, range(8)))

    values = [value for batch in batches for value in batch]
    assert len(set(values)) == 800
    for batch in batches:
        assert batch == sorted(batch)
