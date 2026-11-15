#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""无需 dpkg 工具链，直接从源码树构造合规的 Debian 二进制包（.deb）。

.deb 是 ar 归档：
    !<arch>
    debian-binary       "2.0\n"
    control.tar.gz      ./control ./md5sums ./triggers ...
    data.tar.gz         ./usr/... （uid/gid=0，root:root）

布局与 debian/rules 完全一致，因此本脚本在 Windows 上产出的包与在 Debian 上
执行 `dpkg-buildpackage -us -uc -b` 得到的是等价的 `Architecture: all` 包
（纯 Python，无需编译，故两条路径都合法）。

用法：
    python tools/build_deb.py            # 构建到 dist/
    python tools/build_deb.py --verify   # 重新读取 dist/ 里的 .deb 并校验
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINUX = ROOT / "linux"
DIST = ROOT / "dist"
PKG = "element-blocks-desktop"
UID = GID = 0
UNAME = GNAME = "root"
MTIME = 0  # 可复现构建：固定 mtime / gzip 头 / ar 头


# --------------------------------------------------------------------------
# Debian control 解析
# --------------------------------------------------------------------------
def parse_version() -> str:
    first = (LINUX / "debian" / "changelog").read_text(encoding="utf-8").splitlines()[0]
    m = re.match(r"\S+\s+\(([^)]+)\)", first)
    if not m:
        raise ValueError("无法从 debian/changelog 解析版本号")
    return m.group(1)


def parse_stanza(text: str) -> dict[str, str]:
    """把 RFC822 风格 stanza 解析成 {字段: 值}，续行合并为带 \\n 的值。"""
    out: dict[str, str] = {}
    key = None
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith((" ", "\t")) and key:
            out[key] += "\n" + line.strip()
        else:
            k, _, v = line.partition(":")
            key = k.strip()
            out[key] = v.strip()
    return out


def build_control(version: str, installed_size: int) -> str:
    stanzas = (LINUX / "debian" / "control").read_text(encoding="utf-8").strip().split("\n\n")
    src = parse_stanza(stanzas[0])
    binary = parse_stanza(stanzas[-1])

    fields: list[tuple[str, str]] = [
        ("Package", PKG),
        ("Version", version),
        ("Architecture", binary.get("Architecture", "all")),
        ("Maintainer", src["Maintainer"]),
        ("Installed-Size", str(installed_size)),
    ]
    for name in ("Depends", "Recommends", "Suggests", "Section", "Priority", "Description"):
        value = binary.get(name) or src.get(name)
        if not value:
            continue
        # ${misc:Depends} 由 debhelper 展开（本包无共享库依赖，展开为空）
        value = re.sub(r"\$\{misc:Depends\}\s*,?\s*", "", value)
        value = re.sub(r",\s*,", ",", value).strip().strip(",")
        fields.append((name, value))

    lines: list[str] = []
    for key, value in fields:
        parts = value.split("\n")
        lines.append(f"{key}: {parts[0]}")
        for part in parts[1:]:
            # Debian 续行：单个前导空格，空行用 " ."
            lines.append(" " + (part if part else "."))
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# 文件清单：(源路径, 包内路径, mode)；data.tar 里统一加 "./" 前缀
# --------------------------------------------------------------------------
def collect_files() -> list[tuple[Path, str, int]]:
    files: list[tuple[Path, str, int]] = []
    lib = "/usr/lib/element-blocks-desktop"
    share = "/usr/share/element-blocks-desktop"

    def add(src: Path, dest: str, mode: int = 0o644) -> None:
        if not src.is_file():
            raise FileNotFoundError(src)
        files.append((src, dest.lstrip("/"), mode))

    # Python 包（排除字节码缓存）
    for p in sorted((LINUX / "element_blocks_desktop").rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
            add(p, f"{lib}/element_blocks_desktop/{p.name}")

    # 共享只读数据契约
    for name in ("elements.json", "theme.json", "intervals.json", "config.schema.json"):
        add(LINUX / "data" / name, f"{share}/data/{name}")

    add(LINUX / "data" / "element-blocks-desktop-autostart.desktop",
        f"{share}/element-blocks-desktop-autostart.desktop")
    add(LINUX / "element-blocks-desktop-launcher", "/usr/bin/element-blocks-desktop", 0o755)
    add(LINUX / "data" / "element-blocks-desktop.desktop",
        "/usr/share/applications/element-blocks-desktop.desktop")

    for size in (16, 32, 48, 64, 128, 256):
        add(LINUX / f"data/icons/hicolor/{size}x{size}/apps/element-blocks-desktop.png",
            f"/usr/share/icons/hicolor/{size}x{size}/apps/element-blocks-desktop.png")
    add(LINUX / "data/icons/hicolor/scalable/apps/element-blocks-desktop.svg",
        "/usr/share/icons/hicolor/scalable/apps/element-blocks-desktop.svg")

    add(LINUX / "debian" / "copyright", f"/usr/share/doc/{PKG}/copyright")
    return files


def doc_changelog() -> bytes:
    raw = (LINUX / "debian" / "changelog").read_bytes()
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=MTIME, filename="") as gz:
        gz.write(raw)
    return buf.getvalue()


