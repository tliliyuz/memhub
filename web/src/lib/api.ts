/**
 * kb-api 客户端（memhub.kb.api）。
 *
 * 开发期由 Vite 把 `/api` 代理到 127.0.0.1:8701；打包后由 kb-api 自己托管
 * 静态文件，同源相对路径即可，不引入额外环境变量。
 */

export type Kind =
  | 'entity'
  | 'fact'
  | 'decision'
  | 'procedure'
  | 'pitfall'
  | 'preference'
  | 'event'
  | 'question'

export type Tier = 'candidate' | 'canonical' | 'deprecated'

export type EntityKind =
  | 'service'
  | 'component'
  | 'concept'
  | 'tool'
  | 'person'
  | 'team'
  | 'project'
  | 'external_system'
  | 'config'
  | 'other'

export type Predicate =
  | 'part_of'
  | 'depends_on'
  | 'exposes'
  | 'runs_on'
  | 'about'
  | 'resolved_by'
  | 'supersedes'
  | 'contradicts'
  | 'evidenced_by'
  | 'related_to'

export type NodeSummary = {
  id: string
  kind: Kind
  entity_kind: EntityKind | null
  title: string
  tier: Tier
  project: string
  tags: string[]
  confidence: number | null
  status: 'open' | 'resolved' | null
  created_at: string
  updated_at: string
  revision: string
  body_chars: number
}

export type Frontmatter = {
  id: string
  kind: Kind
  entity_kind: EntityKind | null
  title: string
  tier: Tier
  confidence: number | null
  project: string
  tags: string[]
  source: {
    type: string
    ref: string
    device: string | null
    captured_at: string | null
  }[]
  created_at: string
  updated_at: string
  valid_from: string | null
  valid_until: string | null
  supersedes: string[]
  superseded_by: string | null
  deprecated_reason: string | null
  occurred_at: string | null
  decided_at: string | null
  status: 'open' | 'resolved' | null
}

export type NodeDetail = {
  id: string
  frontmatter: Frontmatter
  body: string
  truncated: boolean
  edges: {
    out: { predicate: Predicate; target: string }[]
    in: { predicate: Predicate; source: string }[]
  }
  revision: string
}

export type Stats = {
  nodes: number
  edges: number
  unresolved_edges: number
  orphans: number
  by_kind: Record<string, number>
  by_tier: Record<string, number>
  by_project: Record<string, number>
}

export type Projection = {
  running: boolean
  started_at: string | null
  finished_at: string | null
  error: string | null
  nodes: number
  edges: number
  unresolved_edges: number
  graph: string
  graph_mtime: string | null
  stale: boolean
}

export type KnowledgeBase = {
  id: string
  name: string
  description: string
  nodes: number
  edges: number
  updated_at: string | null
  created_at: string | null
}

export type GraphNode = {
  id: string
  title: string
  kind: Kind
  tier: Tier
  entity_kind: EntityKind | null
  tags: string[]
  degree: number
  updated_at: string
}

export type GraphEdge = {
  source: string
  target: string
  predicate: Predicate
}

export type KnowledgeGraph = {
  project: string
  nodes: GraphNode[]
  edges: GraphEdge[]
  unresolved_edges: number
}

export type TrashItem = {
  id: string
  title: string
  kind: Kind
  project: string
  deleted_at: string
  reason: string
  actor: string
  trash: string
}

export type ArchivedProject = {
  archive_id: string
  id: string
  name: string
  deleted_at: string
  archived_count: number
  removed_edges: number
}

const projectTrashPath = '/api/v1/kb/trash/projects'

export type Issue = {
  type: 'contradiction' | 'broken_link' | 'orphan' | 'low_confidence' | 'stale'
  target: string | string[]
  created_at: string
}

export type WriteResult = {
  id: string
  revision: string
  commit: string | null
  node?: NodeDetail
}

export type UploadRejectionReason =
  | 'unsupported_type'
  | 'not_utf8'
  | 'empty'
  | 'too_large'
  | 'invalid_name'

