#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Copy shared/*.json into each platform's resource directory.

The MSIX package and the .deb must be self-contained (they cannot reference a
path outside their own source tree), so the shared data contract is duplicated
at build time.  shared/ remains the single source of truth.

    python tools/gen_elements.py && python tools/sync_data.py
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared"
FILES = ["elements.json", "theme.json", "intervals.json", "config.schema.json"]

TARGETS = [
    ROOT / "windows" / "src" / "ElementBlocks.Desktop" / "Assets" / "Data",
    ROOT / "linux" / "data",
    ROOT / "preview" / "data",
]

for target in TARGETS:
    target.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        shutil.copy2(SHARED / name, target / name)
    print(f"synced -> {target.relative_to(ROOT)}")
