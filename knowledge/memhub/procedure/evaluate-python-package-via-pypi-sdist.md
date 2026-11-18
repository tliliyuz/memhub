---
confidence: 0.8
created_at: '2026-11-18T10:54:55.190937Z'
id: memhub/procedure/evaluate-python-package-via-pypi-sdist
kind: procedure
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- evaluation
- pypi
- sdist
- python
tier: candidate
title: 通过 PyPI sdist 本地审查 Python 包
updated_at: '2026-11-18T10:54:55.190937Z'
---

当 GitHub 页面难以直接抓取时，可从 PyPI 下载包的 sdist 源码（如 semantica-0.7.0.tar.gz），解压后本地检查模块结构、pyproject.toml 依赖和关键实现，以评估其能力。
