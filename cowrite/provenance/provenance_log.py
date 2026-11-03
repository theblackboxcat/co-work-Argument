# -*- coding: utf-8 -*-
"""决策点 provenance 写入器（脚手架）。

一条 JSONL 是一次明示的接受／拒绝，不是知音结论，也不是作者判决。
对齐 Who Owns the Text 模式 5。不关 E05b／E7，不开新臂。
span 只收偏移和 sha256；不写正文。

校验不依赖 jsonschema（requirements.txt 未列该包），按同目录
decision_event.schema.json 做手检。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "decision_event.schema.json"
SMOKE_LOG = HERE / "runs" / "smoke.jsonl"

ACTIONS = ("accept", "reject", "edit_then_accept", "dismiss")


class DecisionEventError(ValueError):
    """Event does not match decision_event.schema.json."""


def sha256_text(text: str) -> str:
    """Hash a span before logging. The log stores this hex, not the text."""
    if not isinstance(text, str):
        raise DecisionEventError("sha256_text expects a str")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_schema() -> dict:
    try:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DecisionEventError(f"cannot read schema: {SCHEMA_PATH}") from exc


def _fail(path: str, message: str) -> None:
    where = path if path != "$" else "event"
    raise DecisionEventError(f"{where}: {message}")


def _check_iso8601(value: str, path: str) -> None:
    raw = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        datetime.fromisoformat(raw)
    except ValueError:
        _fail(path, "must be ISO-8601")


def _check(value, spec: dict, path: str) -> None:
    typ = spec.get("type")
    if typ == "string":
        if not isinstance(value, str):
            _fail(path, "must be a string")
        if "\n" in value or "\r" in value:
            _fail(path, "must be a single line")
        min_len = spec.get("minLength", 0)
        if len(value) < min_len:
            _fail(path, f"must be at least {min_len} characters")
        max_len = spec.get("maxLength")
        if max_len is not None and len(value) > max_len:
            _fail(path, f"must be at most {max_len} characters")
        pattern = spec.get("pattern")
        if pattern is not None and re.search(pattern, value) is None:
            _fail(path, "does not match pattern")
        if spec.get("format") == "date-time":
            _check_iso8601(value, path)
        enum = spec.get("enum")
        if enum is not None and value not in enum:
            _fail(path, f"must be one of {list(enum)}")
        return
    if typ == "boolean":
        if type(value) is not bool:
            _fail(path, "must be a boolean")
        return
    if typ == "integer":
        if type(value) is not int:
            _fail(path, "must be an integer")
        minimum = spec.get("minimum")
        if minimum is not None and value < minimum:
            _fail(path, f"must be >= {minimum}")
        return
    if typ == "object":
        _check_object(value, spec, path)
        return
    _fail(path, f"unsupported schema type {typ!r}")


def _check_object(value, spec: dict, path: str) -> None:
    if not isinstance(value, dict):
        _fail(path, "must be an object")
    props = spec.get("properties") or {}
    if spec.get("additionalProperties") is False:
        extra = sorted(set(value) - set(props))
        if extra:
            _fail(path, f"unknown fields {extra}")
    for key in spec.get("required") or []:
        if key not in value:
            child = key if path == "$" else f"{path}.{key}"
            _fail(child, "missing required field")
    for key, item in value.items():
        if key not in props:
            continue
        child = key if path == "$" else f"{path}.{key}"
        _check(item, props[key], child)
    if path == "span" or path.endswith(".span"):
        start = value.get("start")
        end = value.get("end")
        if start is not None and end is not None and end < start:
            _fail(path, "end must be >= start")


def validate_event(event: dict, schema: dict | None = None) -> dict:
    """Raise DecisionEventError when event does not match the schema."""
    spec = schema if schema is not None else _load_schema()
    if spec.get("type") != "object":
        raise DecisionEventError("schema root must be an object")
    enum = ((spec.get("properties") or {}).get("action") or {}).get("enum")
    if list(enum or []) != list(ACTIONS):
        raise DecisionEventError("schema action enum drifted from the scaffold")
    _check(event, spec, "$")
    return event


def append_event(event: dict, path: Path | None = None) -> Path:
    """Validate, then append one JSON object as a single JSONL line."""
    validate_event(event)
    target = Path(path) if path is not None else SMOKE_LOG
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with target.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return target


def _smoke_event(action: str, load_bearing: bool) -> dict:
    before = sha256_text(f"smoke-before-{action}-not-corpus")
    after = sha256_text(f"smoke-after-{action}-not-corpus") if action == "accept" else ""
    return {
        "event_id": f"smoke-{action}",
        "ts_iso": "2026-11-03T00:00:00+00:00",
        "session_id": "smoke-session",
        "suggestion_id": f"smoke-suggestion-{action}",
        "action": action,
        "source": "scaffold:pattern5",
        "span": {
            "before_sha256": before,
            "after_sha256": after,
            "start": 0,
            "end": 12 if action == "accept" else 0,
        },
        "load_bearing_flag": load_bearing,
        "notes": "scaffold smoke; not an author verdict",
    }


def _expect_reject(event: dict) -> None:
    try:
        validate_event(event)
    except DecisionEventError:
        return
    raise DecisionEventError("validator accepted a bad event")


def smoke(log_path: Path | None = None) -> Path:
    """Write one fake accept and one fake reject. Replace the smoke file."""
    path = Path(log_path) if log_path is not None else SMOKE_LOG
    accept = _smoke_event("accept", True)
    reject = _smoke_event("reject", False)
    if path.exists():
        path.unlink()
    append_event(accept, path)
    append_event(reject, path)

    broken = dict(accept)
    broken.pop("source")
    _expect_reject(broken)
    _expect_reject({**accept, "action": "approve"})
    _expect_reject({**accept, "span": {"text": "private corpus"}})
    _expect_reject({**accept, "load_bearing_flag": "yes"})
    _expect_reject({**accept, "ts_iso": "yesterday"})
    _expect_reject({**reject, "span": {"start": 4, "end": 1, "before_sha256": "", "after_sha256": ""}})

    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if [row.get("action") for row in rows] != ["accept", "reject"]:
        raise DecisionEventError("smoke log is not one accept then one reject")
    if rows[0].get("load_bearing_flag") is not True:
        raise DecisionEventError("accept smoke must keep load_bearing_flag true")
    if rows[1].get("load_bearing_flag") is not False:
        raise DecisionEventError("reject smoke must keep load_bearing_flag false")
    blob = path.read_text(encoding="utf-8")
    if "not-corpus" in blob or "private" in blob:
        raise DecisionEventError("smoke log leaked span text")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Append-only accept/reject provenance scaffold. Smoke only; no scoring."
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="write one fake accept and one fake reject, then print OK",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="JSONL path for --smoke (default: cowrite/provenance/runs/smoke.jsonl)",
    )
    args = parser.parse_args(argv)
    if not args.smoke:
        parser.error("this scaffold only runs --smoke; it does not score or close arms")
    try:
        smoke(args.log)
    except DecisionEventError as exc:
        print(f"smoke failed: {exc}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
