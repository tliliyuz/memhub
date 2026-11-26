import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ApiError, api } from '../src/lib/api.ts'

test('记忆列表只透传有值的筛选参数', async (t) => {
  let seen = ''
  t.mock.method(globalThis, 'fetch', async (path) => {
    seen = path
    return Response.json({ items: [], total: 0, offset: 0, limit: 50 })
  })
  await api.memories({ status: 'active', q: '', limit: 50, offset: 100 })
  const url = new URL(seen, 'http://localhost')
  assert.equal(url.pathname, '/api/v1/kb/memories')
  assert.equal(url.searchParams.get('status'), 'active')
  assert.equal(url.searchParams.get('limit'), '50')
  assert.equal(url.searchParams.get('offset'), '100')
  assert.equal(url.searchParams.has('q'), false)
})

test('候选与快照走独立路由，不落入 slug 详情', async (t) => {
  const seen = []
  t.mock.method(globalThis, 'fetch', async (path) => {
    seen.push(path)
    return Response.json({ items: [], total: 0 })
  })
  await api.memoryCandidates({ status: 'conflict' })
  await api.memorySnapshots()
  assert.equal(seen[0], '/api/v1/kb/memories/candidates?status=conflict')
  assert.equal(seen[1], '/api/v1/kb/memories/snapshots')
})

test('更新记忆发送 PATCH 与 expected_revision', async (t) => {
  let request = { path: '' }
  t.mock.method(globalThis, 'fetch', async (path, init) => {
    request = { path, init }
    return Response.json({ slug: 'retry-backoff', revision: 'b'.repeat(16) })
  })
  await api.updateMemory('retry-backoff', {
    expected_revision: 'a'.repeat(16),
    conclusion: '新的结论。',
  })
  assert.equal(request.path, '/api/v1/kb/memories/retry-backoff')
  assert.equal(request.init?.method, 'PATCH')
  assert.deepEqual(JSON.parse(String(request.init?.body)), {
    expected_revision: 'a'.repeat(16),
    conclusion: '新的结论。',
  })
})

test('快照发布、回滚、停用命中约定路径', async (t) => {
  const seen = []
  t.mock.method(globalThis, 'fetch', async (path, init) => {
    seen.push({ path, init })
    return Response.json({ version: 3, status: 'published', item_count: 1 })
  })
  await api.publishMemorySnapshot('第一版')
  await api.activateMemorySnapshot(3)
  await api.disableMemorySnapshot(3, '回滚验收')

  assert.equal(seen[0].path, '/api/v1/kb/memories/snapshots')
  assert.equal(seen[0].init?.method, 'POST')
  assert.deepEqual(JSON.parse(String(seen[0].init?.body)), { note: '第一版' })
  assert.equal(seen[1].path, '/api/v1/kb/memories/snapshots/3/activate')
  assert.equal(seen[2].path, '/api/v1/kb/memories/snapshots/3/disable')
  assert.deepEqual(JSON.parse(String(seen[2].init?.body)), { reason: '回滚验收' })
})

test('乐观锁冲突保留 409 与 1010，供页面展示 ApiError.message', async (t) => {
  t.mock.method(globalThis, 'fetch', async () =>
    Response.json(
      { code: 1010, message: '记忆已被修改，请刷新后重试', data: null },
      { status: 409 },
    ),
  )
  await assert.rejects(
    api.updateMemory('retry-backoff', { expected_revision: 'a'.repeat(16) }),
    (error) => {
      assert.ok(error instanceof ApiError)
      assert.equal(error.status, 409)
      assert.equal(error.code, 1010)
      assert.equal(error.message, '记忆已被修改，请刷新后重试')
      return true
    },
  )
})
