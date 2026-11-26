import { useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Ban, ChevronLeft, ChevronRight, RotateCcw } from 'lucide-react'
import { toast } from 'sonner'
import {
  api,
  type MemoryCandidate,
  type MemoryCandidateStatus,
  type MemoryEntry,
  type MemorySnapshot,
  type MemorySnapshotStatus,
  type MemoryStatus,
} from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export const Route = createFileRoute('/_app/memories')({
  component: MemoriesPage,
})

const PAGE_SIZE = 20

const ENTRY_STATUS_LABELS: Record<MemoryStatus, string> = {
  active: '生效',
  deprecated: '已废弃',
}

const CANDIDATE_STATUS_LABELS: Record<MemoryCandidateStatus, string> = {
  pending: '待处理',
  conflict: '冲突',
  promoted: '已提升',
}

const SNAPSHOT_STATUS_LABELS: Record<MemorySnapshotStatus, string> = {
  published: '已发布',
  superseded: '已被取代',
  disabled: '已停用',
}

function formatTime(value: string | null): string {
  return value ? new Date(value).toLocaleString('zh-CN') : '—'
}

function formatConfidence(value: number): string {
  return `${Math.round(value * 100)}%`
}

function MemoriesPage() {
  const queryClient = useQueryClient()

  // 摘要只取总数，用 limit=1 避免把整页数据拉回来。
  const activeCount = useQuery({
    queryKey: ['memories', 'active', 'count'],
    queryFn: () => api.memories({ status: 'active', limit: 1 }),
    placeholderData: keepPreviousData,
  })
  const deprecatedCount = useQuery({
    queryKey: ['memories', 'deprecated', 'count'],
    queryFn: () => api.memories({ status: 'deprecated', limit: 1 }),
    placeholderData: keepPreviousData,
  })
  const pendingCandidates = useQuery({
    queryKey: ['memory-candidates', 'pending', 'count'],
    queryFn: () => api.memoryCandidates({ status: 'pending', limit: 1 }),
    placeholderData: keepPreviousData,
  })
  const snapshots = useQuery({
    queryKey: ['memory-snapshots'],
    queryFn: () => api.memorySnapshots(),
    placeholderData: keepPreviousData,
  })

  const snapshotItems = snapshots.data?.items ?? []
  const current = snapshotItems.find((item) => item.status === 'published')

  return (
    <>
      <Header>
        <Search />
        <ThemeSwitch />
      </Header>

      <Main className='flex flex-1 flex-col gap-4'>
        <div>
          <h1 className='text-2xl font-bold tracking-tight'>长期记忆</h1>
          <p className='text-sm text-muted-foreground'>
            跨项目聚合出的判断与归一化准则。抽取只注入当前快照，不读写本条页面以外的证据正文。
          </p>
        </div>

        <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-4'>
          <SummaryCard label='生效条目' value={activeCount.data?.total} />
          <SummaryCard label='已废弃条目' value={deprecatedCount.data?.total} />
          <SummaryCard label='待处理候选' value={pendingCandidates.data?.total} />
          <SummaryCard
            label='当前快照'
            value={current ? `v${current.version}` : snapshots.isLoading ? undefined : '无'}
          />
        </div>

        <EntriesCard />
        <CandidatesCard />
        <SnapshotsCard
          items={snapshotItems}
          loading={snapshots.isLoading}
          error={snapshots.isError ? snapshots.error.message : null}
          onReload={() => void snapshots.refetch()}
          onChanged={() => void queryClient.invalidateQueries()}
        />
      </Main>
    </>
  )
}

function SummaryCard({ label, value }: { label: string; value: number | string | undefined }) {
  return (
    <Card>
      <CardHeader className='pb-2'>
        <CardDescription>{label}</CardDescription>
        <CardTitle className='text-2xl'>{value ?? '—'}</CardTitle>
      </CardHeader>
    </Card>
  )
}

