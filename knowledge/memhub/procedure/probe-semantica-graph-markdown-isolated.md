---
confidence: 0.65
created_at: '2026-11-18T10:56:54.868098Z'
id: memhub/procedure/probe-semantica-graph-markdown-isolated
kind: procedure
project: memhub
source:
- device: local
  ref: fe3e3d8c-1ed3-4acd-854f-a304b28ba0fd.jsonl
  type: session
supersedes: []
tags:
- semantica
- probe
- markdown
- graph
- validation
tier: candidate
title: Probe Semantica graph building from Markdown in an isolated directory
updated_at: '2026-11-18T10:56:54.868098Z'
---

To validate Semantica graph building from Markdown, copy Markdown files into a separate probe directory, write a Python probe script, run it with the venv Python while setting PYTHONIOENCODING=utf-8, and keep the experiment read-only with no network calls.
