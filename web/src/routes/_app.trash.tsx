import { useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArchiveRestore, ChevronLeft, ChevronRight } from 'lucide-react'
import { toast } from 'sonner'
import { ApiError, api, type ArchivedProject, type KnowledgeBase } from '@/lib/api'
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

export const Route = createFileRoute('/_app/trash')({
  component: TrashPage,
})

const PAGE_SIZE = 20
const ALL_PROJECTS = '__all__'

function TrashPage() {
  const queryClient = useQueryClient()
  const [page, setPage] = useState(0)
  const [q, setQ] = useState('')
  const [project, setProject] = useState(ALL_PROJECTS)
  const [qDraft, setQDraft] = useState('')

  const projects = useQuery({ queryKey: ['projects'], queryFn: api.projects })
  const trash = useQuery({
    queryKey: ['trash', page, q, project],
    queryFn: () =>
      api.trash({
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        q: q || undefined,
        project: project === ALL_PROJECTS ? undefined : project,
      }),
    placeholderData: keepPreviousData,
  })

  const items = trash.data?.items ?? []
  const total = trash.data?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const restore = useMutation({
    mutationFn: (key: string) => api.restore(key),
    onSuccess: async (result) => {
      toast.success(`已恢复 ${result.id}`)
      if (page > 0 && items.length === 1 && !trash.isPlaceholderData) {
        setPage(page - 1)
      }
      await queryClient.invalidateQueries()
    },
    onError: (error) => toast.error(error.message),
  })

  const applyFilters = (nextProject: string, nextQ: string) => {
    setProject(nextProject)
    setQ(nextQ)
    setPage(0)
  }

  return (
    <>
      <Header>
        <Search />
        <ThemeSwitch />
      </Header>

      <Main className='flex flex-1 flex-col gap-4'>
        <div>
          <h1 className='text-2xl font-bold tracking-tight'>回收站</h1>
          <p className='text-sm text-muted-foreground'>按整库归档或单节点删除的方式分别恢复。</p>
        </div>

        <ArchivedProjects />

        <Card>
          <CardHeader>
            <CardTitle className='text-base'>已删除节点</CardTitle>
            <CardDescription>单独删除的节点可逐条恢复；关系不会自动恢复。</CardDescription>
          </CardHeader>
          <CardContent>
            <div className='mb-3 flex flex-wrap items-center gap-2'>
              <Select value={project} onValueChange={(value) => applyFilters(value, q)}>
                <SelectTrigger className='w-52'>
                  <SelectValue placeholder='全部知识库' />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_PROJECTS}>全部知识库</SelectItem>
                  {(projects.data?.items ?? []).map((kb: KnowledgeBase) => (
                    <SelectItem key={kb.id} value={kb.id}>
                      {kb.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <form
                className='flex flex-1 gap-2'
                onSubmit={(event) => {
                  event.preventDefault()
                  applyFilters(project, qDraft)
                }}
              >
                <Input
                  value={qDraft}
                  onChange={(event) => setQDraft(event.target.value)}
                  placeholder='按标题或 id 搜索…'
                  className='max-w-xs'
                />
                <Button type='submit' variant='outline' size='sm'>
                  搜索
                </Button>
                {(q || project !== ALL_PROJECTS) && (
                  <Button
                    type='button'
                    variant='ghost'
                    size='sm'
                    onClick={() => {
                      setQDraft('')
                      applyFilters(ALL_PROJECTS, '')
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
                    <TableHead>节点</TableHead>
                    <TableHead>类型</TableHead>
                    <TableHead>删除时间</TableHead>
                    <TableHead>原因</TableHead>
                    <TableHead className='text-end'>操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <TableRow key={item.trash}>
                      <TableCell>
                        <div className='font-medium'>{item.title}</div>
                        <div className='font-mono text-xs text-muted-foreground'>
                          {item.id}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant='outline'>{item.kind}</Badge>
                      </TableCell>
                      <TableCell className='text-xs whitespace-nowrap text-muted-foreground'>
                        {new Date(item.deleted_at).toLocaleString('zh-CN')}
                      </TableCell>
                      <TableCell className='max-w-64 truncate text-sm'>
                        {item.reason || '—'}
                      </TableCell>
                      <TableCell className='text-end'>
                        <Button
                          variant='outline'
                          size='sm'
                          disabled={restore.isPending}
                          onClick={() => restore.mutate(item.trash)}
                        >
                          <ArchiveRestore /> 恢复
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                  {items.length === 0 && (
                    <TableRow>
                      <TableCell
                        colSpan={5}
                        className='h-24 text-center text-sm text-muted-foreground'
                      >
                        {trash.isLoading ? '加载中…' : '回收站是空的'}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>

            <div className='mt-3 flex items-center justify-between'>
              <span className='text-sm text-muted-foreground'>
                {trash.isLoading
                  ? '加载中…'
                  : `共 ${total} 条${q || project !== ALL_PROJECTS ? `（全部 ${trash.data?.total_all ?? total} 条）` : ''}`}
              </span>
              <div className='flex items-center gap-2'>
                <Button
                  variant='outline'
                  size='sm'
                  disabled={page === 0 || trash.isFetching}
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
                  disabled={page >= pageCount - 1 || trash.isFetching}
                  onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                >
                  下一页 <ChevronRight />
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </Main>
    </>
  )
}

function ArchivedProjects() {
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<ArchivedProject | null>(null)
  const archived = useQuery({
    queryKey: ['archived-projects'],
    queryFn: api.listArchivedProjects,
  })
  const restore = useMutation({
    mutationFn: api.restoreProject,
    onSuccess: async (result) => {
      toast.success(`已恢复知识库 ${result.id}`, {
        description: `${result.restored_count} 个节点、${result.restored_edges} 条关系。`,
      })
      setSelected(null)
      await queryClient.invalidateQueries()
    },
  })
  const missing = restore.error instanceof ApiError && restore.error.status === 404
  const conflict = restore.error instanceof ApiError && restore.error.status === 409
  const items = archived.data?.items ?? []

  const openRestore = (item: ArchivedProject) => {
    restore.reset()
    setSelected(item)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className='text-base'>已归档知识库</CardTitle>
        <CardDescription>
          整库恢复会将节点、库信息和归档时移除的关系恢复到原知识库。
          {archived.data && ` 共 ${archived.data.total} 个归档。`}
        </CardDescription>
      </CardHeader>
      <CardContent className='space-y-3'>
        {archived.isError && (
          <div className='flex flex-wrap items-center gap-2'>
            <p role='alert' className='break-words text-sm text-destructive'>
              无法加载已归档知识库：{archived.error.message}
            </p>
            <Button
              variant='outline'
              size='sm'
              disabled={archived.isFetching}
              onClick={() => void archived.refetch()}
            >
              重新加载
            </Button>
          </div>
        )}
        {items.length > 0 ? (
          <div className='rounded-md border'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>知识库</TableHead>
                  <TableHead>归档时间</TableHead>
                  <TableHead>节点</TableHead>
                  <TableHead>关系</TableHead>
                  <TableHead className='text-end'>操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((item) => (
                  <TableRow key={item.archive_id}>
                    <TableCell>
                      <div className='font-medium'>{item.name}</div>
                      <div className='font-mono text-xs text-muted-foreground'>{item.id}</div>
                    </TableCell>
                    <TableCell className='text-xs text-muted-foreground'>
                      {new Date(item.deleted_at).toLocaleString('zh-CN')}
                    </TableCell>
                    <TableCell>{item.archived_count}</TableCell>
                    <TableCell>{item.removed_edges}</TableCell>
                    <TableCell className='text-end'>
                      <Button
                        variant='outline'
                        size='sm'
                        disabled={restore.isPending}
                        aria-label={`恢复知识库 ${item.name}`}
                        onClick={() => openRestore(item)}
                      >
                        <ArchiveRestore /> 恢复整库
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : !archived.isError && (
          <p className='py-4 text-center text-sm text-muted-foreground'>
            {archived.isLoading ? '加载中…' : '没有已归档的知识库'}
          </p>
        )}
      </CardContent>
      <Dialog
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open && !restore.isPending) setSelected(null)
        }}
      >
        <DialogContent>
          {selected && (
            <>
              <DialogHeader>
                <DialogTitle className='break-words'>恢复知识库「{selected.name}」？</DialogTitle>
                <DialogDescription>
                  将恢复到原 ID {selected.id}，包括库信息、{selected.archived_count} 个节点和 {selected.removed_edges} 条关系。
                  如果原 ID 已被占用或关系无法恢复，操作不会覆盖现有内容。
                </DialogDescription>
              </DialogHeader>
              {restore.error && (
                <p role='alert' className='break-words text-sm text-destructive'>
                  恢复失败：{restore.error.message}。
                  {missing
                    ? '该归档可能已被恢复，请刷新列表。'
                    : conflict
                      ? '请根据上述原因处理冲突后重试；如涉及归档损坏或路径异常，请联系管理员。'
                      : '请先刷新列表确认归档状态，再重试；若问题持续，请联系管理员。'}
                </p>
              )}
              <DialogFooter>
                <Button
                  variant='outline'
                  disabled={restore.isPending}
                  onClick={() => setSelected(null)}
                >
                  取消
                </Button>
                {missing ? (
                  <Button onClick={() => {
                    setSelected(null)
                    void queryClient.invalidateQueries()
                  }}>
                    刷新列表
                  </Button>
                ) : (
                  <Button
                    disabled={restore.isPending}
                    onClick={() => restore.mutate(selected.archive_id)}
                  >
                    {restore.isPending ? '恢复中…' : '确认恢复'}
                  </Button>
                )}
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </Card>
  )
}
