#!/usr/bin/env python3
"""Merge Memvara's hooks into Cursor's hook configuration.

    python3 bin/install.py                 # ~/.cursor/hooks.json
    python3 bin/install.py --config PATH   # somewhere else
    python3 bin/install.py --remove        # take them out again

Cursor reads hooks from a config file, not from a plugin manifest: a manifest `hooks` key
was measured on cursor-agent 2026.08.25 and did not fire, while both `~/.cursor/hooks.json`
and `<project>/.cursor/hooks.json` did. So installing the plugin gives you the MCP endpoint
and the skill; this script is what makes memory automatic.

Only the entries this plugin owns are added or removed. Anything else in the file is left
exactly as it was, because it is the user's file and Cursor's own features live in it.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

#: Canonical hook -> the Cursor event that carries it. `recall` is deliberately absent:
#: `beforeSubmitPrompt` never fires on this client, so there is no per-prompt recall to
#: install. See `plugin/hooks/hosts/cursor.py`.
EVENTS = {
    "session_start": "sessionStart",
    "capture": "sessionEnd",
    "approve": "preToolUse",
}

#: How an entry of ours is recognised on the way back out. Matching on the command text
#: rather than on the event name is what lets `--remove` leave a user's own hook on the
#: same event alone.
MARKER = "hooks/run.py"


def _entries(root: pathlib.Path) -> "dict[str, list]":
    run = root / "plugin" / "hooks" / "run.py"
    if not run.is_file():
        raise SystemExit(f"refusing to write: no hook entry point at {run}")
    return {event: [{"command": f'python3 "{run}" {hook} --host cursor'}]
            for hook, event in EVENTS.items()}


def main(argv: "list[str]") -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args(argv)

    config = pathlib.Path(args.config) if args.config else (
        pathlib.Path.home() / ".cursor" / "hooks.json")
    body: dict = {}
    if config.exists():
        try:
            body = json.loads(config.read_text(encoding="utf-8"))
        except ValueError as exc:
            # Refuse rather than overwrite. This is the user's file and Cursor's own
            # features live in it; a parse failure is a reason to stop, not to start again
            # from an empty object.
            raise SystemExit(f"refusing to write: {config} is not valid JSON ({exc})")
    if not isinstance(body, dict):
        raise SystemExit(f"refusing to write: {config} is not a JSON object")

    body.setdefault("version", 1)
    hooks = body.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SystemExit(f'refusing to write: "hooks" in {config} is not an object')

    root = pathlib.Path(__file__).resolve().parent.parent
    ours = {} if args.remove else _entries(root)

    for event in set(EVENTS.values()) | set(hooks):
        existing = hooks.get(event)
        if not isinstance(existing, list):
            existing = []
        # Drop only our own entries, so re-running replaces rather than appends and
        # --remove cannot take somebody else's hook with it.
        kept = [e for e in existing
                if not (isinstance(e, dict) and MARKER in str(e.get("command", "")))]
        merged = kept + ours.get(event, [])
        if merged:
            hooks[event] = merged
        else:
            hooks.pop(event, None)

    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(
        f"{'removed' if args.remove else 'wrote'} memvara hooks -> {config}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
