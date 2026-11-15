#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the shared data contract for Element Blocks Desktop.

Single source of truth lives in this script.  It writes:
  shared/elements.json   - 118 elements + periodic-table grid coordinates
  shared/theme.json      - colour tokens shared by WinUI3 / GTK / preview
  shared/config.schema.json - JSON Schema for config.json
  shared/intervals.json  - rotation interval definitions

Re-run after editing any table below:
    python tools/gen_elements.py
    python tools/sync_data.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared"
SHARED.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# 1. Element master table
#    (symbol, English, Chinese, mass text, pinyin fallback for rare CJK chars)
# ---------------------------------------------------------------------------
RAW = """
H   Hydrogen       氢       1.008
He  Helium         氦       4.003
Li  Lithium        锂       6.941
Be  Beryllium      铍       9.012
B   Boron          硼       10.81
C   Carbon         碳       12.01
N   Nitrogen       氮       14.01
O   Oxygen         氧       16.00
F   Fluorine       氟       19.00
Ne  Neon           氖       20.18
Na  Sodium         钠       22.99
Mg  Magnesium      镁       24.31
Al  Aluminium      铝       26.98
Si  Silicon        硅       28.09
P   Phosphorus     磷       30.97
S   Sulfur         硫       32.06
Cl  Chlorine       氯       35.45
Ar  Argon          氩       39.95
K   Potassium      钾       39.10
Ca  Calcium        钙       40.08
Sc  Scandium       钪       44.96
Ti  Titanium       钛       47.87
V   Vanadium       钒       50.94
Cr  Chromium       铬       52.00
Mn  Manganese      锰       54.94
Fe  Iron           铁       55.85
Co  Cobalt         钴       58.93
Ni  Nickel         镍       58.69
Cu  Copper         铜       63.55
Zn  Zinc           锌       65.39
Ga  Gallium        镓       69.72
Ge  Germanium      锗       72.61
As  Arsenic        砷       74.92
Se  Selenium       硒       78.96
Br  Bromine        溴       79.90
Kr  Krypton        氪       83.80
Rb  Rubidium       铷       85.47
Sr  Strontium      锶       87.62
Y   Yttrium        钇       88.91
Zr  Zirconium      锆       91.22
Nb  Niobium        铌       92.91
Mo  Molybdenum     钼       95.94
Tc  Technetium     锝       [98]
Ru  Ruthenium      钌       101.1
Rh  Rhodium        铑       102.9
Pd  Palladium      钯       106.4
Ag  Silver         银       107.9
Cd  Cadmium        镉       112.4
In  Indium         铟       114.8
Sn  Tin            锡       118.7
Sb  Antimony       锑       121.8
Te  Tellurium      碲       127.6
I   Iodine         碘       126.9
Xe  Xenon          氙       131.3
Cs  Caesium        铯       132.9
Ba  Barium         钡       137.3
La  Lanthanum      镧       138.9
Ce  Cerium         铈       140.1
Pr  Praseodymium   镨       140.9
Nd  Neodymium      钕       144.2
Pm  Promethium     钷       [145]
Sm  Samarium       钐       150.4
Eu  Europium       铕       152.0
Gd  Gadolinium     钆       157.3
Tb  Terbium        铽       158.9
Dy  Dysprosium     镝       162.5
Ho  Holmium        钬       164.9
Er  Erbium         铒       167.3
Tm  Thulium        铥       168.9
Yb  Ytterbium      镱       173.0
Lu  Lutetium       镥       175.0
Hf  Hafnium        铪       178.5
Ta  Tantalum       钽       180.9
W   Tungsten       钨       183.8
Re  Rhenium        铼       186.2
Os  Osmium         锇       190.2
Ir  Iridium        铱       192.2
Pt  Platinum       铂       195.1
Au  Gold           金       197.0
Hg  Mercury        汞       200.6
Tl  Thallium       铊       204.4
Pb  Lead           铅       207.2
Bi  Bismuth        铋       209.0
Po  Polonium       钋       [209]
At  Astatine       砹       [210]
Rn  Radon          氡       [222]
Fr  Francium       钫       [223]
Ra  Radium         镭       [226]
Ac  Actinium       锕       [227]
Th  Thorium        钍       232.0
Pa  Protactinium   镤       231.0
U   Uranium        铀       238.0
Np  Neptunium      镎       [237]
Pu  Plutonium      钚       [244]
Am  Americium      镅       [243]
Cm  Curium         锔       [247]
Bk  Berkelium      锫       [247]
Cf  Californium    锎       [251]
Es  Einsteinium    锿       [252]
Fm  Fermium        镄       [257]
Md  Mendelevium    钔       [258]
No  Nobelium       锘       [259]
Lr  Lawrencium     铹       [262]
Rf  Rutherfordium  𬬻   [267]   lu2
Db  Dubnium        𬭊   [268]   du4
Sg  Seaborgium     𬭳   [271]   xi3
Bh  Bohrium        𬭛   [270]   bo1
Hs  Hassium        𬭶   [277]   hei1
Mt  Meitnerium     鿏   [276]   mai4
Ds  Darmstadtium   𫟼   [281]   da2
Rg  Roentgenium    𬬭   [282]   lun2
Cn  Copernicium    鿔   [285]   ge1
Nh  Nihonium       鿭   [286]   ni3
Fl  Flerovium      𫓧   [289]   fu1
Mc  Moscovium      镆       [290]
Lv  Livermorium    𫟷   [293]   li4
Ts  Tennessine     鿬   [294]   tian2
Og  Oganesson      鿫   [294]   ao4
"""

