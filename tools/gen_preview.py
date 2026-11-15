#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the self-contained interactive preview (no server / no fetch).

Reads preview/template.html, injects the shared JSON contract inline, writes
preview/index.html.  Re-run after tools/gen_elements.py:

    python tools/gen_elements.py
    python tools/sync_data.py
    python tools/gen_preview.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared"
PREVIEW = ROOT / "preview"

template = (PREVIEW / "template.html").read_text(encoding="utf-8")

payload = {
    "__ELEMENTS_JSON__": (SHARED / "elements.json").read_text(encoding="utf-8"),
    "__THEME_JSON__": (SHARED / "theme.json").read_text(encoding="utf-8"),
    "__INTERVALS_JSON__": (SHARED / "intervals.json").read_text(encoding="utf-8"),
}

for token, text in payload.items():
    if token not in template:
        raise RuntimeError(f"模板缺少占位符 {token}")
    # 避免 JSON 里出现 </script> 提前结束脚本块（本项目数据不含，保险起见）
    text = text.replace("</", "<\\/")
    template = template.replace(token, text.strip())

out = PREVIEW / "index.html"
out.write_text(template, encoding="utf-8")
print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size} bytes)")