export type UploadAccepted = {
  name: string
  sha256: string
  chars: number
}

export type UploadRejected = {
  name: string
  reason: UploadRejectionReason | string
}

export type UploadResult = {
  batch_id: string
  project: string
  accepted: UploadAccepted[]
  rejected: UploadRejected[]
  queued: boolean
}

export type UploadFileStatus = 'queued' | 'processed' | 'failed' | 'missing'

export type UploadBatchFile = {
  name: string
  sha256: string
  status: UploadFileStatus
  /** 仅在重试失败时出现。 */
  attempts?: number
}

export type UploadBatch = {
  batch_id: string
  project: string
  created_at: string
  total: number
  counts: Record<UploadFileStatus, number>
  files: UploadBatchFile[]
}

export class ApiError extends Error {
  readonly status: number
  readonly code: number
  readonly data: unknown

  constructor(status: number, code: number, message: string, data: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.data = data
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init.body && !(init.body instanceof FormData)
        ? { 'Content-Type': 'application/json' }
        : {}),
      ...init.headers,
    },
  })
  const text = await response.text()
  let payload: unknown = null
  try {
    payload = text ? JSON.parse(text) : null
  } catch {
    payload = null
  }
  if (!response.ok) {
    const body = payload as { code?: number; message?: string; data?: unknown } | null
    throw new ApiError(
      response.status,
      body?.code ?? 0,
      body?.message ?? `请求失败：${response.status} ${path}`,
      body?.data ?? null,
    )
  }
  return payload as T
}

const idPath = (id: string) => `/api/v1/kb/nodes/${id.split('/').map(encodeURIComponent).join('/')}`

export type NodeListParams = {
  project?: string
  kind?: string
  tier?: string
  q?: string
  tag?: string
  limit?: number
  offset?: number
}