# Rows that carry a 4th column: pinyin fallback for CJK Extension characters.
elements_raw: list[tuple[str, str, str, str, str | None]] = []
for line in RAW.strip().splitlines():
    parts = line.split()
    if len(parts) == 4:
        sym, en, zh, mass = parts
        pinyin = None
    else:
        sym, en, zh, mass, pinyin = parts
    elements_raw.append((sym, en, zh, mass, pinyin))

assert len(elements_raw) == 118, f"expected 118 elements, got {len(elements_raw)}"

# ---------------------------------------------------------------------------
# 2. Category assignment
# ---------------------------------------------------------------------------
ALKALI = {1, 3, 11, 19, 37, 55, 87}
ALKALINE = {2, 4, 12, 20, 38, 56, 88} - {2}
NONMETAL = {6, 7, 8, 15, 16, 34}
HALOGEN = {9, 17, 35, 53, 85, 117}
NOBLE = {2, 10, 18, 36, 54, 86, 118}
METALLOID = {5, 14, 32, 33, 51, 52}
POST_TRANSITION = {13, 31, 49, 50, 81, 82, 83, 84, 113, 114, 115, 116}

CATEGORY_LABEL = {
    "alkali": "碱金属",
    "alkaline": "碱土金属",
    "transition": "过渡金属",
    "post_transition": "主族金属",
    "metalloid": "类金属",
    "nonmetal": "非金属",
    "halogen": "卤素",
    "noble": "稀有气体",
    "lanthanide": "镧系元素",
    "actinide": "锕系元素",
}


def category_of(n: int) -> str:
    if n in ALKALI:
        return "alkali"
    if n in ALKALINE:
        return "alkaline"
    if n in NOBLE:
        return "noble"
    if n in HALOGEN:
        return "halogen"
    if n in NONMETAL:
        return "nonmetal"
    if n in METALLOID:
        return "metalloid"
    if 57 <= n <= 71:
        return "lanthanide"
    if 89 <= n <= 103:
        return "actinide"
    if n in POST_TRANSITION:
        return "post_transition"
    # 21-30, 39-48, 72-80, 104-112
    return "transition"


# ---------------------------------------------------------------------------
# 3. Periodic-table grid coordinates (18 columns, 7 periods + 2 f-block rows)
#    row 8 is a visual spacer before the lanthanide / actinide rows.
# ---------------------------------------------------------------------------
MAIN_LAYOUT: dict[int, tuple[int, int]] = {}


