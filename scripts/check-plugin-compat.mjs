#!/usr/bin/env node
// 只读检查当前 DSH profile 里所有 bundle 是否兼容指定 DSH 版本。
//
// 用法：
//   node scripts/check-plugin-compat.mjs [dsh版本] [profile目录] [--dsh-root <DSH安装目录>] [--json]
// 例：
//   node scripts/check-plugin-compat.mjs 0.2.2-rc.1 ~/.dsh/profiles/web
//
// 判定规则与 @deepseek-ai/dsh-app-boot 的 plugin-compatibility 保持一致：
//   1. manifest 有 engines.dsh 时，只用它判断，忽略 peerDependencies；
//   2. 否则逐个检查 peerDependencies 里的 "@deepseek-ai/dsh" 和 "@deepseek-ai/dsh-*"；
//   3. workspace:^ / workspace:~ / workspace:* 视为当前运行时版本；
//   4. semver.satisfies 必须带 { includePrerelease: true }：
//      否则 0.2.2-rc.1 这类 prerelease 版本连 ">=0.2.0-rc.1" 都会被误判为不满足。
//
// 只读：不会写入 profile 或 DSH 安装目录，也不会联网。

import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'

const DEFAULT_DSH_ROOT = '/usr/local/lib/node_modules/@deepseek-ai/dsh'
const WORKSPACE_RANGES = new Set(['workspace:^', 'workspace:~', 'workspace:*'])
const DSH_PACKAGE = '@deepseek-ai/dsh'

function usage() {
  console.log(`用法:
  node check-plugin-compat.mjs [选项] [dsh版本 | profile目录] [profile目录]

  dsh版本        语义化版本，例如 0.2.2-rc.1；默认读取 DSH 安装目录 package.json
  profile目录    默认 $HOME/.dsh/profiles/web

选项:
  --version <v>  指定 DSH 版本
  --profile <p>  指定 profile 目录
  --dsh-root <d> 指定 DSH 安装目录（默认 ${DEFAULT_DSH_ROOT}）
  --json         以 JSON 输出
  -h, --help     显示帮助

例:
  node check-plugin-compat.mjs --version 0.2.2-rc.1 --profile ~/.dsh/profiles/web
  node check-plugin-compat.mjs 0.2.2-rc.1 ~/.dsh/profiles/web
  node check-plugin-compat.mjs ~/.dsh/profiles/web   # 版本自动读取`)
}

function parseArgs(argv) {
  const options = { version: '', profile: '', dshRoot: '', json: false }
  const isVersion = (value) => /^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.test(value)
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (arg === '--help' || arg === '-h') {
      usage()
      process.exit(0)
    } else if (arg === '--json') {
      options.json = true
    } else if (arg === '--version') {
      options.version = argv[++i] || ''
      if (!options.version) throw new Error('--version 需要一个版本号')
    } else if (arg === '--profile') {
      options.profile = argv[++i] || ''
      if (!options.profile) throw new Error('--profile 需要一个目录')
    } else if (arg === '--dsh-root') {
      options.dshRoot = argv[++i] || ''
      if (!options.dshRoot) throw new Error('--dsh-root 需要一个目录')
    } else if (arg.startsWith('--')) {
      throw new Error('未知参数：' + arg)
    } else if (!options.version && isVersion(arg)) {
      options.version = arg
    } else if (!options.profile) {
      options.profile = arg
    } else {
      throw new Error('多余的参数：' + arg)
    }
  }
  return options
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'))
}

function readRuntimeVersion(dshRoot) {
  try {
    const version = readJson(path.join(dshRoot, 'package.json')).version
    return typeof version === 'string' && version.trim() ? version.trim() : ''
  } catch {
    return ''
  }
}

function loadSemver(dshRoot) {
  const anchors = [
    path.join(dshRoot, 'package.json'),
    path.join(process.env.HOME || '/root', '.npm-global', 'lib', 'node_modules', '@deepseek-ai', 'dsh', 'package.json'),
    import.meta.url,
  ]
  for (const anchor of anchors) {
    try {
      const requireFrom = createRequire(anchor)
      const module = requireFrom('semver')
      if (module && typeof module.satisfies === 'function') return module
    } catch {
      /* 继续尝试下一个位置 */
    }
  }
  try {
    const module = createRequire(import.meta.url)(path.join(dshRoot, 'node_modules', 'semver'))
    if (module && typeof module.satisfies === 'function') return module
  } catch {
    /* 没有就直接报错 */
  }
  return null
}

function resolveManifest(name, anchors) {
  for (const anchor of anchors) {
    let requireFromAnchor
    try {
      requireFromAnchor = createRequire(anchor)
    } catch {
      continue
    }
    try {
      const file = requireFromAnchor.resolve(name + '/package.json')
      return { manifest: readJson(file), file }
    } catch {
      /* 尝试从入口文件向上找 package.json */
    }
    try {
      let directory = path.dirname(requireFromAnchor.resolve(name))
      for (let depth = 0; depth < 8; depth += 1) {
        const candidate = path.join(directory, 'package.json')
        if (fs.existsSync(candidate)) return { manifest: readJson(candidate), file: candidate }
        const parent = path.dirname(directory)
        if (parent === directory) break
        directory = parent
      }
    } catch {
      /* 继续下一个 anchor */
    }
  }
  return null
}

