#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSHA + DSH 0.2.2-rc.1 会话写入 / sessionController 修复脚本（非官方）。

适用环境
--------
* DSHA Android 客户端（包名 ``dsh.android.client``）v0.2.1-rc.2（build190）自带的
  Ubuntu / proot 容器；
* 容器内的 ``@deepseek-ai/dsh`` 被手动升级到了 ``0.2.2-rc.1``（例如执行过
  ``npm install --global @deepseek-ai/dsh@0.2.2-rc.1``）。

它解决两个会同时出现的症状：
1. DSHA「安装与环境 → 检查全部组件」提示
   ``会话写入补丁缺失：/usr/local/lib/node_modules/@deepseek-ai/dsh-session-persistence-jsonl/lib/index.js``；
2. Web 工作台新建会话失败：
   ``gateway/service-unavailable: typert gateway: session/create: active Service
   "sessionController" is unavailable``。

原理
----
* 重新把 DSHA 的「原子会话发布」补丁应用到
  ``dsh-session-persistence-jsonl/lib/index.js``（``publishSessionExclusive as link``
  + ``DSHA_SESSION_DIRECT_HINTS_V1``），并补齐 ``dsha-runtime-fs`` 模块；
* 把 web profile 中仍固定为 0.2.1-rc.2 的会话搜索依赖替换为容器里随 dsh 0.2.2-rc.1
  一起安装的 0.2.2-rc.1 版本，使 DSH 的 ``sessionQuery`` 服务可以激活。

安全
----
* 只在本机容器内修改文件；不联网、不读取聊天记录/API Key；
* 修改前自动备份到 ``/root/dsh022-session-fix-backups/<时间戳>/``；
* 脚本按现状提供，无任何担保；请先 ``--dry-run`` 预览。

MIT License · 见仓库 LICENSE 与 NOTICE.md（包含上游 MIT 版权声明）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

DSH_ROOT = "/usr/local/lib/node_modules/@deepseek-ai/dsh"
DSH_NM = DSH_ROOT + "/node_modules"
PROFILE = "/root/.dsh/profiles/web"
BACKUP_ROOT = "/root/dsh022-session-fix-backups"
NODE = "/usr/local/bin/node"

EXPECTED_DSH = "0.2.2-rc.1"
SESSION_PKG = "@deepseek-ai/dsh-session-persistence-jsonl"
SESSION_PATH = DSH_NM + "/" + SESSION_PKG + "/lib/index.js"
RUNTIME_FS_DIR = DSH_NM + "/dsha-runtime-fs"
PROFILE_PKGS = [
    "@deepseek-ai/dsh-experimental-session-search",
    "@deepseek-ai/dsh-session-query-sqlite",
    "@deepseek-ai/dsh-tool-session-query",
    "@deepseek-ai/dsh-brand",
]
PROFILE_PIN = "@deepseek-ai/dsh-experimental-session-search"

