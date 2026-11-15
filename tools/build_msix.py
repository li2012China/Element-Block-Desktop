#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 dotnet build 的产物按 .build.appxrecipe 组装为 MSIX，并用自签名证书签名。

依赖（都由 NuGet 还原，无需 Visual Studio / Windows SDK 安装）：
    microsoft.windows.sdk.buildtools/10.0.26100.1742/bin/.../x64/makeappx.exe
    microsoft.windows.sdk.buildtools/10.0.26100.1742/bin/.../x64/signtool.exe

打包中间文件放在纯 ASCII 的临时目录，避免 makeappx/signtool 处理中文路径出错。

用法：
    dotnet build windows/src/ElementBlocks.Desktop/ElementBlocks.Desktop.csproj `
        -c Release -p:Platform=x64
    powershell -File tools/make_cert.ps1
    python tools/build_msix.py
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJ = ROOT / "windows" / "src" / "ElementBlocks.Desktop"
OUT = PROJ / "bin" / "x64" / "Release" / "net8.0-windows10.0.19041.0"
RECIPE = OUT / "ElementBlocks.Desktop.build.appxrecipe"
DIST = ROOT / "dist"
CERTS = DIST / "certs"
PFX = CERTS / "ElementBlocksDesktop.pfx"
PFX_PASSWORD = "ElementBlocksDev"
NAME = "ElementBlocksDesktop_1.0.1.3_x64.msix"
NUGET = Path.home() / ".nuget" / "packages"
BT = NUGET / "microsoft.windows.sdk.buildtools" / "10.0.26100.1742" / "bin" / "10.0.26100.0" / "x64"
MAKEAPPX = BT / "makeappx.exe"
SIGNTOOL = BT / "signtool.exe"
NS = "{http://schemas.microsoft.com/developer/msbuild/2003}"
# makeappx 不接受非 ASCII 路径，统一在纯 ASCII 目录里组装
STAGE = Path("C:/Temp/ebd-msix") if os.name == "nt" else Path("/tmp/ebd-msix")
LAYOUT = STAGE / "layout"


def run(cmd: list[str], label: str) -> subprocess.CompletedProcess:
    print(f"\n$ {label}")
    r = subprocess.run([str(x) for x in cmd], capture_output=True, text=True,
                       errors="replace", encoding=None)
    for stream in (r.stdout, r.stderr):
        if stream and stream.strip():
            print(stream.strip()[:4000])
    if r.returncode != 0:
        print(f"!! {label} 退出码 {r.returncode}")
    return r


def recipe_entries() -> list[tuple[Path, str]]:
    tree = ET.parse(RECIPE)
    entries: list[tuple[Path, str]] = []
    for tag in ("AppXManifest", "AppxPackagedFile"):
        for node in tree.iter(NS + tag):
            src = Path(node.attrib["Include"])
            pkg = node.find(NS + "PackagePath")
            if pkg is None or not pkg.text:
                continue
            dest = pkg.text.replace("\\", "/")
            if not src.is_file():
                # 少数条目指向 obj/apphost.exe 或 NuGet 的 UAP 变体；回退到 bin 里的同名文件
                alt = OUT / src.name
                if alt.is_file():
                    src = alt
                else:
                    raise FileNotFoundError(f"recipe 引用的文件不存在：{src}")
            entries.append((src, dest))
    return entries


def build_layout() -> None:
    if LAYOUT.exists():
        shutil.rmtree(LAYOUT)
    LAYOUT.mkdir(parents=True)
    entries = recipe_entries()
    seen: set[str] = set()
    for src, dest in entries:
        if dest in seen:
            continue
        seen.add(dest)
        target = LAYOUT / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    print(f"LAYOUT OK  {len(seen)} files -> {LAYOUT}")

    # 清单引用的关键资源必须真实存在，否则安装时才会失败
    manifest = ET.parse(LAYOUT / "AppxManifest.xml").getroot()
    referenced = [v for el in manifest.iter() for v in el.attrib.values()
                  if re.match(r"^Assets[/\\].+\.(png|ico|jpg)$", v, re.I)]
    for ref in referenced:
        p = LAYOUT / ref.replace("\\", "/")
        if not p.is_file():
            raise FileNotFoundError(f"AppxManifest 引用但布局中缺失：{ref}")
    for must in ("ElementBlocks.Desktop.exe", "ElementBlocks.Desktop.dll",
                 "resources.pri", "AppxManifest.xml",
                 "Assets/Data/elements.json", "Assets/Data/theme.json",
                 "Assets/Data/intervals.json", "Assets/Data/config.schema.json"):
        if not (LAYOUT / must).is_file():
            raise FileNotFoundError(f"布局缺少必需文件：{must}")
    print(f"MANIFEST OK  {len(referenced)} 个图标/图像引用全部存在")


def pack() -> Path:
    out = STAGE / NAME
    if out.exists():
        out.unlink()
    r = run([MAKEAPPX, "pack", "/d", LAYOUT, "/p", out, "/o", "/v"], "makeappx pack")
    if r.returncode != 0 or not out.is_file():
        raise RuntimeError("makeappx pack 失败")
    return out


def sign(msix: Path) -> bool:
    if not PFX.is_file():
        print(f"\n! 未找到 {PFX}，跳过签名（先运行 tools/make_cert.ps1）")
        return False
    r = run([SIGNTOOL, "sign", "/fd", "SHA256", "/f", PFX,
             "/p", PFX_PASSWORD, "/v", msix], "signtool sign")
    if r.returncode != 0:
        raise RuntimeError("signtool sign 失败（证书 Subject 需为 CN=Element Blocks Desktop）")
    return True


def inspect(msix: Path, signed: bool) -> None:
    with zipfile.ZipFile(msix) as z:
        names = set(z.namelist())
        required = {"AppxManifest.xml", "[Content_Types].xml", "AppxBlockMap.xml",
                    "ElementBlocks.Desktop.exe", "resources.pri",
                    "Assets/Square150x150Logo.png", "Assets/Data/elements.json"}
        missing = {n for n in required if n not in names}
        if missing:
            raise RuntimeError(f"MSIX 缺少条目：{sorted(missing)}")
        manifest = z.read("AppxManifest.xml").decode("utf-8-sig")
        assert 'ProcessorArchitecture="x64"' in manifest
        assert "Microsoft.WindowsAppRuntime.1.6" in manifest
        assert "ElementBlocksStartup" in manifest
        has_sig = "AppxSignature.p7x" in names
        print(f"\nMSIX OK  {len(names)} entries, {msix.stat().st_size:,} bytes")
        print(f"          AppxSignature.p7x = {has_sig}（签名状态：{'已签名' if signed else '未签名'}）")
        if signed and not has_sig:
            raise RuntimeError("已签名但缺少 AppxSignature.p7x")
        for n in sorted(required):
            print(f"    {n}")
        # 顺便核对随包数据
        import json
        el = json.loads(z.read("Assets/Data/elements.json").decode("utf-8"))
        assert len(el["elements"]) == 118
        print("    elements.json: 118 个元素")


def copy_dependencies() -> None:
    """附带 Microsoft 签名的 Windows App SDK 1.6 框架包，便于离线机器先装依赖。"""
    runtime = NUGET / "microsoft.windowsappsdk" / "1.6.250108002" / "tools" / "MSIX" / "win10-x64"
    if not runtime.is_dir():
        return
    dest = DIST / "dependencies"
    dest.mkdir(parents=True, exist_ok=True)
    for p in sorted(runtime.glob("*.msix")):
        target = dest / p.name
        shutil.copy2(p, target)
        print(f"    dependency: {target.relative_to(ROOT)}  {p.stat().st_size:,} bytes")


def main() -> int:
    for p in (RECIPE, MAKEAPPX, SIGNTOOL):
        if not p.is_file():
            raise FileNotFoundError(f"缺少 {p}；请先执行 dotnet restore / build")
    DIST.mkdir(exist_ok=True)
    build_layout()
    msix = pack()
    signed = sign(msix)
    inspect(msix, signed)

    final = DIST / NAME
    shutil.copy2(msix, final)
    copy_dependencies()

    sums = DIST / "SHA256SUMS.txt"
    lines = [l for l in sums.read_text(encoding="utf-8").splitlines() if NAME not in l] if sums.exists() else []
    lines.append(f"{hashlib.sha256(final.read_bytes()).hexdigest()}  {final.name}")
    sums.write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")
    print(f"\nOUTPUT  {final.relative_to(ROOT)}  {final.stat().st_size:,} bytes")
    print(f"        sha256 {hashlib.sha256(final.read_bytes()).hexdigest()}")
    print(f"        {'已用自签名证书签名' if signed else '未签名（可执行 tools/make_cert.ps1 后重跑）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
