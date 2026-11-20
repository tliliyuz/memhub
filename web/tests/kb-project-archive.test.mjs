import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ApiError, api } from '../src/lib/api.ts'

const archive = {
  archive_id: 'snapshot-01',
  id: 'example',
  name: '示例知识库',
  deleted_at: '2026-11-20T10:00:00Z',
  archived_count: 2,
  removed_edges: 3,
}

test('整库归档返回快照 ID 和节点、关系数量', async (t) => {
  const result = {
    id: archive.id,
    archive_id: archive.archive_id,
    archived_count: archive.archived_count,
    removed_edges: archive.removed_edges,
    commit: null,
  }
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    assert.equal(path, '/api/v1/kb/projects/example')
    assert.equal(options.method, 'DELETE')
    return Response.json(result)
  })
  assert.deepEqual(await api.deleteProject(archive.id), result)
})

test('已归档知识库使用独立列表接口，不传单节点筛选参数', async (t) => {
  const result = { items: [archive], total: 1 }
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    assert.equal(path, '/api/v1/kb/trash/projects')
    assert.equal(options.method ?? 'GET', 'GET')
    return Response.json(result)
  })
  assert.deepEqual(await api.listArchivedProjects(), result)
})

test('整库恢复提交快照 ID，返回节点和关系数量', async (t) => {
  const result = {
    id: archive.id,
    archive_id: archive.archive_id,
    restored_count: 2,
    restored_edges: 3,
    commit: null,
  }
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    assert.equal(path, '/api/v1/kb/trash/projects/restore')
    assert.equal(options.method, 'POST')
    assert.equal(options.headers['Content-Type'], 'application/json')
    assert.deepEqual(JSON.parse(options.body), { archive_id: archive.archive_id })
    return Response.json(result)
  })
  assert.deepEqual(await api.restoreProject(archive.archive_id), result)
})

test('整库恢复保留服务端返回的冲突原因', async (t) => {
  const conflict = { code: 1010, message: '同 ID 的知识库已存在', data: { id: archive.id } }
  t.mock.method(globalThis, 'fetch', async () => Response.json(conflict, { status: 409 }))
  await assert.rejects(api.restoreProject(archive.archive_id), {
    name: ApiError.name,
    status: 409,
    ...conflict,
  })
})

test('单节点回收站保留分页、筛选和原有恢复入口', async (t) => {
  const responses = [
    { items: [], total: 0, total_all: 42, offset: 20 },
    { id: 'example/fact/old', revision: 'abc', commit: null },
  ]
  let request = 0
  const fetch = t.mock.method(globalThis, 'fetch', async (path, options) => {
    if (request === 0) {
      const url = new URL(path, 'http://localhost')
      assert.equal(url.pathname, '/api/v1/kb/trash')
      assert.deepEqual(Object.fromEntries(url.searchParams), {
        limit: '20', offset: '20', project: 'example', q: '旧节点',
      })
    } else {
      assert.equal(path, '/api/v1/kb/trash/restore')
      assert.equal(options.method, 'POST')
      assert.deepEqual(JSON.parse(options.body), { trash: 'ts/example/fact/old' })
    }
    return Response.json(responses[request++])
  })
  assert.deepEqual(
    await api.trash({ limit: 20, offset: 20, project: 'example', q: '旧节点' }),
    responses[0],
  )
  assert.deepEqual(await api.restore('ts/example/fact/old'), responses[1])
  assert.equal(fetch.mock.callCount(), 2)
})