function EntriesCard() {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<MemoryStatus | 'all'>('active')
  const [q, setQ] = useState('')
  const [qDraft, setQDraft] = useState('')
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<MemoryEntry | null>(null)
  const [reason, setReason] = useState('')

  const entries = useQuery({
    queryKey: ['memories', status, q, page],
    queryFn: () =>
      api.memories({
        status,
        q: q || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    placeholderData: keepPreviousData,
  })

  const deprecate = useMutation({
    mutationFn: (entry: MemoryEntry) =>
      api.deprecateMemory(entry.slug, {
        expected_revision: entry.revision,
        reason: reason.trim(),
      }),
    onSuccess: async (entry) => {
      toast.success(`已废弃 ${entry.slug}`)
      setSelected(null)
      setReason('')
      await queryClient.invalidateQueries()
    },
    onError: (error) => toast.error(error.message),
  })

  const items = entries.data?.items ?? []
  const total = entries.data?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const applyFilters = (nextStatus: MemoryStatus | 'all', nextQ: string) => {
    setStatus(nextStatus)
    setQ(nextQ)
    setPage(0)
  }

  const openDeprecate = (entry: MemoryEntry) => {
    deprecate.reset()
    setReason('')
    setSelected(entry)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className='text-base'>记忆条目</CardTitle>
        <CardDescription>只有生效条目会进入快照；废弃只改状态，保留修订历史。</CardDescription>
      </CardHeader>
      <CardContent>
        <div className='mb-3 flex flex-wrap items-center gap-2'>
          <Select value={status} onValueChange={(value) => applyFilters(value as MemoryStatus | 'all', q)}>
            <SelectTrigger className='w-36'>
              <SelectValue placeholder='全部状态' />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value='active'>生效</SelectItem>
              <SelectItem value='deprecated'>已废弃</SelectItem>
              <SelectItem value='all'>全部</SelectItem>
            </SelectContent>
          </Select>
          <form
            className='flex flex-1 gap-2'
            onSubmit={(event) => {
              event.preventDefault()
              applyFilters(status, qDraft)
            }}
          >
            <Input
              value={qDraft}
              onChange={(event) => setQDraft(event.target.value)}
              placeholder='按标题或结论搜索…'
              className='max-w-xs'
            />
            <Button type='submit' variant='outline' size='sm'>
              搜索
            </Button>
            {(q || status !== 'active') && (
              <Button
                type='button'
                variant='ghost'
                size='sm'
                onClick={() => {
                  setQDraft('')
                  applyFilters('active', '')
                }}
              >
                清除
              </Button>
            )}
          </form>
        </div>

        <div className='overflow-x-auto rounded-md border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>slug</TableHead>
                <TableHead>标题</TableHead>
                <TableHead>结论</TableHead>
                <TableHead className='text-end'>置信度</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>更新时间</TableHead>
                <TableHead className='text-end'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.slug}>
                  <TableCell className='font-mono text-xs'>{item.slug}</TableCell>
                  <TableCell className='max-w-40 truncate font-medium' title={item.title}>
                    {item.title}
                  </TableCell>
                  <TableCell className='max-w-80 truncate text-sm' title={item.conclusion}>
                    {item.conclusion}
                  </TableCell>
                  <TableCell className='text-end font-mono text-xs'>
                    {formatConfidence(item.confidence)}
                  </TableCell>
                  <TableCell>
                    <Badge variant={item.status === 'active' ? 'secondary' : 'outline'}>
                      {ENTRY_STATUS_LABELS[item.status]}
                    </Badge>
                  </TableCell>
                  <TableCell className='text-xs whitespace-nowrap text-muted-foreground'>
                    {formatTime(item.updated_at)}
                  </TableCell>
                  <TableCell className='text-end'>
                    {item.status === 'active' && (
                      <Button
                        variant='outline'
                        size='sm'
                        disabled={deprecate.isPending}
                        aria-label={`废弃记忆 ${item.slug}`}
                        onClick={() => openDeprecate(item)}
                      >
                        <Ban /> 废弃
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {items.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={7}
                    className='h-24 text-center text-sm text-muted-foreground'
                  >
                    {entries.isLoading
                      ? '加载中…'
                      : entries.isError
                        ? `加载失败：${entries.error.message}`
                        : '没有符合条件的记忆条目。聚合任务达到门槛后才会写条目。'}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>

        <div className='mt-3 flex items-center justify-between'>
          <span className='text-sm text-muted-foreground'>
            {entries.isLoading ? '加载中…' : `共 ${total} 条`}
          </span>
          <div className='flex items-center gap-2'>
            <Button
              variant='outline'
              size='sm'
              disabled={page === 0 || entries.isFetching}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              <ChevronLeft /> 上一页
            </Button>
            <span className='text-sm text-muted-foreground'>
              {page + 1} / {pageCount}
            </span>
            <Button
              variant='outline'
              size='sm'
              disabled={page + 1 >= pageCount || entries.isFetching}
              onClick={() => setPage((p) => p + 1)}
            >
              下一页 <ChevronRight />
            </Button>
          </div>
        </div>

        <Dialog
          open={selected !== null}
          onOpenChange={(open) => {
            if (!open && !deprecate.isPending) setSelected(null)
          }}
        >
          <DialogContent>
            {selected && (
              <>
                <DialogHeader>
                  <DialogTitle className='break-words'>废弃记忆「{selected.slug}」？</DialogTitle>
                  <DialogDescription>
                    废弃后该条目不进入后续快照，聚合也不会复活它。原因会写入修订历史。
                  </DialogDescription>
                </DialogHeader>
                <Input
                  autoFocus
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder='废弃原因（必填）'
                  aria-label='废弃原因'
                />
                {deprecate.error && (
                  <p role='alert' className='break-words text-sm text-destructive'>
                    废弃失败：{deprecate.error.message}
                  </p>
                )}
                <DialogFooter>
                  <Button
                    variant='outline'
                    disabled={deprecate.isPending}
                    onClick={() => setSelected(null)}
                  >
                    取消
                  </Button>
                  <Button
                    variant='destructive'
                    disabled={deprecate.isPending || !reason.trim()}
                    onClick={() => deprecate.mutate(selected)}
                  >
                    {deprecate.isPending ? '废弃中…' : '确认废弃'}
                  </Button>
                </DialogFooter>
              </>
            )}
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  )
}

function CandidatesCard() {
  const [status, setStatus] = useState<MemoryCandidateStatus | 'all'>('pending')
  const candidates = useQuery({
    queryKey: ['memory-candidates', status],
    queryFn: () => api.memoryCandidates({ status }),
    placeholderData: keepPreviousData,
  })

  const items = candidates.data?.items ?? []

  return (
    <Card>
      <CardHeader>
        <CardTitle className='text-base'>聚合候选</CardTitle>
        <CardDescription>
          证据不足或与现有条目冲突时只留候选，不会自动写入条目。候选本期只读。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className='mb-3 flex flex-wrap items-center gap-2'>
          <Select
            value={status}
            onValueChange={(value) => setStatus(value as MemoryCandidateStatus | 'all')}
          >
            <SelectTrigger className='w-36'>
              <SelectValue placeholder='待处理' />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value='pending'>待处理</SelectItem>
              <SelectItem value='conflict'>冲突</SelectItem>
              <SelectItem value='all'>全部</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className='overflow-x-auto rounded-md border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>slug</TableHead>
                <TableHead>结论</TableHead>
                <TableHead className='text-end'>会话数</TableHead>
                <TableHead className='text-end'>项目数</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>原因</TableHead>
                <TableHead>最近出现</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <CandidateRow key={item.id} item={item} />
              ))}
              {items.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={7}
                    className='h-24 text-center text-sm text-muted-foreground'
                  >
                    {candidates.isLoading
                      ? '加载中…'
                      : candidates.isError
                        ? `加载失败：${candidates.error.message}`
                        : '没有候选。'}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

function CandidateRow({ item }: { item: MemoryCandidate }) {
  const conflict = item.status === 'conflict'
  return (
    <TableRow className={conflict ? 'bg-destructive/5' : undefined}>
      <TableCell className='font-mono text-xs'>{item.slug}</TableCell>
      <TableCell className='max-w-80 truncate text-sm' title={item.conclusion}>
        {item.conclusion}
      </TableCell>
      <TableCell className='text-end font-mono text-xs'>{item.session_count}</TableCell>
      <TableCell className='text-end font-mono text-xs'>{item.project_count}</TableCell>
      <TableCell>
        <Badge variant={conflict ? 'destructive' : 'outline'}>
          {CANDIDATE_STATUS_LABELS[item.status]}
        </Badge>
      </TableCell>
      <TableCell className='max-w-64 truncate text-xs text-muted-foreground' title={item.reason}>
        {item.reason || '—'}
      </TableCell>
      <TableCell className='text-xs whitespace-nowrap text-muted-foreground'>
        {formatTime(item.last_seen_at)}
      </TableCell>
    </TableRow>
  )
}

type SnapshotAction =
  | { kind: 'publish' }
  | { kind: 'activate'; version: number }
  | { kind: 'disable'; version: number }

function SnapshotsCard({
  items,
  loading,
  error,
  onReload,
  onChanged,
}: {
  items: MemorySnapshot[]
  loading: boolean
  error: string | null
  onReload: () => void
  onChanged: () => void
}) {
  const action = useMutation({
    mutationFn: (next: SnapshotAction) => {
      switch (next.kind) {
        case 'publish':
          return api.publishMemorySnapshot()
        case 'activate':
          return api.activateMemorySnapshot(next.version)
        case 'disable':
          return api.disableMemorySnapshot(next.version)
      }
    },
    onSuccess: (snapshot, next) => {
      const done =
        next.kind === 'publish'
          ? `已发布快照 v${snapshot.version}`
          : next.kind === 'activate'
            ? `已回滚到快照 v${snapshot.version}`
            : `已停用快照 v${snapshot.version}`
      toast.success(done)
      onChanged()
    },
    onError: (cause) => toast.error(cause.message),
  })

  const publish = () => {
    if (
      !window.confirm('把当前全部生效条目冻结为新的记忆快照？当前已发布的快照会被取代。')
    ) {
      return
    }
    action.mutate({ kind: 'publish' })
  }

  const activate = (version: number) => {
    if (!window.confirm(`回滚到快照 v${version}？当前快照会被取代，worker 需重启后生效。`)) {
      return
    }
    action.mutate({ kind: 'activate', version })
  }

  const disable = (version: number) => {
    if (!window.confirm(`停用快照 v${version}？停用后会话抽取不再注入长期记忆。`)) {
      return
    }
    action.mutate({ kind: 'disable', version })
  }

  return (
    <Card>
      <CardHeader>
        <div className='flex flex-wrap items-start justify-between gap-2'>
          <div>
            <CardTitle className='text-base'>记忆快照</CardTitle>
            <CardDescription>
              抽取只读取已发布快照；回滚或停用后运行中的 worker 需重启才会换用新版本。
            </CardDescription>
          </div>
          <Button size='sm' disabled={action.isPending} onClick={publish}>
            发布新快照
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {(error || action.error) && (
          <p role='alert' className='mb-3 break-words text-sm text-destructive'>
            操作失败：{action.error?.message ?? error}
            {error && (
              <Button variant='outline' size='sm' className='ml-2' onClick={onReload}>
                重新加载
              </Button>
            )}
          </p>
        )}

        <div className='overflow-x-auto rounded-md border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>版本</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className='text-end'>条目数</TableHead>
                <TableHead>发布时间</TableHead>
                <TableHead>备注</TableHead>
                <TableHead className='text-end'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.version}>
                  <TableCell className='font-mono text-xs'>v{item.version}</TableCell>
                  <TableCell>
                    <Badge variant={item.status === 'published' ? 'secondary' : 'outline'}>
                      {SNAPSHOT_STATUS_LABELS[item.status]}
                    </Badge>
                  </TableCell>
                  <TableCell className='text-end font-mono text-xs'>{item.item_count}</TableCell>
                  <TableCell className='text-xs whitespace-nowrap text-muted-foreground'>
                    {formatTime(item.published_at)}
                  </TableCell>
                  <TableCell
                    className='max-w-56 truncate text-xs text-muted-foreground'
                    title={item.note}
                  >
                    {item.note || '—'}
                  </TableCell>
                  <TableCell className='text-end'>
                    {item.status === 'published' ? (
                      <Button
                        variant='outline'
                        size='sm'
                        disabled={action.isPending}
                        onClick={() => disable(item.version)}
                      >
                        <Ban /> 停用
                      </Button>
                    ) : item.status === 'superseded' ? (
                      <Button
                        variant='outline'
                        size='sm'
                        disabled={action.isPending}
                        onClick={() => activate(item.version)}
                      >
                        <RotateCcw /> 回滚
                      </Button>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
              {items.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={6}
                    className='h-24 text-center text-sm text-muted-foreground'
                  >
                    {loading ? '加载中…' : '还没有发布过快照，抽取不会注入长期记忆。'}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}
