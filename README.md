# DSHA + DSH 0.2.2-rc.1 会话修复（非官方 workaround）

> **非官方社区补丁**。本仓库与 DSH-APP/DSHA、qiannianhuanxiang、DeepSeek 及 DeepSeek Harness 项目
> **没有隶属、背书或支持关系**。按 MIT 许可证「现状」提供，不提供任何明示或默示担保；
> 是否使用、是否继续修改你的设备由你自行判断并承担风险。见 [LICENSE](LICENSE) 与 [NOTICE.md](NOTICE.md)。

如果你在 DSHA 安卓客户端中把容器内的 `@deepseek-ai/dsh` 手动升级到了 `0.2.2-rc.1`，然后遇到下面两个报错，
这个脚本可以尝试修复：

- 工作台新建会话失败：  
  `新建会话失败：gateway/service-unavailable: typert gateway: session/create: active Service "sessionController" is unavailable`
- DSHA「安装与环境 → 检查全部组件」：  
  `会话写入补丁缺失：/usr/local/lib/node_modules/@deepseek-ai/dsh-session-persistence-jsonl/lib/index.js`

> 只想恢复到官方支持组合（DSHA 自带的 DSH 0.2.1-rc.2）的人，建议直接在 DSHA 里点「安装与环境 → 更新受管运行时」，
> 不需要使用本仓库。

---

## 为什么会坏（题外话，方便核对）

DSHA 在安卓 proot/SELinux 环境里不能依赖 Node 原生的 `link(2)` 发布会话文件，所以它的构建流程会把
`dsh-session-persistence-jsonl` 的会话发布改成自己提供的 `publishSessionExclusive`（`dsha-runtime-fs` 模块）。

手动 `npm install --global @deepseek-ai/dsh@0.2.2-rc.1` 会覆盖整个受管 dsh 树：

1. 会话写入补丁和 `dsha-runtime-fs` 丢失；
2. web profile 里仍固定着 0.2.1-rc.2 的 `@deepseek-ai/dsh-experimental-session-search` 及其依赖。
   DSH 0.2.2 会把它们判定为版本不兼容并自动禁用，导致 `sessionQuery` 服务没人提供，
   `sessionController` 无法激活，于是新建会话失败。

`fix_dsh_022_session.py` 做两件事：

1. 重新给会话模块打上 DSHA 的会话发布补丁，并写入 `dsha-runtime-fs`；
2. 把 web profile 里 4 个 0.2.1-rc.2 的会话依赖替换为容器中随 dsh 0.2.2-rc.1 一起安装的 0.2.2-rc.1 版本，
   并同步 `package.json` 的依赖 pin。

---

## 环境要求

- DSHA 安卓客户端：包名 `dsh.android.client`，版本 `0.2.1-rc.2-20261022.2100-dsh0.2.1-rc.2`（build190）；
- 容器内的 `@deepseek-ai/dsh` 版本为 **`0.2.2-rc.1`**（脚本默认只接受这个版本，防止误伤其它环境）；
- 在 DSHA 的「Ubuntu · PTY」终端里以容器 root 执行（不是 Android root，也不是电脑上的 root）；
- 不需要联网；脚本不会上传任何数据。

已验证的设备/组合：vivo V2403A / Android 16 / DSHA 标准版 build190 / dsh 0.2.2-rc.1。
其它机型、其它 DSHA 版本或其它 dsh 版本不保证适用。

---

## 使用步骤

1. 把脚本放到手机（任选一种）：
   ```bash
   adb push fix_dsh_022_session.py /sdcard/Download/
   adb push revert_dsh_022_session.py /sdcard/Download/
   ```
   或直接在手机上把文件保存到 `Download/`。
2. 打开 DSHA → 底部「终端」→ 切到 `Ubuntu · PTY`，先预览：
   ```bash
   python3 /sdcard/Download/fix_dsh_022_session.py --dry-run
   ```
3. 确认输出符合预期后执行：
   ```bash
   python3 /sdcard/Download/fix_dsh_022_session.py
   ```
   脚本会自动备份到 `/root/dsh022-session-fix-backups/<时间戳>/`，并在最后做一次 Node 加载验证。
4. 回到 DSHA 启动页，点「重启」，等待 DSH 就绪，进入工作台新建会话验证。
5. 可选：到「安装与环境 → 检查全部组件」，六项应全部通过。

## 验证是否修好

