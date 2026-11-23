import { useEffect, useState } from 'react'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDownLeft, ArrowUpRight, ChevronRight, Database, Plus, Save, Trash2, XCircle } from 'lucide-react'
import { toast } from 'sonner'
import {
  PREDICATES,
  TIERS,
  api,
  type Predicate,
  type Tier,
} from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Textarea } from '@/components/ui/textarea'
import { BackButton } from '@/components/layout/back-button'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export const Route = createFileRoute('/_app/nodes/$')({
  component: NodeDetailPage,
})

function NodeDetailPage() {
  const { _splat } = Route.useParams()
  const nodeId = _splat ?? ''
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const node = useQuery({
    queryKey: ['node', nodeId],
    queryFn: () => api.getNode(nodeId),
  })

  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [tags, setTags] = useState('')
  const [tier, setTier] = useState<Tier>('candidate')
  const [confidence, setConfidence] = useState('')
  const [revision, setRevision] = useState('')

  useEffect(() => {
    if (!node.data) return
    setTitle(node.data.frontmatter.title)
    setBody(node.data.body)
    setTags(node.data.frontmatter.tags.join(', '))
    setTier(node.data.frontmatter.tier)
    setConfidence(
      node.data.frontmatter.confidence == null
        ? ''
        : String(node.data.frontmatter.confidence),
    )
    setRevision(node.data.revision)
  }, [node.data])

  const refresh = async () => {
    await queryClient.invalidateQueries()
  }

  const save = useMutation({
    mutationFn: () =>
      api.updateNode(nodeId, {
        expected_revision: revision,
        title: title.trim(),
        body,
        tags: tags
          .split(',')
          .map((tag) => tag.trim())
          .filter(Boolean),
        tier,
        ...(confidence.trim() ? { confidence: Number(confidence) } : {}),
      }),
    onSuccess: async (result) => {
      setRevision(result.revision)
      toast.success(result.commit ? `已保存（${result.commit}）` : '已保存')
      await refresh()
    },
    onError: (error) => toast.error(error.message),
  })

  if (node.isLoading) {
    return (
      <div className='space-y-2 p-8'>
        <BackButton fallbackTo='/nodes' />
        <p className='text-sm text-muted-foreground'>加载中…</p>
      </div>
    )
  }
  if (node.isError || !node.data) {
    return (
      <div className='space-y-3 p-8'>
        <BackButton fallbackTo='/nodes' />
        <p className='text-sm text-destructive'>{node.error?.message ?? '节点不存在'}</p>
        <Button asChild variant='outline'>
          <Link to='/nodes'>返回列表</Link>
        </Button>
      </div>
    )
  }

  const detail = node.data
  const frontmatter = detail.frontmatter

  return (
    <>
      <Header>
        <Search />
        <ThemeSwitch />
      </Header>

      <Main className='flex flex-1 flex-col gap-4'>
        <div className='space-y-1'>
          <div className='flex flex-wrap items-center gap-1 text-xs text-muted-foreground'>
            <BackButton fallbackTo={`/kb/${frontmatter.project}`} />
            <Link to='/' className='hover:underline'>
              知识库
            </Link>
            <ChevronRight className='size-3' />
            <Link
              to='/kb/$project'
              params={{ project: frontmatter.project }}
              className='font-mono hover:underline'
            >
              {frontmatter.project}
            </Link>
            <ChevronRight className='size-3' />
            <Link
              to='/kb/$project/nodes'
              params={{ project: frontmatter.project }}
              className='hover:underline'
            >
              节点
            </Link>
            <ChevronRight className='size-3' />
            <span className='truncate'>{frontmatter.title}</span>
          </div>
          <div className='flex flex-wrap items-center gap-2'>
            <Badge variant='outline'>{frontmatter.kind}</Badge>
            <Badge variant={frontmatter.tier === 'canonical' ? 'default' : 'secondary'}>
              {frontmatter.tier}
            </Badge>
            {frontmatter.entity_kind && (
              <Badge variant='outline'>{frontmatter.entity_kind}</Badge>
            )}
            <Button asChild variant='ghost' size='sm' className='h-6 px-2 text-xs'>
              <Link
                to='/kb/$project'
                params={{ project: frontmatter.project }}
                className='font-mono'
              >
                <Database className='size-3' /> {frontmatter.project}
              </Link>
            </Button>
            <span className='font-mono text-xs text-muted-foreground'>{detail.id}</span>
          </div>
          <h1 className='text-2xl font-bold tracking-tight'>{frontmatter.title}</h1>
          <p className='text-xs text-muted-foreground'>
            创建 {new Date(frontmatter.created_at).toLocaleString('zh-CN')} · 更新{' '}
            {new Date(frontmatter.updated_at).toLocaleString('zh-CN')} · 修订号{' '}
            <span className='font-mono'>{detail.revision}</span>
          </p>
          {frontmatter.superseded_by && (
            <p className='text-sm'>
              已被{' '}
              <Link
                to='/nodes/$'
                params={{ _splat: frontmatter.superseded_by }}
                className='underline'
              >
                {frontmatter.superseded_by}
              </Link>{' '}
              取代
            </p>
          )}
          {!frontmatter.superseded_by && frontmatter.deprecated_reason && (
            <p className='text-sm'>废弃原因：{frontmatter.deprecated_reason}</p>
          )}
        </div>

        <div className='grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]'>
          <Card>
            <CardHeader className='flex-row items-center justify-between'>
              <CardTitle className='text-base'>编辑</CardTitle>
              <div className='flex gap-2'>
                <DeprecateDialog nodeId={detail.id} onDone={refresh} />
                <DeleteDialog
                  nodeId={detail.id}
                  revision={revision}
                  onDone={async () => {
                    await refresh()
                    await navigate({ to: '/nodes' })
                  }}
                />
              </div>
            </CardHeader>
            <CardContent className='space-y-3'>
              <div className='space-y-1.5'>
                <Label>标题</Label>
                <Input value={title} onChange={(event) => setTitle(event.target.value)} />
              </div>
              <div className='grid gap-3 sm:grid-cols-3'>
                <div className='space-y-1.5'>
                  <Label>层级</Label>
                  <Select value={tier} onValueChange={(value) => setTier(value as Tier)}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {TIERS.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className='space-y-1.5'>
                  <Label>置信度（0-1）</Label>
                  <Input
                    value={confidence}
                    onChange={(event) => setConfidence(event.target.value)}
                    placeholder='可留空'
                  />
                </div>
                <div className='space-y-1.5'>
                  <Label>标签</Label>
                  <Input value={tags} onChange={(event) => setTags(event.target.value)} />
                </div>
              </div>
              <div className='space-y-1.5'>
                <Label>正文（markdown）</Label>
                <Textarea
                  rows={18}
                  className='font-mono text-sm'
                  value={body}
                  onChange={(event) => setBody(event.target.value)}
                />
              </div>
              <div className='flex items-center justify-between'>
                <span className='text-xs text-muted-foreground'>
                  {detail.truncated && '正文超过 8192 字符，编辑会截断——请用 CLI 修改。'}
                </span>
                <Button onClick={() => save.mutate()} disabled={save.isPending}>
                  <Save /> {save.isPending ? '保存中…' : '保存'}
                </Button>
              </div>
            </CardContent>
          </Card>

          <div className='space-y-4'>
            <Card>
              <CardHeader>
                <CardTitle className='text-base'>出处</CardTitle>
              </CardHeader>
              <CardContent className='space-y-2 text-sm'>
                {frontmatter.source.length === 0 && (
                  <p className='text-muted-foreground'>无来源记录</p>
                )}
                {frontmatter.source.map((ref) => (
                  <div key={`${ref.type}:${ref.ref}`} className='space-y-0.5'>
                    <div className='font-mono text-xs'>{ref.ref}</div>
                    <div className='text-xs text-muted-foreground'>
                      {ref.type}
                      {ref.captured_at &&
                        ` · ${new Date(ref.captured_at).toLocaleString('zh-CN')}`}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className='text-base'>关系</CardTitle>
              </CardHeader>
              <CardContent className='space-y-3'>
                <div className='space-y-1'>
                  <div className='flex items-center gap-1 text-xs text-muted-foreground'>
                    <ArrowUpRight className='size-3' /> 出边
                  </div>
                  {detail.edges.out.map((edge) => (
                    <Link
                      key={`${edge.predicate}:${edge.target}`}
                      to='/nodes/$'
                      params={{ _splat: edge.target }}
                      className='block truncate rounded px-1 py-0.5 text-sm hover:bg-accent'
                    >
                      <span className='font-mono text-xs text-muted-foreground'>
                        {edge.predicate}
                      </span>{' '}
                      → {edge.target}
                    </Link>
                  ))}
                  {detail.edges.out.length === 0 && (
                    <p className='text-xs text-muted-foreground'>无</p>
                  )}
                </div>
                <Separator />
                <div className='space-y-1'>
                  <div className='flex items-center gap-1 text-xs text-muted-foreground'>
                    <ArrowDownLeft className='size-3' /> 入边
                  </div>
                  {detail.edges.in.map((edge) => (
                    <Link
                      key={`${edge.predicate}:${edge.source}`}
                      to='/nodes/$'
                      params={{ _splat: edge.source }}
                      className='block truncate rounded px-1 py-0.5 text-sm hover:bg-accent'
                    >
                      {edge.source}{' '}
                      <span className='font-mono text-xs text-muted-foreground'>
                        {edge.predicate} →
                      </span>
                    </Link>
                  ))}
                  {detail.edges.in.length === 0 && (
                    <p className='text-xs text-muted-foreground'>无</p>
                  )}
                </div>
                <Separator />
                <EdgesEditor
                  nodeId={detail.id}
                  initial={detail.edges.out}
                  onSaved={refresh}
                />
              </CardContent>
            </Card>
          </div>
        </div>
      </Main>
    </>
  )
}

function EdgesEditor({
  nodeId,
  initial,
  onSaved,
}: {
  nodeId: string
  initial: { predicate: Predicate; target: string }[]
  onSaved: () => Promise<void>
}) {
  const [rows, setRows] = useState(initial)

  const save = useMutation({
    mutationFn: () => api.replaceEdges(nodeId, rows.filter((row) => row.target.trim())),
    onSuccess: async (result) => {
      toast.success(`出边已更新：${result.added} 条`)
      await onSaved()
    },
    onError: (error) => toast.error(error.message),
  })

  return (
    <div className='space-y-2'>
      <div className='text-xs text-muted-foreground'>编辑出边（保存会替换该节点的全部出边）</div>
      {rows.map((row, index) => (
        <div key={index} className='flex gap-1.5'>
          <Select
            value={row.predicate}
            onValueChange={(value) => {
              const next = [...rows]
              next[index] = { ...row, predicate: value as Predicate }
              setRows(next)
            }}
          >
            <SelectTrigger className='w-36 shrink-0'>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PREDICATES.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            value={row.target}
            placeholder='目标节点 id，如 memhub/fact/xxx'
            onChange={(event) => {
              const next = [...rows]
              next[index] = { ...row, target: event.target.value }
              setRows(next)
            }}
          />
          <Button
            variant='ghost'
            size='icon'
            onClick={() => setRows(rows.filter((_, i) => i !== index))}
          >
            <XCircle />
          </Button>
        </div>
      ))}
      <div className='flex gap-2'>
        <Button
          variant='outline'
          size='sm'
          onClick={() => setRows([...rows, { predicate: 'related_to', target: '' }])}
        >
          <Plus /> 加一条
        </Button>
        <Button size='sm' onClick={() => save.mutate()} disabled={save.isPending}>
          保存出边
        </Button>
      </div>
    </div>
  )
}

function DeprecateDialog({ nodeId, onDone }: { nodeId: string; onDone: () => Promise<void> }) {
  const [open, setOpen] = useState(false)
  const [target, setTarget] = useState('')
  const [reason, setReason] = useState('')
  const deprecate = useMutation({
    mutationFn: () => api.deprecateNode(nodeId, target.trim(), reason.trim()),
    onSuccess: async () => {
      toast.success('已标记为废弃')
      setOpen(false)
      await onDone()
    },
    onError: (error) => toast.error(error.message),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant='outline' size='sm'>
          废弃
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>标记为已废弃</DialogTitle>
          <DialogDescription>
            废弃不删除文件：节点保留，被替代关系写进 frontmatter，废弃原因追加到正文末尾。
          </DialogDescription>
        </DialogHeader>
        <div className='space-y-3'>
          <div className='space-y-1.5'>
            <Label>替代节点 id</Label>
            <Input
              value={target}
              onChange={(event) => setTarget(event.target.value)}
              placeholder='memhub/fact/new-answer'
            />
          </div>
          <div className='space-y-1.5'>
            <Label>原因</Label>
            <Textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button
            disabled={!target.trim() || deprecate.isPending}
            onClick={() => deprecate.mutate()}
          >
            确认废弃
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function DeleteDialog({
  nodeId,
  revision,
  onDone,
}: {
  nodeId: string
  revision: string
  onDone: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const remove = useMutation({
    mutationFn: () => api.deleteNode(nodeId, revision, reason.trim()),
    onSuccess: async (result) => {
      toast.success(`已归档到回收站（同时移除 ${result.removed_edges} 条边）`)
      setOpen(false)
      await onDone()
    },
    onError: (error) => toast.error(error.message),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant='destructive' size='sm'>
          <Trash2 /> 删除
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>删除这个节点？</DialogTitle>
          <DialogDescription>
            文件会移入 `_trash/`，并移除与它相连的边；可在「回收站」恢复文件本身，
            但边需要重新编辑。删除前建议先考虑「废弃」。
          </DialogDescription>
        </DialogHeader>
        <div className='space-y-1.5'>
          <Label>原因（写在回收站记录里）</Label>
          <Textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} />
        </div>
        <DialogFooter>
          <Button variant='destructive' onClick={() => remove.mutate()} disabled={remove.isPending}>
            确认删除
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
