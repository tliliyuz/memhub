import { useState } from 'react'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  BookOpenText,
  Database,
  GitFork,
  Network,
  Plus,
  RefreshCw,
} from 'lucide-react'
import { toast } from 'sonner'
import { api, type KnowledgeBase } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
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
import { Textarea } from '@/components/ui/textarea'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export const Route = createFileRoute('/_app/')({
  component: KnowledgeBaseIndex,
})

function KnowledgeBaseIndex() {
  const queryClient = useQueryClient()
  const projects = useQuery({ queryKey: ['projects'], queryFn: api.projects })
  const projection = useQuery({ queryKey: ['projection'], queryFn: api.projection })

  const rebuild = useMutation({
    mutationFn: api.rebuild,
    onSuccess: async (result) => {
      toast.success(`投影已重建：${result.nodes} 节点 / ${result.edges} 边`)
      await queryClient.invalidateQueries()
    },
    onError: (error) => toast.error(error.message),
  })

  const items = projects.data?.items ?? []
  const nodeTotal = items.reduce((sum, item) => sum + item.nodes, 0)
  const edgeTotal = items.reduce((sum, item) => sum + item.edges, 0)

  return (
    <>
      <Header>
        <Search />
        <ThemeSwitch />
      </Header>

      <Main className='flex flex-1 flex-col gap-4'>
        <div className='flex flex-wrap items-end justify-between gap-3'>
          <div>
            <h1 className='text-2xl font-bold tracking-tight'>知识库</h1>
            <p className='text-sm text-muted-foreground'>
              每个知识库是真源里的一个隔离目录，节点、边、图谱都只属于它自己。
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <Button asChild variant='outline' size='sm'>
              <Link to='/nodes'>
                <BookOpenText /> 全部节点
              </Link>
            </Button>
            <Button asChild variant='outline' size='sm'>
              <Link to='/graph'>
                <Network /> 全局图谱
              </Link>
            </Button>
            <CreateKbDialog />
          </div>
        </div>

        {projection.data && (projection.data.stale || projection.data.error) && (
          <Card className='border-amber-500/40 bg-amber-500/5'>
            <CardContent className='flex flex-wrap items-center gap-3 py-3'>
              <AlertTriangle className='size-4 text-amber-600' />
              <div className='flex-1 text-xs'>
                {projection.data.error
                  ? `semantica 投影上次重建失败：${projection.data.error}`
                  : '真源有更新，semantica 投影（kg.json）已过期'}
                <span className='text-muted-foreground'>
                  {' '}
                  —— 它只供 MCP / explorer 使用，管理台的图谱直接用真源。
                </span>
              </div>
              <Button
                size='sm'
                variant='outline'
                onClick={() => rebuild.mutate()}
                disabled={rebuild.isPending || projection.data.running}
              >
                <RefreshCw className={rebuild.isPending ? 'animate-spin' : ''} />
                重建投影
              </Button>
            </CardContent>
          </Card>
        )}

        {projects.isError && (
          <Card>
            <CardContent className='py-10 text-center text-sm text-destructive'>
              {projects.error.message}
            </CardContent>
          </Card>
        )}

        <div className='grid gap-3 sm:grid-cols-2 xl:grid-cols-3'>
          {items.map((kb) => (
            <KbCard key={kb.id} kb={kb} />
          ))}
          {!projects.isLoading && items.length === 0 && (
            <Card className='border-dashed sm:col-span-2 xl:col-span-3'>
              <CardContent className='flex flex-col items-center gap-2 py-12 text-sm text-muted-foreground'>
                <Database className='size-8 opacity-40' />
                <span>还没有知识库。新建一个，或者把已有 markdown 目录放进 knowledge/。</span>
              </CardContent>
            </Card>
          )}
        </div>

        <p className='text-xs text-muted-foreground'>
          共 {items.length} 个知识库 · {nodeTotal} 个节点 · {edgeTotal} 条边
        </p>
      </Main>
    </>
  )
}

function KbCard({ kb }: { kb: KnowledgeBase }) {
  return (
    <Card className='flex flex-col'>
      <CardHeader className='pb-2'>
        <div className='flex items-start justify-between gap-2'>
          <CardTitle className='min-w-0 text-base'>
            <Link
              to='/kb/$project'
              params={{ project: kb.id }}
              className='hover:underline'
            >
              {kb.name}
            </Link>
          </CardTitle>
          <Badge variant='outline' className='shrink-0 font-mono text-[10px]'>
            {kb.id}
          </Badge>
        </div>
        <CardDescription className='line-clamp-2 min-h-8 text-xs'>
          {kb.description || '没有描述'}
        </CardDescription>
      </CardHeader>
      <CardContent className='mt-auto space-y-3'>
        <div className='flex items-center gap-4 text-xs text-muted-foreground'>
          <span>
            <span className='font-medium text-foreground'>{kb.nodes}</span> 节点
          </span>
          <span>
            <span className='font-medium text-foreground'>{kb.edges}</span> 条边
          </span>
          <span className='ms-auto text-[11px]'>
            {kb.updated_at
              ? new Date(kb.updated_at).toLocaleDateString('zh-CN')
              : '—'}
          </span>
        </div>
        <div className='flex items-center gap-1'>
          <Button asChild variant='outline' size='sm' className='flex-1'>
            <Link to='/kb/$project' params={{ project: kb.id }}>
              <Database /> 概览
            </Link>
          </Button>
          <Button asChild variant='outline' size='sm' className='flex-1'>
            <Link to='/kb/$project/nodes' params={{ project: kb.id }}>
              <BookOpenText /> 节点
            </Link>
          </Button>
          <Button asChild variant='outline' size='sm' className='flex-1'>
            <Link to='/kb/$project/graph' params={{ project: kb.id }}>
              <GitFork /> 图谱
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function CreateKbDialog() {
  const [open, setOpen] = useState(false)
  const [id, setId] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const valid = /^[a-z0-9][a-z0-9._-]{0,63}$/.test(id.trim())

  const create = useMutation({
    mutationFn: () =>
      api.createProject({
        id: id.trim(),
        name: name.trim() || id.trim(),
        description: description.trim(),
      }),
    onSuccess: async (result) => {
      toast.success(`已创建知识库 ${result.id}`)
      setOpen(false)
      setId('')
      setName('')
      setDescription('')
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      await navigate({ to: '/kb/$project', params: { project: result.id } })
    },
    onError: (error) => toast.error(error.message),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size='sm'>
          <Plus /> 新建知识库
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>新建知识库</DialogTitle>
          <DialogDescription>
            id 会成为真源目录名（knowledge/&lt;id&gt;），创建后不可修改；显示名和描述随时可改。
          </DialogDescription>
        </DialogHeader>
        <div className='space-y-3'>
          <div className='space-y-1.5'>
            <Label>id</Label>
            <Input
              value={id}
              onChange={(event) => setId(event.target.value)}
              placeholder='sdp-tag'
              className='font-mono'
            />
            {id.trim() && !valid && (
              <p className='text-xs text-destructive'>
                只能用小写字母/数字/./_/-，且以字母或数字开头
              </p>
            )}
          </div>
          <div className='space-y-1.5'>
            <Label>显示名</Label>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder='留空则用 id'
            />
          </div>
          <div className='space-y-1.5'>
            <Label>描述</Label>
            <Textarea
              rows={3}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button
            disabled={!valid || create.isPending}
            onClick={() => create.mutate()}
          >
            {create.isPending ? '创建中…' : '创建'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
