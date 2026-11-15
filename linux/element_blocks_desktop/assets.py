"""加载随 deb 安装的共享数据契约（elements / theme / intervals）。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# 安装后：/usr/share/element-blocks-desktop/data/
# 开发期：linux/data/ 或仓库根 shared/
CANDIDATES = [
    Path("/usr/share/element-blocks-desktop/data"),
    Path(__file__).resolve().parent.parent / "data",
    Path(__file__).resolve().parents[2] / "shared",
]


def data_dir() -> Path:
    for p in CANDIDATES:
        if (p / "elements.json").is_file():
            return p
    raise FileNotFoundError("找不到 shared 数据目录（elements.json）")


@dataclass(frozen=True)
class Element:
    number: int
    symbol: str
    name_en: str
    name_zh: str
    pinyin: str | None
    mass: str
    mass_bracketed: bool
    category: str
    category_label: str
    radioactive: bool
    synthetic: bool
    row: int
    column: int
    period: int
    group: int | None

    @property
    def tooltip(self) -> str:
        extra = "*" if self.synthetic else ""
        lines = [
            f"{self.number}  {self.symbol}  {self.name_zh}{extra} / {self.name_en}",
            f"相对原子质量 {self.mass}"
            + ("（最长半衰期同位素质量数）" if self.mass_bracketed else ""),
            f"{self.category_label} · 第 {self.period} 周期"
            + (f" · 第 {self.group} 族" if self.group else " · f 区"),
        ]
        if self.radioactive:
            lines.append("放射性元素（红色序号）")
        return "\n".join(lines)


@dataclass(frozen=True)
class Interval:
    id: str
    label: str
    minutes: int
    description: str


class Assets:
    def __init__(self) -> None:
        d = data_dir()
        raw = json.loads((d / "elements.json").read_text(encoding="utf-8"))
        self.theme = json.loads((d / "theme.json").read_text(encoding="utf-8"))
        self.layout = raw["layout"]
        self.elements: list[Element] = [self._element(x) for x in raw["elements"]]
        self.by_symbol = {e.symbol: e for e in self.elements}
        self.intervals = [
            Interval(**{k: v for k, v in x.items() if k in ("id", "label", "minutes", "description")})
            for x in json.loads((d / "intervals.json").read_text(encoding="utf-8"))
        ]
        if len(self.elements) != 118:
            raise ValueError(f"elements.json 应含 118 个元素，实际 {len(self.elements)}")

    @staticmethod
    def _element(x: dict) -> Element:
        return Element(
            number=x["number"], symbol=x["symbol"], name_en=x["nameEn"],
            name_zh=x["nameZh"], pinyin=x.get("pinyin"), mass=x["mass"],
            mass_bracketed=x["massBracketed"], category=x["category"],
            category_label=x["categoryLabel"], radioactive=x["radioactive"],
            synthetic=x["synthetic"], row=x["row"], column=x["column"],
            period=x["period"], group=x["group"],
        )

    def interval(self, id_: str) -> Interval:
        return next((i for i in self.intervals if i.id == id_), self.intervals[0])

    def style(self, category: str) -> dict:
        return self.theme["categories"].get(category, self.theme["categories"]["alkali"])


def hex_to_rgb(value: str) -> tuple[float, float, float]:
    s = value.lstrip("#")
    return tuple(int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]
