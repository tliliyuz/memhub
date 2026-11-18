---
confidence: 0.75
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/procedure/install-semantica-extras-tsinghua-mirror
kind: procedure
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- semantica
- pip
- windows
- tsinghua-mirror
- installation
tier: candidate
title: Install Semantica extras through Tsinghua PyPI mirror on Windows
updated_at: '2026-11-18T10:56:54.868098Z'
---

In a Windows venv, semantica extras can be installed with python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn "semantica[watch,vectorstore-sqlite,documents,llm-openai]". Verify by listing .venv\Scripts\*.exe and running semantica.exe --version and semantica.exe info.