# --------------------------------------------------------------------------
# tar.gz / ar
# --------------------------------------------------------------------------
def make_targz(members: list[tuple[str, bytes, int]]) -> bytes:
    """members: (包内路径, 内容, mode)。自动补齐目录条目，全部 root:root。"""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=MTIME, filename="") as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as tf:
            dirs: set[str] = {"./"}
            for name, _, _ in members:
                prefix = "./"
                for part in name.lstrip("./").split("/")[:-1]:
                    prefix += part + "/"
                    dirs.add(prefix)
            for d in sorted(dirs):
                info = tarfile.TarInfo(d)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.uid, info.gid, info.uname, info.gname = UID, GID, UNAME, GNAME
                info.mtime = MTIME
                tf.addfile(info)
            for name, data, mode in members:
                info = tarfile.TarInfo("./" + name.lstrip("./"))
                info.size = len(data)
                info.mode = mode
                info.uid, info.gid, info.uname, info.gname = UID, GID, UNAME, GNAME
                info.mtime = MTIME
                tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def ar_member(name: str, data: bytes) -> bytes:
    header = (
        f"{(name + '/'):<16}"
        f"{MTIME:<12d}{UID:<6d}{GID:<6d}{0o100644:<8o}{len(data):<10d}"
    ).encode("ascii") + b"`\n"
    assert len(header) == 60, len(header)
    pad = b"\n" if len(data) % 2 else b""
    return header + data + pad


def make_deb(control_tar: bytes, data_tar: bytes) -> bytes:
    return (
        b"!<arch>\n"
        + ar_member("debian-binary", b"2.0\n")
        + ar_member("control.tar.gz", control_tar)
        + ar_member("data.tar.gz", data_tar)
    )


# --------------------------------------------------------------------------
# 构建
# --------------------------------------------------------------------------
def build() -> Path:
    version = parse_version()
    files = collect_files()
    payload: list[tuple[str, bytes, int]] = []
    for src, dest, mode in files:
        payload.append((dest, src.read_bytes(), mode))
    payload.append((f"usr/share/doc/{PKG}/changelog.Debian.gz", doc_changelog(), 0o644))

    # 随包数据自检
    elements = json.loads((LINUX / "data" / "elements.json").read_text(encoding="utf-8"))
    assert len(elements["elements"]) == 118, "elements.json 必须包含 118 个元素"
    for name, data, _ in payload:
        if name.endswith(".json"):
            json.loads(data.decode("utf-8"))

    md5sums = "".join(
        f"{hashlib.md5(data).hexdigest()}  {name}\n" for name, data, _ in payload
    )
    installed_kb = (sum(len(d) for _, d, _ in payload) + 1023) // 1024
    control = build_control(version, installed_kb)

    control_members = [
        ("control", control.encode("utf-8"), 0o644),
        ("md5sums", md5sums.encode("utf-8"), 0o644),
        ("triggers", b"activate-noawait update-icon-caches\n", 0o644),
    ]
    deb = make_deb(make_targz(control_members), make_targz(payload))

    DIST.mkdir(exist_ok=True)
    out = DIST / f"{PKG}_{version}_all.deb"
    out.write_bytes(deb)
    # 合并而非覆盖：dist/ 里还有 MSIX 与历史版本 deb 的校验和
    sums = DIST / "SHA256SUMS.txt"
    entry = f"{hashlib.sha256(deb).hexdigest()}  {out.name}"
    kept: list[str] = []
    if sums.exists():
        kept = [l for l in sums.read_text(encoding="utf-8").splitlines()
                if not l.endswith("  " + out.name)]
    kept.append(entry)
    sums.write_text("\n".join(sorted(set(kept))) + "\n", encoding="utf-8")
    print(f"BUILD OK  {out.relative_to(ROOT)}  {len(deb):,} bytes")
    print(f"          {len(payload)} files, Installed-Size {installed_kb} KiB, sha256 -> SHA256SUMS.txt")
    print("\n--- control ---\n" + control.rstrip())
    return out


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------
def parse_ar(data: bytes) -> dict[str, bytes]:
    if not data.startswith(b"!<arch>\n"):
        raise ValueError("不是 ar 归档")
    out: dict[str, bytes] = {}
    pos = 8
    while pos < len(data):
        header = data[pos:pos + 60]
        if len(header) < 60:
            break
        name = header[:16].decode("ascii").rstrip().rstrip("/")
        size = int(header[48:58].decode("ascii").strip())
        out[name] = data[pos + 60:pos + 60 + size]
        pos += 60 + size + (size % 2)
    return out