# 来自 DSH-APP/DSHA app/src/main/assets/runtime-fs/index.js（MIT，见 NOTICE.md）。
RUNTIME_FS_INDEX = r"""/** 用独立临时副本与 renameat2 发布完整文件，保留 link 的源文件和 EEXIST 语义。 */
import { constants } from 'node:fs';
import { copyFile, open, link, lstat, rename, rm } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { dirname, join } from 'node:path';
import { getSystemErrorName } from 'node:util';
import { tryLockExclusive } from '@deepseek-ai/node-addon-system/flock';

let native;
async function kernelPublish(source, target) {
  if (!native) {
    const { default: koffi } = await import('koffi');
    try {
      const library = koffi.load(null);
      let renameNoReplace;
      try { renameNoReplace = library.func('renameat2', 'int', ['int', 'str', 'int', 'str', 'uint']); }
      catch {
        // musl 不一定导出包装函数；编号来自 Linux UAPI，Android arm64 与本地 x64 测试共用。
        const number = { arm64: 276, x64: 316 }[process.arch];
        if (number === undefined) throw new Error('未支持的 syscall 架构');
        const syscall = library.func('syscall', 'long', ['long', 'long', 'str', 'long', 'str', 'uint']);
        renameNoReplace = (...args) => syscall(number, ...args);
      }
      native = { koffi, library, rename: renameNoReplace };
    } catch (cause) { throw Object.assign(new Error('当前系统没有 renameat2', { cause }), { code: 'ENOSYS' }); }
  }
  if (native.rename(-100, source, -100, target, 1) === 0) return;
  const errno = native.koffi.errno();
  const code = getSystemErrorName(-errno);
  throw Object.assign(new Error(`${code}: 无法原子发布文件`), { code, errno, syscall: 'renameat2' });
}

async function lockedSessionPublish(source, target) {
  // 一目录一个永久 inode；不按每个文件永久留下锁，也绝不 unlink 有等待者的锁。
  // 普通文件工具不使用此降级，以保留对其他程序的严格 createIfAbsent 语义。
  const name = join(dirname(target), '.dsha-publish.lock');
  const lock = await open(name, constants.O_CREAT | constants.O_RDWR | constants.O_NOFOLLOW, 0o600);
  try {
    const identity = await lock.stat();
    if (!identity.isFile()) throw Object.assign(new Error('发布锁不是普通文件'), { code: 'EINVAL' });
    await syncParent(target);
    const deadline = Date.now() + 10_000;
    for (;;) {
      try { await tryLockExclusive(lock.fd); break; }
      catch (error) {
        if (!['EAGAIN', 'EWOULDBLOCK'].includes(error.code) || Date.now() >= deadline) throw error;
        await new Promise(resolve => setTimeout(resolve, 25));
      }
    }
    const current = await lstat(name);
    if (!current.isFile() || current.dev !== identity.dev || current.ino !== identity.ino)
      throw Object.assign(new Error('发布锁已被替换'), { code: 'ESTALE' });
    try {
      await lstat(target);
      throw Object.assign(new Error('目标会话文件已存在'), { code: 'EEXIST' });
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
    await rename(source, target);
  } finally { await lock.close(); }
}

async function syncParent(target) {
  const parent = await open(dirname(target), constants.O_RDONLY | constants.O_DIRECTORY);
  try { await parent.sync(); } finally { await parent.close(); }
}

/** 依赖注入只用于隔离文件系统回归；部署入口固定使用真实内核操作。 */
export function createPublisher(renameNoReplace = kernelPublish) {
  return async function publish(source, target, privateSession = false, signal) {
    signal?.throwIfAborted();
    if (process.platform !== 'linux') return link(source, target);
    const temporary = target + '.dsha-publish-' + randomUUID() + '.tmp';
    let created = false;
    try {
      await copyFile(source, temporary, constants.COPYFILE_EXCL);
      created = true;
      // copyFile preserves immutable attachment mode 0400. fsync only needs a
      // readable fd; NOFOLLOW and NONBLOCK reject links without blocking on a
      // substituted FIFO, then fstat excludes directories and special files.
      const file = await open(temporary, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
      try {
        if (!(await file.stat()).isFile()) throw Object.assign(new Error('发布临时文件不是普通文件'), { code: 'EINVAL' });
        await file.sync();
      } finally { await file.close(); }
      signal?.throwIfAborted();
      try { await renameNoReplace(temporary, target); }
      catch (error) {
        if (!privateSession || !['ENOSYS', 'EINVAL', 'EOPNOTSUPP'].includes(error.code)) throw error;
        await lockedSessionPublish(temporary, target);
      }
      await syncParent(target);
    } finally { if (created) await rm(temporary, { force: true }); }
  };
}
export const publishExclusive = createPublisher();
export function publishSessionExclusive(source, target) { return publishExclusive(source, target, true); }
// 图片、文件及不可变别名都保留源对象；不支持排他 rename 的内核使用相同协作锁。
export function publishAttachmentExclusive(source, target) { return publishExclusive(source, target, true); }
"""

RUNTIME_FS_PACKAGE = {
    "name": "dsha-runtime-fs",
    "version": "1.0.0",
    "private": True,
    "type": "module",
    "exports": "./index.js",
    "description": "DSHA 在 Android 上的原子、禁止覆盖文件发布",
    "license": "MIT",
}


def info(message: str) -> None:
    print("[fix] " + message)


def fail(message: str) -> "NoReturn":
    print("ERROR: " + message, file=sys.stderr)
    sys.exit(1)


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as stream:
        return stream.read()


def read_json(path: str):
    with open(path, "r", encoding="utf-8") as stream:
        return json.load(stream)


def sha256_file(path: str) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text_atomic(path: str, text: str, mode: int = 0o600) -> None:
    directory = os.path.dirname(path)
    temporary = os.path.join(directory, "." + os.path.basename(path) + ".dsh022fix.tmp")
    with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)
    try:
        handle = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(handle)
        finally:
            os.close(handle)
    except OSError:
        pass


def package_version(path: str) -> str:
    try:
        return str(read_json(path).get("version", ""))
    except (OSError, ValueError):
        return ""


