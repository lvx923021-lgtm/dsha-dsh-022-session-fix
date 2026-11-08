# NOTICE

This repository is an **unofficial community workaround**. It is not affiliated
with, endorsed by, or supported by DSH-APP/DSHA, qiannianhuanxiang, DeepSeek, or
the DeepSeek Harness project.

## Adapted / embedded upstream material

### 1. DSHA — MIT

- Upstream: https://github.com/DSH-APP/DSHA
- Copyright (c) 2026 qiannianhuanxiang
- `fix_dsh_022_session.py` embeds, nearly verbatim, the `dsha-runtime-fs`
  module from `app/src/main/assets/runtime-fs/index.js` so that DSH
  0.2.2-rc.1 can perform DSHA's atomic session publishing on Android.
- The session-persistence patch anchors and replacements in
  `fix_dsh_022_session.py` are adapted from DSHA's
  `tools/build-dsh-runtime.py`.

MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

### 2. DeepSeek Harness — MIT

- Upstream: https://github.com/deepseek-ai/deepseek-harness
- Copyright (c) 2026 DeepSeek
- The script applies small text replacements to a locally installed copy of
  `@deepseek-ai/dsh-session-persistence-jsonl`. No upstream package files are
  redistributed in this repository.
- `scripts/check-plugin-compat.mjs` mirrors the plugin compatibility rule
  implemented in `@deepseek-ai/dsh-app-boot` (MIT). It is an independent
  read-only reimplementation for diagnostic purposes.

MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## What is NOT included

- No DSHA APK, DSH package tarballs, binaries, or full upstream source trees.
- No device logs, chat data, credentials, tokens, or other personal data.