- 新建会话不再出现 `sessionController ... unavailable`；
- `安装与环境` 的「会话写入补丁」显示通过（六项全绿）；
- 会话文件会实际写入（例如 `/root/.dsh/sessions/.../session.v4.jsonl.zstd`）。

## 回退

**推荐顺序（回到官方 0.2.1-rc.2 组合）：**

1. 在 DSHA「安装与环境 → 更新受管运行时」恢复官方受管运行时；
2. 在 DSHA 终端执行：
   ```bash
   python3 /sdcard/Download/revert_dsh_022_session.py
   ```
   它会把 web profile 的 `package.json` 和会话搜索依赖恢复成备份原件；如果当前 dsh 已不是
   0.2.2-rc.1，它不会把 0.2.2 的会话模块写回 0.2.1 树里。
3. 重启 Web。

如果只是想临时撤销本脚本、但仍留在 0.2.2：也可以直接运行 restore 脚本（会回到「原始未修复」的 0.2.2 状态，
也就是会重新出现 sessionController 不可用）。

## 已知限制（务必阅读）

- DSH 0.2.2 启动时会自动跳过 4 个版本不兼容的 DSHA 内置插件：
  `dsh-device-shell-guide`、`dsh-computer-use-android`、`dsh-auto-review`、`dsh-tool-vscreen`。
  因此**虚拟屏、Computer Use、自动审查、设备 shell 指南**等功能在 0.2.2 下暂不可用。
  建议等 DSHA 发布适配新 DSH 的版本；不建议用版本豁免强行加载，可能崩溃或损坏数据。
- DSHA APK 仍按 0.2.1-rc.2 管理运行时，所以安装页仍显示「受管运行时 0.2.1-rc.2」，
  启动时也可能记录 `PATCH_RUNTIME_VERSION_MISMATCH`，属于版本记录不一致，不是本次修复引入的问题。
- DSHA 后续「更新受管运行时」或 DSH 再次升级都会覆盖本修复；届时需要重新执行或等待官方支持。
- 本补丁只恢复会话链路，不包含 DSHA 针对 0.2.1 的其它 UI/行为补丁，行为不会与官方 0.2.1 组合 100% 一致。

## 安全 / 法务说明

- 脚本只修改**你自己的**手机、你自己的容器里的本地文件，修改前自动备份；不联网、不读取聊天记录/凭据、
  不上传任何数据；
- 本仓库**不包含** DSHA/DSH 的二进制、APK 或完整源码；少量上游 MIT 代码/补丁锚点按 MIT 许可保留版权声明和许可文本，
  详见 [NOTICE.md](NOTICE.md)；
- 本仓库是独立社区作品，不代表任何上游项目，也未获其背书；
- 不同国家和地区可能有额外的软件修改/分发规定；如果对此有顾虑，请先咨询专业人士。本文不构成法律建议；
- **请勿**把任何 GitHub Token、API Key、手机日志或个人数据提交到本仓库或 issue。

---

## English summary

Unofficial MIT-licensed workaround for the following combination:

- DSHA Android client `dsh.android.client` v0.2.1-rc.2 (build190); and
- `@deepseek-ai/dsh` manually upgraded to `0.2.2-rc.1` inside the bundled Ubuntu/proot container.

Symptoms: `active Service "sessionController" is unavailable` when creating a session, and the
DSHA environment check reports a missing session-write patch.

The fix re-applies DSHA's atomic session publish patch (`publishSessionExclusive` / `dsha-runtime-fs`),
and upgrades the web profile's pinned 0.2.1-rc.2 session-search dependencies to the 0.2.2-rc.1 copies
already present in the container.

It is provided **as-is, without warranty**, is **not affiliated with or endorsed by** DSHA, DeepSeek,
or the DeepSeek Harness project, and only modifies files on your own device after making a backup.
The official/supported way back is DSHA's "Update managed runtime" (restores DSH 0.2.1-rc.2).

Run inside the DSHA Ubuntu PTY terminal as container root:

```bash
python3 /sdcard/Download/fix_dsh_022_session.py --dry-run
python3 /sdcard/Download/fix_dsh_022_session.py
```

Then restart DSH Web from the DSHA launch page.

## Files

- `fix_dsh_022_session.py` — apply the workaround (with dry-run and automatic backup)
- `revert_dsh_022_session.py` — restore profile / session module from the latest backup
- `LICENSE` — MIT license for this repository
- `NOTICE.md` — upstream MIT notices and what was adapted