function queryString(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export type NodeCreatePayload = {
  kind: Kind
  title: string
  body?: string
  project?: string
  tier?: Tier
  tags?: string[]
  entity_kind?: EntityKind
  confidence?: number
  status?: 'open' | 'resolved'
  slug?: string
  actor?: string
}

export type NodeUpdatePayload = {
  expected_revision: string
  title?: string
  body?: string
  tags?: string[]
  tier?: Tier
  confidence?: number
  status?: 'open' | 'resolved'
  superseded_by?: string
  actor?: string
}

export const api = {
  healthz: () =>
    request<{ ok: boolean; knowledge_dir: string; nodes: number; projection: Projection }>(
      '/api/v1/kb/healthz',
    ),
  stats: () => request<Stats>('/api/v1/kb/stats'),
  listNodes: (params: NodeListParams = {}) =>
    request<{ items: NodeSummary[]; total: number; offset: number; limit: number }>(
      `/api/v1/kb/nodes${queryString({ ...params })}`,
    ),
  getNode: (id: string) => request<NodeDetail>(idPath(id)),
  createNode: (payload: NodeCreatePayload) =>
    request<WriteResult>('/api/v1/kb/nodes', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateNode: (id: string, payload: NodeUpdatePayload) =>
    request<WriteResult>(idPath(id), {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  deprecateNode: (id: string, supersededBy: string, reason = '') =>
    request<WriteResult>(`${idPath(id)}/deprecate`, {
      method: 'POST',
      body: JSON.stringify({ superseded_by: supersededBy, reason }),
    }),
  deleteNode: (id: string, revision: string, reason = '') =>
    request<{ id: string; trash: string; removed_edges: number; commit: string | null }>(
      `${idPath(id)}${queryString({ revision, reason })}`,
      { method: 'DELETE' },
    ),
  replaceEdges: (id: string, edges: { predicate: Predicate; target: string }[]) =>
    request<{ id: string; added: number }>(`${idPath(id)}/edges`, {
      method: 'PUT',
      body: JSON.stringify({ edges }),
    }),
  trash: (params: { limit?: number; offset?: number; project?: string; q?: string } = {}) =>
    request<{
      items: TrashItem[]
      total: number
      offset: number
      total_all: number
    }>(`/api/v1/kb/trash${queryString({ ...params })}`),
  restore: (trash: string) =>
    request<{ id: string; revision: string; commit: string | null }>(
      '/api/v1/kb/trash/restore',
      { method: 'POST', body: JSON.stringify({ trash }) },
    ),
  listArchivedProjects: () =>
    request<{ items: ArchivedProject[]; total: number }>(projectTrashPath),
  restoreProject: (archiveId: string) =>
    request<{
      id: string
      archive_id: string
      restored_count: number
      restored_edges: number
      commit: string | null
    }>(`${projectTrashPath}/restore`, {
      method: 'POST',
      body: JSON.stringify({ archive_id: archiveId }),
    }),
  audit: (limit = 200) =>
    request<{ issues: Issue[]; total: number; offset: number; limit: number }>(
      `/api/v1/kb/audit${queryString({ limit })}`,
    ),
  projection: () => request<Projection>('/api/v1/kb/projection'),
  rebuild: () => request<Projection>('/api/v1/kb/rebuild', { method: 'POST' }),
  projects: () =>
    request<{ items: KnowledgeBase[]; total: number }>('/api/v1/kb/projects'),
  createProject: (payload: { id: string; name?: string; description?: string }) =>
    request<KnowledgeBase>('/api/v1/kb/projects', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateProject: (id: string, payload: { name?: string; description?: string }) =>
    request<KnowledgeBase>(`/api/v1/kb/projects/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  /** 归档整个知识库，包括库内节点、元数据和受影响的关系。 */
  deleteProject: (id: string) =>
    request<{
      id: string
      archive_id: string
      archived_count: number
      removed_edges: number
      commit: string | null
    }>(`/api/v1/kb/projects/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  me: () =>
    request<{ authenticated: boolean; user: string | null; avatar_url: string | null }>(
      '/api/v1/kb/me',
    ),
  /** 上传文档进提炼队列；返回 201 只代表「已入队」，抽取由 worker 异步完成。 */
  uploadDocuments: (project: string, files: File[]) => {
    const body = new FormData()
    body.set('project', project)
    for (const file of files) body.append('files', file, file.name)
    return request<UploadResult>('/api/v1/kb/uploads', { method: 'POST', body })
  },
  uploadStatus: (batchId: string) =>
    request<UploadBatch>(`/api/v1/kb/uploads/${encodeURIComponent(batchId)}`),
  graph: (project: string) =>
    request<KnowledgeGraph>(`/api/v1/kb/graph${queryString({ project })}`),
}

export const KINDS: { value: Kind; label: string }[] = [
  { value: 'entity', label: '实体' },
  { value: 'fact', label: '事实' },
  { value: 'decision', label: '决策' },
  { value: 'procedure', label: '流程' },
  { value: 'pitfall', label: '坑' },
  { value: 'preference', label: '偏好' },
  { value: 'event', label: '事件' },
  { value: 'question', label: '问题' },
]

export const TIERS: { value: Tier; label: string }[] = [
  { value: 'canonical', label: '正式' },
  { value: 'candidate', label: '候选' },
  { value: 'deprecated', label: '已废弃' },
]

export const PREDICATES: { value: Predicate; label: string }[] = [
  { value: 'part_of', label: 'part_of' },
  { value: 'depends_on', label: 'depends_on' },
  { value: 'exposes', label: 'exposes' },
  { value: 'runs_on', label: 'runs_on' },
  { value: 'about', label: 'about' },
  { value: 'resolved_by', label: 'resolved_by' },
  { value: 'supersedes', label: 'supersedes' },
  { value: 'contradicts', label: 'contradicts' },
  { value: 'evidenced_by', label: 'evidenced_by' },
  { value: 'related_to', label: 'related_to' },
]

export const ISSUE_LABELS: Record<Issue['type'], string> = {
  contradiction: '矛盾',
  broken_link: '断链',
  orphan: '孤立节点',
  low_confidence: '低置信',
  stale: '陈旧',
}
