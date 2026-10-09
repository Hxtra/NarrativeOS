"""Provider-agnostic access to a reasoning model for the Director.

NarrativeOS does not depend on any particular model. The Director runs
deterministically by default. A reasoning model (for example Claude) can be
attached through this interface to *propose* extra editorial events; every
proposal is validated exactly like rule-based output, and invalid proposals
are rejected with reasons. Nothing here names or assumes a vendor.

Provider config:
  {"type": "command", "name": "...", "model": "...", "command": ["...", "{input_file}", "{output_file}"], "timeout_sec": 120}
      Runs an external program: it reads the task JSON from {input_file} and writes a JSON reply to {output_file}.
  {"type": "callable", "name": "...", "model": "...", "callable": fn(task, context) -> dict}
      In-process integration (e.g. an SDK wrapper); also used by tests.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

TASKS = {"propose_edit_events", "propose_edit_patch"}


def load_reasoning_provider(config: dict) -> tuple[dict, Callable[[str, dict], dict]]:
    """Returns (identity, call). identity = {"name", "model", "type"} for provenance on every proposal."""
    if not isinstance(config, dict):
        raise ValueError("reasoning provider config must be an object")
    for key in ("type", "name", "model"):
        if not isinstance(config.get(key), str) or not config[key]:
            raise ValueError(f"reasoning provider config needs a non-empty '{key}'")
    identity = {"type": config["type"], "name": config["name"], "model": config["model"]}
    if config["type"] == "callable":
        fn = config.get("callable")
        if not callable(fn):
            raise ValueError("callable provider needs a 'callable'")
        return identity, _checked(fn)
    if config["type"] == "command":
        command = config.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(c, str) for c in command):
            raise ValueError("command provider needs 'command' as a list of strings")
        return identity, _checked(_command_call(command, config.get("timeout_sec", 120)))
    raise ValueError(f"unknown reasoning provider type {config['type']!r} (supported: command, callable)")


def _checked(fn: Callable[[str, dict], dict]) -> Callable[[str, dict], dict]:
    def call(task: str, context: dict) -> dict:
        if task not in TASKS:
            raise ValueError(f"unknown reasoning task {task!r}")
        reply = fn(task, context)
        key = "operations" if task == "propose_edit_patch" else "events"
        if not isinstance(reply, dict) or not isinstance(reply.get(key, []), list):
            raise ValueError(f"reasoning provider must reply with an object containing an '{key}' list")
        return reply
    return call


def _command_call(command: list[str], timeout: float) -> Callable[[str, dict], dict]:
    def call(task: str, context: dict) -> dict:
        with tempfile.TemporaryDirectory() as td:
            inp, out = Path(td) / "task.json", Path(td) / "reply.json"
            inp.write_text(json.dumps({"task": task, "context": context}, allow_nan=False), encoding="utf-8")
            subprocess.run([c.format(input_file=inp, output_file=out) for c in command], check=True, capture_output=True, timeout=timeout)
            if not out.is_file():
                raise ValueError("reasoning provider wrote no reply")
            return json.loads(out.read_text(encoding="utf-8"))
    return call
