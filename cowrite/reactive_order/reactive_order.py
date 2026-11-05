# -*- coding: utf-8 -*-
"""先承重再建议的顺序探针（脚手架）。

一条 JSONL 是一次顺序检查：人的承重草稿先在，建议门后开。
不是知音结论，也不是作者判决。不关 E05b／E7，不开新臂。
span 只收 sha256；不写正文。

校验不依赖 jsonschema（requirements.txt 未列该包），按同目录
order_event.schema.json 做手检。门的规则在 gate()：
load_bearing_present 为 false 时必须 block，为 true 时必须 allow。
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
SCHEMA_PATH = HERE / "order_event.schema.json"
SMOKE_LOG = HERE / "runs" / "smoke.jsonl"

PHASES = (
    "await_load_bearing",
    "load_bearing_ready",
    "suggest_allowed",
    "suggest_blocked",
)
GATE_RESULTS = ("allow", "block")
REASON_CODES = ("missing_load_bearing", "ok_after_human_draft")

# phase -> (load_bearing_present, suggestion_attempted)
PHASE_SHAPE = {
    "await_load_bearing": (False, False),
    "load_bearing_ready": (True, False),
    "suggest_blocked": (False, True),
    "suggest_allowed": (True, True),
}


class OrderEventError(ValueError):
    """Event does not match order_event.schema.json, or breaks the gate."""


def sha256_text(text: str) -> str:
    """Hash a span before logging. The log stores this hex, not the text."""
    if not isinstance(text, str):
        raise OrderEventError("sha256_text expects a str")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def gate(load_bearing_present: bool) -> str:
    """Allow a suggestion only after a human load-bearing draft is present.

    False must block. True must allow. An order rule, not a score.
    """
    if type(load_bearing_present) is not bool:
        raise OrderEventError("gate expects a bool")
    if load_bearing_present:
        return "allow"
    return "block"


def reason_code_for(load_bearing_present: bool) -> str:
    """Reason code paired with gate(). Not a free-text verdict."""
    if gate(load_bearing_present) == "block":
        return "missing_load_bearing"
    return "ok_after_human_draft"


def _load_schema() -> dict:
    try:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        raise OrderEventError(f"cannot read schema: {SCHEMA_PATH}") from exc


def _fail(path: str, message: str) -> None:
    where = path if path != "$" else "event"
    raise OrderEventError(f"{where}: {message}")


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


def _enum(spec: dict, name: str) -> list:
    return list(((spec.get("properties") or {}).get(name) or {}).get("enum") or [])


def _check_order(event: dict) -> None:
    present = event["load_bearing_present"]
    attempted = event["suggestion_attempted"]
    phase = event["phase"]
    want_present, want_attempted = PHASE_SHAPE[phase]
    if present is not want_present or attempted is not want_attempted:
        _fail("phase", "must match load_bearing_present and suggestion_attempted")
    expected = gate(present)
    if event["gate_result"] != expected:
        shown = "true" if present else "false"
        _fail("gate_result", f"must be {expected} when load_bearing_present is {shown}")
    expected_reason = reason_code_for(present)
    if event["reason_code"] != expected_reason:
        shown = "true" if present else "false"
        _fail(
            "reason_code",
            f"must be {expected_reason} when load_bearing_present is {shown}",
        )


def validate_event(event: dict, schema: dict | None = None) -> dict:
    """Raise OrderEventError when event does not match the schema or the gate."""
    spec = schema if schema is not None else _load_schema()
    if spec.get("type") != "object":
        raise OrderEventError("schema root must be an object")
    if _enum(spec, "phase") != list(PHASES):
        raise OrderEventError("schema phase enum drifted from the scaffold")
    if _enum(spec, "gate_result") != list(GATE_RESULTS):
        raise OrderEventError("schema gate_result enum drifted from the scaffold")
    if _enum(spec, "reason_code") != list(REASON_CODES):
        raise OrderEventError("schema reason_code enum drifted from the scaffold")
    _check(event, spec, "$")
    _check_order(event)
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


def _smoke_event(phase: str) -> dict:
    present, attempted = PHASE_SHAPE[phase]
    before = sha256_text(f"smoke-before-{phase}-not-corpus")
    after = sha256_text(f"smoke-after-{phase}-not-corpus") if present else ""
    return {
        "event_id": f"smoke-{phase}",
        "ts_iso": "2026-11-05T00:00:00+00:00",
        "session_id": "smoke-session",
        "phase": phase,
        "load_bearing_present": present,
        "suggestion_attempted": attempted,
        "gate_result": gate(present),
        "reason_code": reason_code_for(present),
        "span": {
            "before_sha256": before,
            "after_sha256": after,
        },
        "notes": "scaffold smoke; not an author verdict",
    }


def _expect_reject(event: dict) -> None:
    try:
        validate_event(event)
    except OrderEventError:
        return
    raise OrderEventError("validator accepted a bad event")


def smoke(log_path: Path | None = None) -> Path:
    """Write one fake blocked attempt, then one fake allowed attempt."""
    path = Path(log_path) if log_path is not None else SMOKE_LOG
    blocked = _smoke_event("suggest_blocked")
    allowed = _smoke_event("suggest_allowed")
    validate_event(_smoke_event("await_load_bearing"))
    validate_event(_smoke_event("load_bearing_ready"))
    if path.exists():
        path.unlink()
    append_event(blocked, path)
    append_event(allowed, path)
    try:
        gate("no")
    except OrderEventError:
        pass
    else:
        raise OrderEventError("gate accepted a non-bool")

    broken = dict(allowed)
    broken.pop("session_id")
    _expect_reject(broken)
    _expect_reject({**allowed, "phase": "approve"})
    _expect_reject({**allowed, "span": {"text": "private corpus"}})
    _expect_reject({**allowed, "load_bearing_present": "yes"})
    _expect_reject({**allowed, "ts_iso": "yesterday"})
    _expect_reject({**allowed, "notes": "x" * 281})
    _expect_reject(
        {
            **blocked,
            "gate_result": "allow",
        }
    )
    _expect_reject(
        {
            **allowed,
            "gate_result": "block",
        }
    )
    _expect_reject(
        {
            **allowed,
            "reason_code": "missing_load_bearing",
        }
    )
    _expect_reject(
        {
            **allowed,
            "phase": "suggest_blocked",
        }
    )
    _expect_reject(
        {
            **blocked,
            "span": {"before_sha256": "not-a-hash", "after_sha256": ""},
        }
    )

    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if [row.get("phase") for row in rows] != ["suggest_blocked", "suggest_allowed"]:
        raise OrderEventError("smoke log is not one blocked attempt then one allowed")
    if rows[0].get("load_bearing_present") is not False or rows[0].get("gate_result") != "block":
        raise OrderEventError("blocked smoke must keep the gate shut")
    if rows[0].get("reason_code") != "missing_load_bearing":
        raise OrderEventError("blocked smoke must record missing_load_bearing")
    if rows[0].get("suggestion_attempted") is not True:
        raise OrderEventError("blocked smoke must be an attempted suggestion")
    if rows[1].get("load_bearing_present") is not True or rows[1].get("gate_result") != "allow":
        raise OrderEventError("allowed smoke must open the gate after the draft")
    if rows[1].get("reason_code") != "ok_after_human_draft":
        raise OrderEventError("allowed smoke must record ok_after_human_draft")
    if gate(False) != "block" or gate(True) != "allow":
        raise OrderEventError("gate() drifted from block-then-allow")
    blob = path.read_text(encoding="utf-8")
    if "not-corpus" in blob or "private" in blob:
        raise OrderEventError("smoke log leaked span text")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Order probe: block suggestions until a human load-bearing draft exists. Smoke only; no scoring."
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="write one fake blocked attempt and one fake allowed attempt, then print OK",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="JSONL path for --smoke (default: cowrite/reactive_order/runs/smoke.jsonl)",
    )
    args = parser.parse_args(argv)
    if not args.smoke:
        parser.error("this scaffold only runs --smoke; it does not score or close arms")
    try:
        smoke(args.log)
    except OrderEventError as exc:
        print(f"smoke failed: {exc}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
