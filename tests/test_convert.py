import json
from pathlib import Path

from observer.convert import iter_jsonl_lines


def test_iter_jsonl_skips_truncated_last_line(tmp_path: Path) -> None:
    p = tmp_path / "test.jsonl"
    # Two complete lines + one truncated (no trailing newline, partial JSON)
    p.write_bytes(b'{"a":1}\n{"a":2}\n{"a":3')
    rows = list(iter_jsonl_lines(p))
    assert rows == [{"a": 1}, {"a": 2}]


def test_iter_jsonl_handles_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.jsonl"
    p.write_bytes(b"")
    rows = list(iter_jsonl_lines(p))
    assert rows == []


def test_iter_jsonl_skips_unparseable_lines(tmp_path: Path) -> None:
    p = tmp_path / "test.jsonl"
    p.write_bytes(b'{"a":1}\nnot-json\n{"a":2}\n')
    rows = list(iter_jsonl_lines(p))
    assert rows == [{"a": 1}, {"a": 2}]
