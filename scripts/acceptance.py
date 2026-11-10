"""Create and check a human-reviewed LibreChat acceptance record. No network access."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / "docs" / "banco-de-preguntas.md"
REQUIRED_CONFIG = ("librechat_url", "librechat_version", "model", "provider", "model_settings", "dataset", "reviewer")
STATUSES = {"pending", "passed", "failed", "blocked"}


def bank_cases():
    cases = []
    for line in BANK.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not line.startswith("|") or not cells[0].isdigit():
            continue
        cases.append({"id": int(cells[0]), "scenario": cells[1], "expected_behavior": cells[2],
                      "prompt": cells[1], "verified_expected": "", "observed": "",
                      "tool_calls": [], "evidence": "", "executed_at": "", "status": "pending"})
    if [case["id"] for case in cases] != list(range(1, 31)):
        raise ValueError("Expected exactly the 30 acceptance scenarios, in order")
    return cases


def new_record(config):
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    return {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "config": {**config, "mcp_revision": revision, "working_tree_dirty": dirty,
                       "bank_sha256": hashlib.sha256(BANK.read_bytes()).hexdigest()},
            "cases": bank_cases()}


def check_record(record, require_pass=False):
    """Check completeness, not semantic correctness; the reviewer judges the answers."""
    errors = []
    if record.get("schema_version") != 1:
        errors.append("Unsupported schema_version")
    config = record.get("config", {})
    if not isinstance(config, dict):
        return errors + ["config must be an object"]
    for key in (*REQUIRED_CONFIG, "mcp_revision", "bank_sha256"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            errors.append(f"Missing config.{key}")
    for key in ("created_at",):
        try:
            timestamp = datetime.fromisoformat(record.get(key, ""))
            if timestamp.tzinfo is None:
                raise ValueError("Missing timezone")
        except (TypeError, ValueError):
            errors.append(f"Invalid {key}: use an ISO timestamp with timezone")
    cases = record.get("cases", [])
    if not isinstance(cases, list) or not all(isinstance(case, dict) for case in cases):
        return errors + ["cases must be a list of objects"]
    if [case.get("id") for case in cases] != list(range(1, 31)):
        errors.append("Expected IDs 1..30, in order and without duplicates")
    for case in cases:
        prefix = f"Case {case.get('id')}"
        status = case.get("status")
        if not isinstance(status, str) or status not in STATUSES:
            errors.append(f"{prefix}: invalid status")
        for key in ("scenario", "expected_behavior", "prompt"):
            if not isinstance(case.get(key), str) or not case[key].strip():
                errors.append(f"{prefix}: missing {key}")
        if isinstance(status, str) and status in {"passed", "failed", "blocked"}:
            for key in ("verified_expected", "observed", "evidence"):
                if not isinstance(case.get(key), str) or not case[key].strip():
                    errors.append(f"{prefix}: missing {key}")
            try:
                timestamp = datetime.fromisoformat(case.get("executed_at", ""))
                if timestamp.tzinfo is None:
                    raise ValueError("Missing timezone")
            except (TypeError, ValueError):
                errors.append(f"{prefix}: executed_at needs an ISO timestamp with timezone")
        calls = case.get("tool_calls")
        if not isinstance(calls, list) or not all(isinstance(call, dict) and isinstance(call.get("name"), str)
                                                 and isinstance(call.get("arguments"), dict) for call in calls):
            errors.append(f"{prefix}: tool_calls must contain name and arguments objects")
        if require_pass and status != "passed":
            errors.append(f"{prefix}: not passed ({status})")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Create a pending record; never overwrites an existing file")
    for key in REQUIRED_CONFIG:
        init.add_argument("--" + key.replace("_", "-"), required=True)
    init.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("check", help="Validate recorded evidence, optionally require 30 passes")
    check.add_argument("record", type=Path)
    check.add_argument("--require-pass", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "init":
        record = new_record({key: getattr(args, key) for key in REQUIRED_CONFIG})
        errors = check_record(record)
        if errors:
            parser.exit(1, "\n".join(errors) + "\n")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as target:
            json.dump(record, target, ensure_ascii=False, indent=2)
            target.write("\n")
        print(f"Created {args.output}: 30 pending scenarios (no model execution)")
        return
    try:
        record = json.loads(args.record.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError("Record must be an object")
        errors = check_record(record, args.require_pass)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Invalid record: {exc}\n")
    if errors:
        parser.exit(1, "\n".join(errors) + "\n")
    counts = {status: sum(case["status"] == status for case in record["cases"]) for status in sorted(STATUSES)}
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