function satisfies(semver, runtimeVersion, range) {
  if (typeof range !== 'string') return false
  const effective = WORKSPACE_RANGES.has(range) ? runtimeVersion : range
  if (!effective.trim()) return false
  try {
    return semver.satisfies(runtimeVersion, effective, { includePrerelease: true })
  } catch {
    return false
  }
}

// 与 DSH app-boot 的 unmetRequirements() 对应；返回未满足的 requirements 映射。
function unmetRequirements(manifest, runtimeVersion, semver) {
  const fields = manifest && typeof manifest === 'object' ? manifest : {}
  const engines = fields.engines && typeof fields.engines === 'object' && !Array.isArray(fields.engines) ? fields.engines : {}
  if (Object.hasOwn(engines, 'dsh')) {
    const range = engines.dsh
    if (typeof range !== 'string') return { 'engines.dsh': String(range) }
    return satisfies(semver, runtimeVersion, range) ? {} : { 'engines.dsh': range }
  }
  if (!fields.peerDependencies || typeof fields.peerDependencies !== 'object' || Array.isArray(fields.peerDependencies)) {
    return {}
  }
  const unmet = {}
  for (const [name, range] of Object.entries(fields.peerDependencies)) {
    if (name !== DSH_PACKAGE && !name.startsWith(DSH_PACKAGE + '-')) continue
    if (typeof range !== 'string') {
      unmet[name] = range
      continue
    }
    if (!satisfies(semver, runtimeVersion, range)) unmet[name] = range
  }
  return unmet
}

function main() {
  let options
  try {
    options = parseArgs(process.argv.slice(2))
  } catch (error) {
    console.error(error.message)
    usage()
    process.exit(2)
  }

  const dshRoot = options.dshRoot || process.env.DSH_ROOT || DEFAULT_DSH_ROOT
  const profileDir = options.profile || path.join(process.env.HOME || '/root', '.dsh', 'profiles', 'web')
  const runtimeVersion = options.version || readRuntimeVersion(dshRoot)
  const semver = loadSemver(dshRoot)

  if (!runtimeVersion) {
    console.error('无法确定 DSH 版本：请在命令行传入，或检查 --dsh-root 下的 package.json。')
    process.exit(2)
  }
  if (!semver) {
    console.error('找不到 semver。可先 npm i semver，或确认 DSH 安装目录的 node_modules 里有 semver。')
    process.exit(2)
  }

  let profile
  try {
    profile = readJson(path.join(profileDir, 'package.json'))
  } catch (error) {
    console.error('读取 profile package.json 失败：' + path.join(profileDir, 'package.json') + '（' + error.message + '）')
    process.exit(2)
  }
  const bundles = profile?.dsh?.profile?.bundles
  if (!Array.isArray(bundles)) {
    console.error('profile package.json 里没有 dsh.profile.bundles 数组：' + profileDir)
    process.exit(2)
  }

  const anchors = [path.join(profileDir, 'package.json'), path.join(dshRoot, 'package.json')]
  const results = []
  let checked = 0
  let skipped = 0
  for (const bundle of bundles) {
    if (typeof bundle !== 'string' || !bundle.trim()) continue
    const resolved = resolveManifest(bundle.trim(), anchors)
    if (!resolved) {
      skipped += 1
      results.push({ name: bundle, status: 'skipped', reason: 'not-installed' })
      continue
    }
    checked += 1
    const unmet = unmetRequirements(resolved.manifest, runtimeVersion, semver)
    if (Object.keys(unmet).length === 0) {
      results.push({ name: bundle, status: 'ok' })
    } else {
      results.push({
        name: bundle,
        version: resolved.manifest.version,
        status: 'incompatible',
        requirements: unmet,
        manifest: resolved.file,
      })
    }
  }

  const bad = results.filter((item) => item.status === 'incompatible')
  if (options.json) {
    console.log(JSON.stringify({ runtimeVersion, profile: profileDir, checked, skipped, incompatible: bad }, null, 2))
    process.exit(bad.length ? 1 : 0)
  }

  for (const item of bad) {
    console.log('✗ ' + item.name + (item.version ? '@' + item.version : '') + ' 需要 ' + JSON.stringify(item.requirements))
  }
  console.log('')
  console.log('检查 ' + bundles.length + ' 个 bundle：不兼容 ' + bad.length + ' 个（目标版本 ' + runtimeVersion + '）')
  if (skipped) console.log('跳过 ' + skipped + ' 个未在 profile/DSH 安装目录中解析到的 bundle。')
  process.exit(bad.length ? 1 : 0)
}

main()