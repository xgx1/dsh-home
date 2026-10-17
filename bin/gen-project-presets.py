#!/usr/bin/env python3
"""生成类型预设：base 取 ~/.dsh/preset-base.yml，按清单追加该类型要的 MCP。

输入：
  ~/.dsh/preset-base.yml     共享基础树（原 omni 的 plugins 列表）
  ~/.dsh/type-presets.yaml   类型清单（mcps + types + disable_host）
输出：
  ~/.dsh/profiles/web/cordis.patch.yml 的 generated 区块

用法：
  gen-project-presets.py            # 重写区块
  gen-project-presets.py --check    # 只报告将生成什么
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

HOME = Path.home()
BASE = HOME / ".dsh/preset-base.yml"
PATCH = HOME / ".dsh/profiles/web/cordis.patch.yml"
MANIFEST = HOME / ".dsh/type-presets.yaml"

BEGIN = "# <<< BEGIN generated type presets — 改 ~/.dsh/type-presets.yaml 或 ~/.dsh/preset-base.yml 后跑 ~/.dsh/bin/gen-project-presets.py >>>"
END = "# <<< END generated type presets >>>"


def base_rows() -> list[str]:
    rows = [ln for ln in BASE.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not rows:
        raise SystemExit(f"{BASE}: 基础树为空")
    return rows


def dump_mcp(key: str, config: dict) -> list[str]:
    body = yaml.safe_dump(config, sort_keys=False, allow_unicode=True, default_flow_style=False)
    out = [f"          - id: mcp-{key}", "            name: '@deepseek-ai/dsh-mcp-client'", "            config:"]
    out += ["              " + ln for ln in body.rstrip().splitlines()]
    return out


def dump_plugin(key: str, spec: dict) -> list[str]:
    out = [f"          - id: {key}", f"            name: '{spec['name']}'"]
    config = spec.get("config") or {}
    if config:
        body = yaml.safe_dump(config, sort_keys=False, allow_unicode=True, default_flow_style=False)
        out.append("            config:")
        out += ["              " + ln for ln in body.rstrip().splitlines()]
    return out


def render(manifest: dict) -> str:
    rows = base_rows()
    mcps = manifest.get("mcps", {})
    plugins = manifest.get("plugins", {})
    out: list[str] = [BEGIN]

    for entry in manifest.get("disable_host", []) or []:
        out += [f"- id: {entry}", "  disabled: true"]

    for item in manifest.get("types") or []:
        keys = item.get("mcp") or []
        unknown = [k for k in keys if k not in mcps]
        if unknown:
            raise SystemExit(f"{item['id']}: 未定义的 mcp {unknown}")
        plugin_keys = item.get("plugins") or []
        unknown = [k for k in plugin_keys if k not in plugins]
        if unknown:
            raise SystemExit(f"{item['id']}: 未定义的 plugin {unknown}")
        out += [
            "- insert:",
            f"    - id: preset-{item['id']}",
            "      name: '@deepseek-ai/dsh-agent-preset'",
            "      config:",
            f"        id: {item['id']}",
            f"        name: {item['name']}",
            f"        order: {item.get('order', 50)}",
            "        plugins:",
        ]
        out += rows
        for key in keys:
            out += dump_mcp(key, mcps[key])
        for key in plugin_keys:
            out += dump_plugin(key, plugins[key])

    out.append(END)
    return "\n".join(out) + "\n"


def main() -> None:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    region = render(manifest)
    types = manifest.get("types") or []

    if "--check" in sys.argv:
        print(f"types={len(types)} base_rows={len(base_rows())} mcps={list(manifest.get('mcps', {}))}")
        for p in types:
            print(f"  preset-{p['id']:<16} order={p.get('order', 50):<3} mcp={p.get('mcp') or []}")
        print(f"region_lines={len(region.splitlines())}")
        return

    text = PATCH.read_text(encoding="utf-8")
    if BEGIN in text and END in text:
        rest = text[text.index(END) + len(END):]
        new = text[: text.index(BEGIN)] + region + ("\n" + rest.lstrip("\n") if rest.strip() else "")
    elif "# <<< BEGIN generated" in text and "# <<< END generated" in text:
        b = text.index("# <<< BEGIN generated")
        e = text.index("# <<< END generated")
        new = text[:b] + region + text[text.index("\n", e) + 1:]
    else:
        new = text.rstrip("\n") + "\n\n" + region
    PATCH.write_text(new, encoding="utf-8")
    print(f"wrote {PATCH} ({len(new.splitlines())} lines, {len(types)} type presets)")


if __name__ == "__main__":
    main()