def copy_tree(source: str, target: str) -> None:
    if os.path.lexists(target):
        if os.path.isdir(target) and not os.path.islink(target):
            shutil.rmtree(target)
        else:
            os.remove(target)
    shutil.copytree(source, target, symlinks=True)


def backup_tree(source: str, target: str) -> None:
    if not os.path.lexists(source):
        return
    if os.path.isdir(source) and not os.path.islink(source):
        shutil.copytree(source, target, symlinks=True)
    else:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)


def patch_session_module(text: str) -> str:
    """按 DSHA build-dsh-runtime.py 的会话补丁逻辑修改 0.2.2-rc.1 模块。"""
    marker = "/* DSHA_SESSION_DIRECT_HINTS_V1 */\n"
    already = (
        "publishSessionExclusive as link" in text
        and marker in text
        and "await link(tmp, finalPath);" in text
    )
    if already:
        return text

    import_pattern = re.compile(r'^import \{([^}]+)\} from "node:fs/promises";', re.M)
    match = import_pattern.search(text)
    if match is None:
        raise ValueError("找不到 node:fs/promises 导入，模块结构可能已变化")
    fields = [item.strip() for item in match.group(1).split(",") if item.strip()]
    if "link" not in fields:
        raise ValueError("node:fs/promises 导入里没有 link，模块结构可能已变化")
    fields.remove("link")
    replacement = (
        'import { publishSessionExclusive as link } from "dsha-runtime-fs";\n'
        'import { ' + ", ".join(fields) + ' } from "node:fs/promises";'
    )
    text = text[: match.start()] + replacement + text[match.end():]

    if marker in text:
        raise ValueError("文件里已有部分 DSHA 会话标记，请先恢复备份后重试")

    create_anchor = (
        "\t\tthis.tracker.registerCreated(snapshot, inheritedEventCount);\n"
        '\t\treturn this.tracker.adopt(new JsonlSessionHandle(this, snapshot.id, snapshot, "write", {'
    )
    create_replacement = (
        "\t\tthis.tracker.registerCreated(snapshot, inheritedEventCount);\n"
        "\t\tthis.dshaSessionHints.remember(snapshot);\n"
        '\t\treturn this.tracker.adopt(new JsonlSessionHandle(this, snapshot.id, snapshot, "write", {'
    )
    class_anchor = (
        "\ttracker;\n"
        "\t/** Backend label for diagnostics and effects; shadows `Service.name` without changing the service key. */"
    )
    find_anchor = "\tasync findLog(id, signal) {\n\t\tconst matches = [];"
    find_replacement = (
        "\tasync findLog(id, signal) {\n"
        "\t\tconst hinted = this.dshaSessionHints.get(id);\n"
        "\t\tif (hinted !== void 0) {\n"
        "\t\t\tconst selected = await this.resolveHintedGeneration(hinted, id, signal);\n"
        "\t\t\tif (selected !== void 0) return selected;\n"
        "\t\t\tthis.dshaSessionHints.forget(id);\n"
        "\t\t}\n"
        "\t\tconst matches = [];"
    )
    resolve_anchor = (
        "\t/** Find the unique authoritative generation for an id across project directories. */\n"
        "\tasync findLog(id, signal) {"
    )
    resolve_replacement = (
        "\t/** Resolve a session published by this backend without relying on parent getdents. */\n"
        "\tasync resolveHintedGeneration(header, id, signal) {\n"
        "\t\tsignal?.throwIfAborted();\n"
        "\t\tconst dir = sessionDir(this.root, header.cwd, id);\n"
        "\t\tconst currentPath = generationLogPath(this.root, header.cwd, id, sessionFormatCatalog.currentVersion, this.compression);\n"
        "\t\tif (await this.exists(currentPath)) return { sourcePath: currentPath, sourceVersion: sessionFormatCatalog.currentVersion, currentPath };\n"
        "\t\tconst oppositePath = generationLogPath(this.root, header.cwd, id, sessionFormatCatalog.currentVersion, this.oppositeCompression());\n"
        "\t\tif (await this.exists(oppositePath)) throw this.encodingMismatch(oppositePath);\n"
        "\t\treturn void 0;\n"
        "\t}\n"
        "\t/** Find the unique authoritative generation for an id across project directories. */\n"
        "\tasync findLog(id, signal) {"
    )
    release_anchor = (
        "\treleaseHandle(handle, materialized) {\n"
        "\t\tthis.tracker.release(handle, materialized);\n"
        "\t}"
    )
    release_replacement = (
        "\treleaseHandle(handle, materialized) {\n"
        "\t\tif (!materialized) this.dshaSessionHints.forget(handle.id);\n"
        "\t\tthis.tracker.release(handle, materialized);\n"
        "\t}"
    )
    hints_anchor = "var JsonlSessionPersistence = class extends SessionPersistence {"
    hints_code = (
        "/* DSHA_SESSION_DIRECT_HINTS_V1 */\n"
        "class DshaSessionHints {\n"
        "\tentries = new Map();\n"
        "\tremember(header) {\n"
        '\t\tif (header && typeof header.id === "string") this.entries.set(header.id, { id: header.id, cwd: header.cwd });\n'
        "\t}\n"
        "\tget(id) { return this.entries.get(id); }\n"
        "\tforget(id) { this.entries.delete(id); }\n"
        "}\n"
    )

    for anchor, value in (
        (create_anchor, create_replacement),
        (class_anchor, "\tdshaSessionHints = new DshaSessionHints();\n" + class_anchor),
        (find_anchor, find_replacement),
        (resolve_anchor, resolve_replacement),
        (release_anchor, release_replacement),
        (hints_anchor, hints_code + hints_anchor),
    ):
        if anchor == class_anchor and text.count("\t\tthis.tracker = tracker;") != 1:
            raise ValueError("tracker 构造器锚点变化，模块结构可能已变化")
        if text.count(anchor) != 1:
            raise ValueError("模块结构已变化，找不到唯一锚点：" + anchor.splitlines()[0][:60])
        text = text.replace(anchor, value)

    patched = marker + text
    if patched.count("await link(tmp, finalPath);") != 1:
        raise ValueError("补丁后的 link 调用点数量异常")
    return patched