def verify(path: Path) -> None:
    raw = path.read_bytes()
    members = parse_ar(raw)
    assert list(members) == ["debian-binary", "control.tar.gz", "data.tar.gz"], list(members)
    assert members["debian-binary"] == b"2.0\n"

    def read_tar(blob: bytes) -> dict[str, tuple[tarfile.TarInfo, bytes]]:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
            return {m.name.lstrip("./"): (m, tf.extractfile(m).read())
                    for m in tf.getmembers() if m.isfile()}

    ctl = read_tar(members["control.tar.gz"])
    data = read_tar(members["data.tar.gz"])
    control_text = ctl["control"][1].decode("utf-8")
    fields = parse_stanza(control_text)
    assert fields["Package"] == PKG
    assert fields["Architecture"] == "all"
    assert "${misc:Depends}" not in control_text
    assert ">= 3.9" not in control_text, "仍存在过严的 python3 版本下限"
    assert "python3-gi" in fields["Depends"]
    assert int(fields["Installed-Size"]) > 0

    # md5sums 与实际内容一致
    md5 = {}
    for line in ctl["md5sums"][1].decode("utf-8").splitlines():
        digest, _, name = line.partition("  ")
        md5[name] = digest
    assert set(md5) == set(data), "md5sums 与 data.tar 文件清单不一致"
    for name, (info, blob) in data.items():
        assert hashlib.md5(blob).hexdigest() == md5[name], name
        assert info.uid == info.gid == 0 and info.uname == "root", name
    launcher = data["usr/bin/element-blocks-desktop"]
    assert launcher[0].mode == 0o755 and launcher[1].startswith(b"#!/usr/bin/python3")
    assert data["usr/share/applications/element-blocks-desktop.desktop"][1].startswith(b"[Desktop Entry]")

    json_names = [n for n in data if n.endswith(".json")]
    assert len(json_names) == 4, json_names
    for n in json_names:
        json.loads(data[n][1].decode("utf-8"))
    elements = json.loads(data["usr/share/element-blocks-desktop/data/elements.json"][1])
    assert len(elements["elements"]) == 118

    print(f"VERIFY OK {path.name}")
    print(f"  ar members      : {', '.join(members)}")
    print(f"  control.tar.gz  : {', '.join(sorted(ctl))}")
    print(f"  data.tar.gz     : {len(data)} files, {len(members['data.tar.gz']):,} bytes (gzip)")
    print(f"  package         : {fields['Package']} {fields['Version']} {fields['Architecture']}")
    print(f"  installed-size  : {fields['Installed-Size']} KiB")
    print(f"  md5sums         : {len(md5)} entries, all match")
    print(f"  sha256          : {hashlib.sha256(raw).hexdigest()}")
    for n in ("usr/bin/element-blocks-desktop",
              "usr/lib/element-blocks-desktop/element_blocks_desktop/main.py",
              "usr/share/element-blocks-desktop/data/elements.json",
              "usr/share/applications/element-blocks-desktop.desktop",
              "usr/share/icons/hicolor/scalable/apps/element-blocks-desktop.svg",
              "usr/share/doc/element-blocks-desktop/copyright"):
        print(f"    {oct(data[n][0].mode)}  {n}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="只校验 dist/ 里已存在的 deb")
    args = ap.parse_args()
    path = build() if not args.verify else DIST / f"{PKG}_{parse_version()}_all.deb"
    verify(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
