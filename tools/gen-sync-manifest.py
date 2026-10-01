#!/usr/bin/env python3
"""
生成 / 更新远程插件同步清单 sync-plugins.json。

用法：
    python tools/gen-sync-manifest.py              # 扫描 plugins/ 重建清单，Version 自动 +1
    python tools/gen-sync-manifest.py --keep-version   # 不递增 Version（仅改内容时用）
    python tools/gen-sync-manifest.py --check          # 只打印将要写入的内容，不落盘

它做三件事：
  1. 扫描 plugins/*.cipx，从包内 manifest.yml 读出插件 id 与 version
  2. 计算每个包的 sha256，写进 Hash 字段（客户端会强制校验）
  3. 版本号 +1 —— 只有 Version 变化，教室机才会重新比对插件版本

新增插件的正确姿势：
  1. 把新插件的 .cipx 放进 plugins/（文件名随意，内容必须含 manifest.yml）
  2. 运行本脚本
  3. git commit && git push
"""

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO / "plugins"
MANIFEST = REPO / "sync-plugins.json"

# 主源与镜像：raw.githubusercontent.com 在国内可能不通，jsDelivr 作为兜底
PRIMARY = "https://raw.githubusercontent.com/wngmay/ZhongXianMiddleSchool-ClassislandControl-Class11/main"
MIRROR = "https://gcore.jsdelivr.net/gh/wngmay/ZhongXianMiddleSchool-ClassislandControl-Class11@main"


def read_yaml_field(text: str, field: str):
    """从 manifest.yml 文本里取一个顶层标量字段，避免引入 PyYAML 依赖。"""
    pattern = re.compile(rf"^\s*{field}\s*:\s*[\"']?([^\"'\r\n]+)[\"']?\s*$", re.MULTILINE)
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_plugin(pkg: Path):
    with zipfile.ZipFile(pkg) as zf:
        try:
            text = zf.read("manifest.yml").decode("utf-8", errors="replace")
        except KeyError:
            print(f"[跳过] {pkg.name}：包内没有 manifest.yml，不是合法插件包", file=sys.stderr)
            return None

    plugin_id = read_yaml_field(text, "id")
    version = read_yaml_field(text, "version")
    if not plugin_id:
        print(f"[跳过] {pkg.name}：manifest.yml 里没有 id", file=sys.stderr)
        return None

    rel = pkg.relative_to(REPO).as_posix()
    return {
        "Id": plugin_id,
        "Version": version or "0.0.0",
        "Url": f"{PRIMARY}/{rel}",
        "Hash": f"sha256:{sha256_of(pkg)}",
        "Mirrors": [f"{MIRROR}/{rel}"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-version", action="store_true", help="不递增清单 Version")
    parser.add_argument("--check", action="store_true", help="只打印不写文件")
    args = parser.parse_args()

    if not PLUGINS_DIR.is_dir():
        print(f"没有插件目录：{PLUGINS_DIR}", file=sys.stderr)
        return 1

    packages = sorted(PLUGINS_DIR.glob("*.cipx"))
    plugins = [item for item in (collect_plugin(p) for p in packages) if item]
    if not plugins:
        print("plugins/ 下没有可用的 .cipx", file=sys.stderr)
        return 1

    old_version = 0
    old_automation_version = 0
    if MANIFEST.exists():
        try:
            old = json.loads(MANIFEST.read_text(encoding="utf-8"))
            old_version = int(old.get("Version", 0))
            old_automation_version = int((old.get("Automation") or {}).get("Version", 0))
        except Exception as exc:
            print(f"[警告] 现有清单解析失败，将按 Version=1 重建：{exc}", file=sys.stderr)

    manifest = {
        "Version": old_version if args.keep_version else old_version + 1,
        "Plugins": plugins,
    }

    rules = REPO / "automation" / "rules.json"
    if rules.exists():
        rel = rules.relative_to(REPO).as_posix()
        manifest["Automation"] = {
            "Version": old_automation_version if args.keep_version else old_automation_version + 1,
            "Url": f"{PRIMARY}/{rel}",
            "Hash": f"sha256:{sha256_of(rules)}",
            "Mirrors": [f"{MIRROR}/{rel}"],
        }

    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        print(text)
        return 0

    MANIFEST.write_text(text, encoding="utf-8")
    print(f"已写入 {MANIFEST}  (Version={manifest['Version']}, {len(plugins)} 个插件)")
    for item in plugins:
        print(f"  - {item['Id']} {item['Version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