def run_node_import(module: str, cwd: str) -> subprocess.CompletedProcess:
    code = (
        "import(" + json.dumps(module) + ").then(m => {"
        "console.log('IMPORT_OK', Object.keys(m).length);"
        "}).catch(e => {console.error('IMPORT_FAIL', e && e.stack || e); process.exit(1);});"
    )
    return subprocess.run(
        [NODE, "--input-type=module", "-e", code],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="DSHA + DSH 0.2.2-rc.1 会话修复（非官方）")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写文件")
    parser.add_argument("--force", action="store_true", help="即使 DSH 版本不是 0.2.2-rc.1 也继续")
    parser.add_argument("--skip-profile", action="store_true", help="只修复会话模块，不动 web profile 依赖")
    args = parser.parse_args()

    if os.geteuid() != 0:
        fail("请用容器 root 运行（DSHA 终端里通常已经是 root）")

    for path in (DSH_ROOT, DSH_NM, PROFILE):
        if not os.path.isdir(path):
            fail("找不到预期路径：" + path)

    installed_version = package_version(os.path.join(DSH_ROOT, "package.json"))
    info("已安装 dsh 版本：" + (installed_version or "未知"))
    if installed_version != EXPECTED_DSH and not args.force:
        fail(
            "本脚本只针对 dsh " + EXPECTED_DSH + "；当前是 " + (installed_version or "未知")
            + "。确认要强制继续请加 --force。"
        )

    if not os.path.isfile(SESSION_PATH):
        fail("找不到会话模块：" + SESSION_PATH)
    session_text = read_text(SESSION_PATH)
    session_needs_patch = "publishSessionExclusive as link" not in session_text

    runtime_needs_install = True
    runtime_index = os.path.join(RUNTIME_FS_DIR, "index.js")
    if os.path.isfile(runtime_index):
        try:
            runtime_needs_install = read_text(runtime_index) != RUNTIME_FS_INDEX
        except OSError:
            runtime_needs_install = True

    profile_actions = []
    if not args.skip_profile:
        for package in PROFILE_PKGS:
            source = os.path.join(DSH_NM, package)
            target = os.path.join(PROFILE, "node_modules", package)
            if not os.path.isdir(source):
                fail("容器内缺少依赖目录：" + source + "（dsh 安装可能不完整）")
            if package_version(os.path.join(target, "package.json")) != EXPECTED_DSH:
                profile_actions.append((package, source, target))

    info("会话模块补丁：" + ("需要应用" if session_needs_patch else "已存在，跳过"))
    info("dsha-runtime-fs：" + ("需要写入" if runtime_needs_install else "已存在，跳过"))
    if args.skip_profile:
        info("web profile 依赖：按 --skip-profile 跳过")
    elif profile_actions:
        info("web profile 依赖需要升级：" + ", ".join(item[0] for item in profile_actions))
    else:
        info("web profile 依赖：已是 " + EXPECTED_DSH + "，跳过")

    if args.dry_run:
        info("--dry-run 模式：未做任何修改。")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    os.makedirs(BACKUP_ROOT, mode=0o700, exist_ok=True)
    backup_dir = os.path.join(BACKUP_ROOT, stamp)
    os.makedirs(backup_dir, mode=0o700, exist_ok=True)
    os.makedirs(os.path.join(backup_dir, "profile", "packages"), exist_ok=True)
    info("备份目录：" + backup_dir)

    manifest = {
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "dshVersion": installed_version,
        "sessionPatched": bool(session_needs_patch),
        "runtimeFsInstalled": bool(runtime_needs_install),
        "profilePackages": [item[0] for item in profile_actions],
        "profilePinUpdated": False,
        "sessionSha256Before": sha256_file(SESSION_PATH),
    }

    if session_needs_patch:
        shutil.copy2(SESSION_PATH, os.path.join(backup_dir, "session-index.js.orig"))

    profile_manifest = os.path.join(PROFILE, "package.json")
    if os.path.isfile(profile_manifest):
        shutil.copy2(profile_manifest, os.path.join(backup_dir, "profile", "package.json.orig"))
    for package, source, target in profile_actions:
        backup_tree(target, os.path.join(backup_dir, "profile", "packages", package))

    with open(os.path.join(backup_dir, "manifest.json"), "w", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
    with open(os.path.join(BACKUP_ROOT, "latest"), "w", encoding="utf-8") as stream:
        stream.write(backup_dir + "\n")
    os.chmod(os.path.join(BACKUP_ROOT, "latest"), 0o600)

    try:
        if runtime_needs_install:
            os.makedirs(RUNTIME_FS_DIR, mode=0o700, exist_ok=True)
            write_text_atomic(os.path.join(RUNTIME_FS_DIR, "index.js"), RUNTIME_FS_INDEX, 0o600)
            write_text_atomic(
                os.path.join(RUNTIME_FS_DIR, "package.json"),
                json.dumps(RUNTIME_FS_PACKAGE, ensure_ascii=False, indent=2) + "\n",
                0o600,
            )
            info("已写入 dsha-runtime-fs")

        if session_needs_patch:
            patched = patch_session_module(session_text)
            write_text_atomic(SESSION_PATH, patched, 0o600)
            info("已修补会话模块：" + SESSION_PATH)

        if profile_actions:
            for package, source, target in profile_actions:
                os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
                copy_tree(source, target)
                info("已更新 profile 依赖：" + package + " -> " + EXPECTED_DSH)
            package_json = read_json(profile_manifest)
            dependencies = package_json.setdefault("dependencies", {})
            if PROFILE_PIN in dependencies and dependencies[PROFILE_PIN] != EXPECTED_DSH:
                dependencies[PROFILE_PIN] = EXPECTED_DSH
                write_text_atomic(
                    profile_manifest,
                    json.dumps(package_json, ensure_ascii=False, indent=2) + "\n",
                    0o600,
                )
                manifest["profilePinUpdated"] = True
                with open(os.path.join(backup_dir, "manifest.json"), "w", encoding="utf-8") as stream:
                    json.dump(manifest, stream, ensure_ascii=False, indent=2)
                info("已更新 profile package.json 依赖 pin：" + PROFILE_PIN)
    except Exception as error:  # noqa: BLE001
        print("ERROR: 修复未完成：" + str(error), file=sys.stderr)
        print("已将改动前的文件备份到：" + backup_dir, file=sys.stderr)
        return 1

    info("开始验证会话模块可被 Node 加载…")
    result = run_node_import(SESSION_PKG, DSH_ROOT)
    print(result.stdout.strip())
    if result.returncode != 0:
        fail("会话模块加载失败；请检查输出，或用备份恢复后反馈问题：" + backup_dir)

    verify_text = read_text(SESSION_PATH)
    for token in (
        "publishSessionExclusive as link",
        "DSHA_SESSION_DIRECT_HINTS_V1",
        "await link(tmp, finalPath);",
    ):
        if token not in verify_text:
            fail("修补后的模块缺少标记：" + token)

    info("完成。请在 DSHA 启动页点「重启」，等待 DSH 就绪后进入工作台新建会话验证。")
    info("如需回退，先按 README 的官方方式恢复受管运行时，再运行 revert_dsh_022_session.py。")
    return 0


if __name__ == "__main__":
    sys.exit(main())