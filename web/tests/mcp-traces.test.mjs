import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ApiError, api } from '../src/lib/api.ts'
import { credentialLabel, sinceFromDays } from '../src/lib/traces.ts'

test('轨迹列表只透传有值的筛选参数，空串与未定义不进查询串', async (t) => {
  let seen = ''
  t.mock.method(globalThis, 'fetch', async (path) => {
    seen = path
    return Response.json({ items: [], total: 0, offset: 0, limit: 50 })
  })
  await api.mcpTraces({ limit: 50, offset: 100, tool: 'kb_search', status: 'error', credential: '' })
  const url = new URL(seen, 'http://localhost')
  assert.equal(url.pathname, '/api/v1/kb/mcp-traces')
  assert.equal(url.searchParams.get('limit'), '50')
  assert.equal(url.searchParams.get('offset'), '100')
  assert.equal(url.searchParams.get('tool'), 'kb_search')
  assert.equal(url.searchParams.get('status'), 'error')
  assert.equal(url.searchParams.has('credential'), false)
  assert.equal(url.searchParams.has('since'), false)
})

test('轨迹汇总按 days 取近 N 天', async (t) => {
  let seen = ''
  const body = {
    since: '2026-11-18T00:00:00+00:00',
    days: 7,
    total: 3,
    ok: 2,
    error: 1,
    rejected: 0,
    tools: [{ tool: 'kb_search', count: 3, ok: 2, error: 1, rejected: 0, avg_ms: 12 }],
    credentials: [{ id: 'a1b2c3d4e5f6', name: null, count: 3 }],
  }
  t.mock.method(globalThis, 'fetch', async (path) => {
    seen = path
    return Response.json(body)
  })
  assert.deepEqual(await api.mcpTracesSummary(7), body)
  assert.equal(seen, '/api/v1/kb/mcp-traces/summary?days=7')
})

test('非 PG 存储的 503 以 ApiError 抛出并保留错误码', async (t) => {
  t.mock.method(globalThis, 'fetch', async () =>
    Response.json({ code: 2001, message: '仅 PG 存储支持', data: null }, { status: 503 }),
  )
  await assert.rejects(api.mcpTraces(), (error) => {
    assert.ok(error instanceof ApiError)
    assert.equal(error.status, 503)
    assert.equal(error.code, 2001)
    return true
  })
})

test('凭据显示按 name、id、unknown 依次降级', () => {
  assert.equal(credentialLabel({ id: 'a1b2c3d4e5f6', name: 'claude-code-laptop' }), 'claude-code-laptop')
  assert.equal(credentialLabel({ id: 'a1b2c3d4e5f6', name: null }), 'a1b2c3d4e5f6')
  assert.equal(credentialLabel({ id: null, name: null }), 'unknown')
  assert.equal(credentialLabel({ id: '', name: '' }), 'unknown')
})

test('时间范围换算为 ISO 起点，不改动传入的当前时间', () => {
  const now = new Date('2026-11-25T08:00:00Z')
  assert.equal(sinceFromDays(1, now), '2026-11-24T08:00:00.000Z')
  assert.equal(sinceFromDays(30, now), '2026-10-26T08:00:00.000Z')
  assert.equal(now.toISOString(), '2026-11-25T08:00:00.000Z')
})