def put_period(start: int, end: int, period: int, cols: list[int]) -> None:
    for n, col in zip(range(start, end + 1), cols):
        MAIN_LAYOUT[n] = (period, col)


put_period(1, 1, 1, [1])            # H
MAIN_LAYOUT[2] = (1, 18)           # He
put_period(3, 4, 2, [1, 2])
put_period(5, 10, 2, list(range(13, 19)))
put_period(11, 12, 3, [1, 2])
put_period(13, 18, 3, list(range(13, 19)))
put_period(19, 36, 4, list(range(1, 19)))
put_period(37, 54, 5, list(range(1, 19)))
MAIN_LAYOUT[55] = (6, 1)           # Cs
MAIN_LAYOUT[56] = (6, 2)           # Ba
put_period(72, 86, 6, list(range(4, 19)))
MAIN_LAYOUT[87] = (7, 1)           # Fr
MAIN_LAYOUT[88] = (7, 2)           # Ra
put_period(104, 118, 7, list(range(4, 19)))
for i, n in enumerate(range(57, 72)):   # La..Lu -> row 9, cols 3..17
    MAIN_LAYOUT[n] = (9, 3 + i)
for i, n in enumerate(range(89, 104)):  # Ac..Lr -> row 10, cols 3..17
    MAIN_LAYOUT[n] = (10, 3 + i)

assert len(MAIN_LAYOUT) == 118

GROUP_LABELS = {
    1: "ⅠA", 2: "ⅡA", 3: "ⅢB", 4: "ⅣB", 5: "ⅤB", 6: "ⅥB",
    7: "ⅦB", 8: "Ⅷ", 9: "Ⅷ", 10: "Ⅷ", 11: "ⅠB", 12: "ⅡB",
    13: "ⅢA", 14: "ⅣA", 15: "ⅤA", 16: "ⅥA", 17: "ⅦA", 18: "0",
}

# ---------------------------------------------------------------------------
# 4. Emit elements.json
# ---------------------------------------------------------------------------
elements = []
for number, (sym, en, zh, mass, pinyin) in enumerate(elements_raw, start=1):
    row, col = MAIN_LAYOUT[number]
    elements.append({
        "number": number,
        "symbol": sym,
        "nameEn": en,
        "nameZh": zh,
        "pinyin": pinyin,
        "mass": mass,
        "massBracketed": mass.startswith("["),
        "category": category_of(number),
        "categoryLabel": CATEGORY_LABEL[category_of(number)],
        "radioactive": number == 43 or number == 61 or number >= 84,
        "synthetic": number in (43, 61) or number >= 93,
        "row": row,
        "column": col,
        "period": row if row <= 7 else (6 if row == 9 else 7),
        "group": col if row <= 7 else None,
    })

elements_doc = {
    "$schemaVersion": 1,
    "generatedBy": "tools/gen_elements.py",
    "layout": {
        "columns": 18,
        "rows": 10,
        "spacerRow": 8,
        "fBlockFirstColumn": 3,
        "fBlockLastColumn": 17,
        "placeholders": [
            {"row": 6, "column": 3, "label": "57-71", "subLabel": "镧系"},
            {"row": 7, "column": 3, "label": "89-103", "subLabel": "锕系"},
        ],
        "groupLabels": GROUP_LABELS,
        "periodLabels": {str(i): str(i) for i in range(1, 8)},
    },
    "elements": elements,
}

