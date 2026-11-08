#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""撤销 fix_dsh_022_session.py 的改动（非官方脚本，按现状提供）。

用法（DSHA 容器内 root）：
    python3 revert_dsh_022_session.py --dry-run
    python3 revert_dsh_022_session.py

默认使用 /root/dsh022-session-fix-backups/latest 指向的备份。
也可以 --backup /root/dsh022-session-fix-backups/20261109-012345 指定。

说明
----
* 恢复 web profile 的 package.json 和会话搜索依赖原件（这部分和 dsh 版本无关，
  无论当前是 0.2.1 还是 0.2.2 都需要恢复，否则两边版本会继续对不上）。
* 仅当当前 dsh 版本仍是备份回执里的版本（一般 0.2.2-rc.1）时，才恢复
  dsh-session-persistence-jsonl/lib/index.js 原件并移除 dsha-runtime-fs；
  如果已经用 DSHA「更新受管运行时」恢复到 0.2.1-rc.2，则不会把 0.2.2 的文件
  写回 0.2.1 树里。
* 不会自动降级 dsh；降级请先用 DSHA「安装与环境 → 更新受管运行时」。

MIT License · 见仓库 LICENSE / NOTICE.md。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

DSH_ROOT = "/usr/local/lib/node_modules/@deepseek-ai/dsh"
DSH_NM = DSH_ROOT + "/node_modules"
PROFILE = "/root/.dsh/profiles/web"
SESSION_PATH = DSH_NM + "/@deepseek-ai/dsh-session-persistence-jsonl/lib/index.js"
RUNTIME_FS_DIR = DSH_NM + "/dsha-runtime-fs"
BACKUP_ROOT = "/root/dsh022-session-fix-backups"


def info(message: str) -> None:
    print("[revert] " + message)


def fail(message: str) -> "NoReturn":
    print("ERROR: " + message, file=sys.stderr)
    sys.exit(1)


def package_version(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return str(json.load(stream).get("version", ""))
    except Exception:  # noqa: BLE001
        return ""


def copy_file(source: str, target: str) -> None:
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copy2(source, target)


def replace_tree(source: str, target: str) -> None:
    if os.path.lexists(target):
        if os.path.isdir(target) and not os.path.islink(target):
            shutil.rmtree(target)
        else:
            os.remove(target)
    shutil.copytree(source, target, symlinks=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="撤销 DSHA + DSH 0.2.2 会话修复")
    parser.add_argument("--backup", help="固定备份目录（默认用 latest）")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写文件")
    args = parser.parse_args()

    if os.geteuid() != 0:
        fail("请用容器 root 运行")

    backup_dir = args.backup
    if not backup_dir:
        latest_file = os.path.join(BACKUP_ROOT, "latest")
        if not os.path.isfile(latest_file):
            fail("找不到 latest 备份指针：" + latest_file)
        with open(latest_file, "r", encoding="utf-8") as stream:
            backup_dir = stream.read().strip()
    if not os.path.isdir(backup_dir):
        fail("备份目录不存在：" + backup_dir)

    manifest_path = os.path.join(backup_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        fail("备份缺少 manifest.json：" + backup_dir)
    with open(manifest_path, "r", encoding="utf-8") as stream:
        manifest = json.load(stream)

    current_version = package_version(os.path.join(DSH_ROOT, "package.json"))
    info("备份目录：" + backup_dir)
    info("备份时 dsh 版本：" + str(manifest.get("dshVersion", "未知")))
    info("当前 dsh 版本：" + (current_version or "未知"))

    profile_backup = os.path.join(backup_dir, "profile")
    actions = []
    if os.path.isfile(os.path.join(profile_backup, "package.json.orig")):
        actions.append("恢复 web profile package.json")
    packages_backup = os.path.join(profile_backup, "packages")
    if os.path.isdir(packages_backup):
        for name in sorted(os.listdir(packages_backup)):
            actions.append("恢复 profile 依赖：" + name)

    restore_session = (
        bool(manifest.get("sessionPatched"))
        and os.path.isfile(os.path.join(backup_dir, "session-index.js.orig"))
        and current_version == str(manifest.get("dshVersion", ""))
    )
    if restore_session:
        actions.append("恢复会话模块 index.js 原件")
    elif manifest.get("sessionPatched"):
        info("当前 dsh 版本与备份时不同，跳过会话模块恢复（避免把 0.2.2 文件写回 0.2.1 树）。")
    remove_runtime = bool(manifest.get("runtimeFsInstalled")) and restore_session
    if remove_runtime:
        actions.append("移除 dsha-runtime-fs")

    if not actions:
        info("没有需要恢复的内容。")
        return 0
    for action in actions:
        info("将" + action)
    if args.dry_run:
        info("--dry-run 模式：未做任何修改。")
        return 0

    if os.path.isfile(os.path.join(profile_backup, "package.json.orig")):
        copy_file(os.path.join(profile_backup, "package.json.orig"), os.path.join(PROFILE, "package.json"))
    if os.path.isdir(packages_backup):
        for name in sorted(os.listdir(packages_backup)):
            source = os.path.join(packages_backup, name)
            target = os.path.join(PROFILE, "node_modules", "@deepseek-ai", name.split("@deepseek-ai/")[-1])
            replace_tree(source, target)
    if restore_session:
        copy_file(os.path.join(backup_dir, "session-index.js.orig"), SESSION_PATH)
        if remove_runtime and os.path.isdir(RUNTIME_FS_DIR) and not os.path.islink(RUNTIME_FS_DIR):
            shutil.rmtree(RUNTIME_FS_DIR)

    info("恢复完成。请在 DSHA 启动页点「重启」；如果已恢复官方 0.2.1 运行时，现在应与原先一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())