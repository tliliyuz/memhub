---
confidence: 0.85
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/pitfall/python-format-json-braces-in-prompt
kind: pitfall
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- python
- prompt
- pitfall
tier: candidate
title: Python .format() 会误解析 prompt 中的 JSON 示例花括号
updated_at: '2026-11-18T10:56:54.868098Z'
---

在 prompt 里放置 {...} JSON 示例并用 Python str.format() 注入变量时，花括号会被当成占位符导致 KeyError/解析错误。应改用字符串拼接，或只用 .replace 注入 path/text 等变量。