# ---------------------------------------------------------------------------
# 5. Emit theme.json
# ---------------------------------------------------------------------------
theme = {
    "$schemaVersion": 1,
    "tile": {
        "background": "#EFE3C0",
        "foreground": "#2B2A28",
        "accent": "#B23A2E",
        "border": "#8C7B55",
        "borderWidth": 1.0,
        "cornerRadius": 2.0,
        "disabledOpacity": 0.32,
        "fontNumber": 15,
        "fontSymbol": 17,
        "fontNameZh": 46,
        "fontNameEn": 14,
        "fontMass": 15,
    },
    "categories": {
        "alkali":         {"fill": "#EFE3C0", "text": "#2B2A28", "border": "#C9B98F"},
        "alkaline":       {"fill": "#EFE3C0", "text": "#2B2A28", "border": "#C9B98F"},
        "transition":     {"fill": "#F3E7C6", "text": "#2B2A28", "border": "#B23A2E"},
        "post_transition":{"fill": "#EFE3C0", "text": "#2B2A28", "border": "#C9B98F"},
        "metalloid":      {"fill": "#A9C79A", "text": "#20321D", "border": "#5F8C6B"},
        "nonmetal":       {"fill": "#5F8C6B", "text": "#F7F3E6", "border": "#3F6A4B"},
        "halogen":        {"fill": "#5F8C6B", "text": "#F7F3E6", "border": "#3F6A4B"},
        "noble":          {"fill": "#C7D98B", "text": "#2B2A28", "border": "#8FA85A"},
        "lanthanide":     {"fill": "#F0DCD5", "text": "#2B2A28", "border": "#B23A2E"},
        "actinide":       {"fill": "#F0DCD5", "text": "#2B2A28", "border": "#B23A2E"},
    },
    "settings": {
        "windowsBackdrop": "Mica",
        "sidebarWidth": 220,
        "windowWidth": 1160,
        "windowHeight": 780,
    },
}

# ---------------------------------------------------------------------------
# 6. Emit intervals.json
# ---------------------------------------------------------------------------
intervals = [
    {"id": "never", "label": "从不", "minutes": 0,   "description": "始终显示当前元素，不自动切换"},
    {"id": "m30",   "label": "每 30 分钟", "minutes": 30,  "description": "每半小时切换一次"},
    {"id": "h1",    "label": "每小时",   "minutes": 60,  "description": "每小时整点切换一次"},
    {"id": "h2",    "label": "每 2 小时", "minutes": 120, "description": "每两小时切换一次"},
    {"id": "h3",    "label": "每 3 小时", "minutes": 180, "description": "每三小时切换一次"},
    {"id": "h6",    "label": "每 6 小时", "minutes": 360, "description": "每六小时切换一次"},
    {"id": "h12",   "label": "每 12 小时","minutes": 720, "description": "每半天切换一次"},
    {"id": "d1",    "label": "每天",     "minutes": 1440,"description": "每 24 小时切换一次"},
]

# ---------------------------------------------------------------------------
# 7. Emit config.schema.json
# ---------------------------------------------------------------------------
schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://elementblocks.local/schemas/config-v1.json",
    "title": "Element Blocks Desktop configuration",
    "type": "object",
    "additionalProperties": False,
    "required": ["version", "enabledSymbols", "rotation"],
    "properties": {
        "version": {"const": 1, "description": "schema version, bumped when migrating"},
        "enabledSymbols": {
            "type": "array",
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1, "maxLength": 3},
            "description": "symbols the rotation picker may choose from",
        },
        "rotation": {
            "type": "string",
            "enum": [i["id"] for i in intervals],
        },
        "position": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "anchor": {"enum": ["TopLeft", "TopRight", "BottomLeft", "BottomRight", "Custom"]},
                "offsetX": {"type": "integer", "minimum": -4096, "maximum": 4096},
                "offsetY": {"type": "integer", "minimum": -4096, "maximum": 4096},
                "monitorIndex": {"type": "integer", "minimum": 0},
            },
        },
        "blockSize": {"type": "integer", "minimum": 80, "maximum": 320},
        "clickThrough": {"type": "boolean"},
        "autoStart": {"type": "boolean"},
        "paused": {"type": "boolean"},
        "lastSymbol": {"type": ["string", "null"]},
        "nextFireUtc": {"type": ["string", "null"], "format": "date-time"},
        "rotationCursor": {"type": "integer", "minimum": 0},
    },
}


def dump(name: str, obj: object) -> None:
    path = SHARED / name
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}  ({path.stat().st_size} bytes)")


dump("elements.json", elements_doc)
dump("theme.json", theme)
dump("intervals.json", intervals)
dump("config.schema.json", schema)
print(f"elements: {len(elements)}, categories: {len(CATEGORY_LABEL)}")
