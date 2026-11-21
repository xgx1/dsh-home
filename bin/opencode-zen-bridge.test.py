#!/usr/bin/env python3
"""Assert-based self-check for the bridge's gate shaping and tool-name mapping."""
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("bridge", Path(__file__).resolve().parent / "opencode-zen-bridge.py")
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


def tool(name):
    return {"type": "function", "function": {"name": name, "description": name, "parameters": {"type": "object", "properties": {}}}}


def gate(doc):
    return b.gated(json.dumps(doc).encode(), doc)


# run_code alone -> renamed to bash, map back, read injected
doc = {"model": "big-pickle", "messages": [{"role": "user", "content": "hi"}], "tools": [tool("run_code")]}
raw, rename = gate(doc)
sent = json.loads(raw)
assert rename == {"bash": "run_code"}, rename
assert [t["function"]["name"] for t in sent["tools"]] == ["bash", "read"], sent["tools"]
assert sent["messages"][0]["role"] == "system" and sent["messages"][0]["content"].startswith(b.SYSTEM_PROMPT)

# run_code + real bash -> no rename (collision avoided)
doc = {"model": "big-pickle", "messages": [{"role": "user", "content": "hi"}], "tools": [tool("run_code"), tool("bash")]}
raw, rename = gate(doc)
assert rename == {}, rename
assert [t["function"]["name"] for t in json.loads(raw)["tools"]] == ["run_code", "bash", "read"]

# no run_code -> no rename; existing read kept (not duplicated)
doc = {"model": "big-pickle", "messages": [{"role": "user", "content": "hi"}], "tools": [tool("read")]}
raw, rename = gate(doc)
assert rename == {} and [t["function"]["name"] for t in json.loads(raw)["tools"]] == ["read"]

# system prompt prepended once, not doubled
doc = {"model": "big-pickle", "messages": [{"role": "system", "content": b.SYSTEM_PROMPT + "\n\nextra"}, {"role": "user", "content": "hi"}]}
raw, _ = gate(doc)
assert json.loads(raw)["messages"][0]["content"] == b.SYSTEM_PROMPT + "\n\nextra"

# non-object body forwarded untouched
assert b.gated(b"not json", None) == (b"not json", {})

# SSE tool-call name mapped back (streaming delta + non-streaming message)
line = b'data: ' + json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "bash", "arguments": "{\"code\"}"}}]}}]}).encode()
out = json.loads(b.rename_tool_calls(line, {"bash": "run_code"})[5:])
assert out["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "run_code"
line2 = b'data: ' + json.dumps({"choices": [{"message": {"tool_calls": [{"function": {"name": "bash"}}]}}]}).encode()
assert json.loads(b.rename_tool_calls(line2, {"bash": "run_code"})[5:])["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "run_code"
# untouched: [DONE], non-data, empty rename, arguments-only chunk
assert b.rename_tool_calls(b"data: [DONE]", {"bash": "run_code"}) == b"data: [DONE]"
assert b.rename_tool_calls(b": ping", {"bash": "run_code"}) == b": ping"
assert b.rename_tool_calls(line, {}) == line
argline = b'data: ' + json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "more"}}]}}]}).encode()
assert b.rename_tool_calls(argline, {"bash": "run_code"}) == argline

print("PASS: run_code rename, collision avoidance, read injection, prompt prepend, SSE name mapping")
