---
confidence: 0.8
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/procedure/install-verify-semantica-windows
kind: procedure
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- semantica
- installation
- windows
tier: candidate
title: 在 Windows 上安装并验证 semantica
updated_at: '2026-11-18T10:56:54.868098Z'
---

在 Windows PowerShell 中执行：python -m venv .venv；.\.venv\Scripts\python.exe -m pip install --upgrade pip；.\.venv\Scripts\python.exe -m pip install "semantica[watch,vectorstore-sqlite,documents]"；用 .\.venv\Scripts\semantica.exe --version 和 .\.venv\Scripts\semantica.exe info 验证安装。
