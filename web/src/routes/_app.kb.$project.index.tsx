import { useState } from 'react'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BookOpenText,
  ChevronRight,
  Clock3,
  GitFork,
  Network,
  PencilLine,
  Unlink,
} from 'lucide-react'
import { toast } from 'sonner'
import { KINDS, api, type Kind } from '@/lib/api'
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
import { BackButton } from '@/components/layout/back-button'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export const Route = createFileRoute('/_app/kb/$project/')({
  component: KbOverviewPage,
})

function KbOverviewPage() {
  const { project } = Route.useParams()
  const projects = useQuery({ queryKey: ['projects'], queryFn: api.projects })
  const kb = projects.data?.items.find((item) => item.id === project)
  const graph = useQuery({ queryKey: ['graph', project], queryFn: () => api.graph(project) })
  const recent = useQuery({
    queryKey: ['nodes', project, 'recent'],
    queryFn: () => api.listNodes({ project, limit: 8 }),
  })

  const counts = new Map<Kind, number>()
  for (const node of graph.data?.nodes ?? []) {
    counts.set(node.kind, (counts.get(node.kind) ?? 0) + 1)
  }
  const total = graph.data?.nodes.length ?? 0
  const kinds = KINDS.filter((item) => (counts.get(item.value) ?? 0) > 0)
  // 兜底必须取最大 updated_at：图谱节点没有排序保证，nodes[0] 可能是很久以前的节点，
  // 会让「最近更新」落后于下方「最近更新的节点」列表（尤其 projects 尚未返回时）。
  const graphUpdatedAt = (graph.data?.nodes ?? []).reduce<string | null>(
    (latest, node) =>
      latest === null || node.updated_at > latest ? node.updated_at : latest,
    null,
  )
  const updatedAt = [
    kb?.updated_at,
    recent.data?.items[0]?.updated_at,
    graphUpdatedAt,
  ]
    .filter((value): value is string => Boolean(value))
    .reduce<string | null>(
      (latest, value) => (latest === null || value > latest ? value : latest),
      null,
    )

  if (projects.isError) {
    return (
      <>
        <Header>
          <Search />
          <ThemeSwitch />
        </Header>
        <Main>
          <Card>
            <CardContent className='py-10 text-center text-sm text-destructive'>
              {projects.error.message}
            </CardContent>
          </Card>
          <Button asChild variant='outline' className='mt-4'>
            <Link to='/'>返回知识库列表</Link>
          </Button>
        </Main>
      </>
    )
  }

  return (
    <>
      <Header>
        <Search />
        <ThemeSwitch />
      </Header>

      <Main className='flex flex-1 flex-col gap-4'>
        <div className='flex flex-wrap items-end justify-between gap-3'>
          <div className='min-w-0'>
            <div className='flex items-center gap-1 text-xs text-muted-foreground'>
              <BackButton fallbackTo='/' />
              <Link to='/' className='hover:underline'>
                知识库
              </Link>
              <ChevronRight className='size-3' />
              <span className='font-mono'>{project}</span>
            </div>
            <h1 className='mt-1 truncate text-2xl font-bold tracking-tight'>
              {kb?.name ?? project}
            </h1>
            <p className='text-sm text-muted-foreground'>
              {kb?.description || '这个知识库还没有描述；节点只属于它自己，不会和其他库混在一起。'}
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <EditKbDialog project={project} name={kb?.name ?? project} description={kb?.description ?? ''} />
            <Button asChild variant='outline' size='sm'>
              <Link to='/kb/$project/nodes' params={{ project }}>
                <BookOpenText /> 节点
              </Link>
            </Button>
            <Button asChild size='sm'>
              <Link to='/kb/$project/graph' params={{ project }}>
                <GitFork /> 知识图谱
              </Link>
            </Button>
          </div>
        </div>

        <div className='grid gap-3 sm:grid-cols-2 xl:grid-cols-4'>
          <StatCard icon={BookOpenText} label='知识节点' value={total} hint='markdown 真源里的条目' />
          <StatCard
            icon={Network}
            label='关系'
            value={graph.data?.edges.length ?? 0}
            hint='本库内已解析的边'
          />
          <StatCard
            icon={Unlink}
            label='未解析边'
            value={graph.data?.unresolved_edges ?? 0}
            hint='目标节点不存在或重名'
          />
          <StatCard
            icon={Clock3}
            label='最近更新'
            value={updatedAt ? new Date(updatedAt).toLocaleDateString('zh-CN') : '—'}
            hint='本库最新一条节点'
          />
        </div>

        <div className='grid gap-4 lg:grid-cols-5'>
          <Card className='lg:col-span-2'>
            <CardHeader>
              <CardTitle className='text-base'>类型分布</CardTitle>
              <CardDescription>点类型跳到筛选后的节点列表。</CardDescription>
            </CardHeader>
            <CardContent className='space-y-2'>
              {kinds.length === 0 && (
                <p className='text-sm text-muted-foreground'>还没有节点。</p>
              )}
              {kinds.map((item) => {
                const value = counts.get(item.value) ?? 0
                return (
                  <Link
                    key={item.value}
                    to='/kb/$project/nodes'
                    params={{ project }}
                    search={{ kind: item.value }}
                    className='block space-y-1 rounded-md p-1 hover:bg-accent/50'
                  >
                    <div className='flex items-center justify-between text-xs'>
                      <span>{item.label}</span>
                      <span className='text-muted-foreground'>{value}</span>
                    </div>
                    <div className='h-1.5 overflow-hidden rounded-full bg-muted'>
                      <div
                        className='h-full rounded-full bg-primary'
                        style={{ width: `${total ? (value / total) * 100 : 0}%` }}
                      />
                    </div>
                  </Link>
                )
              })}
            </CardContent>
          </Card>

          <Card className='lg:col-span-3'>
            <CardHeader className='flex flex-row flex-wrap items-center justify-between gap-2'>
              <div className='space-y-1'>
                <CardTitle className='text-base'>最近更新的节点</CardTitle>
                <CardDescription>只列这个知识库自己的条目。</CardDescription>
              </div>
              <Button asChild variant='ghost' size='sm'>
                <Link to='/kb/$project/nodes' params={{ project }}>
                  全部 <ChevronRight />
                </Link>
              </Button>
            </CardHeader>
            <CardContent className='space-y-1'>
              {(recent.data?.items ?? []).map((node) => (
                <Link
                  key={node.id}
                  to='/nodes/$'
                  params={{ _splat: node.id }}
                  className='flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-sm hover:bg-accent/50'
                >
                  <span className='min-w-0 flex-1 truncate'>{node.title}</span>
                  <Badge variant='outline' className='shrink-0 text-[10px]'>
                    {node.kind}
                  </Badge>
                  <span className='shrink-0 text-[11px] text-muted-foreground'>
                    {new Date(node.updated_at).toLocaleDateString('zh-CN')}
                  </span>
                </Link>
              ))}
              {!recent.isLoading && (recent.data?.items.length ?? 0) === 0 && (
                <p className='py-6 text-center text-sm text-muted-foreground'>
                  还没有节点，从「节点」页新建第一个。
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </Main>
    </>
  )
}

function StatCard({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: React.ElementType
  label: string
  value: number | string
  hint: string
}) {
  return (
    <Card>
      <CardContent className='flex items-start gap-3 py-4'>
        <Icon className='mt-0.5 size-4 text-muted-foreground' />
        <div>
          <div className='text-xs text-muted-foreground'>{label}</div>
          <div className='text-2xl font-semibold tabular-nums'>{value}</div>
          <div className='text-[11px] text-muted-foreground'>{hint}</div>
        </div>
      </CardContent>
    </Card>
  )
}

function EditKbDialog({
  project,
  name,
  description,
}: {
  project: string
  name: string
  description: string
}) {
  const [open, setOpen] = useState(false)
  const [nextName, setNextName] = useState(name)
  const [nextDescription, setNextDescription] = useState(description)
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const update = useMutation({
    mutationFn: () =>
      api.updateProject(project, {
        name: nextName.trim(),
        description: nextDescription.trim(),
      }),
    onSuccess: async () => {
      toast.success('知识库信息已更新')
      setOpen(false)
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      await navigate({ to: '/kb/$project', params: { project } })
    },
    onError: (error) => toast.error(error.message),
  })

  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        setOpen(value)
        if (value) {
          setNextName(name)
          setNextDescription(description)
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant='ghost' size='sm'>
          <PencilLine /> 编辑
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>编辑知识库</DialogTitle>
          <DialogDescription>
            id（<span className='font-mono'>{project}</span>）对应真源目录，不可改；显示名和描述只影响管理台。
          </DialogDescription>
        </DialogHeader>
        <div className='space-y-3'>
          <div className='space-y-1.5'>
            <Label>显示名</Label>
            <Input value={nextName} onChange={(event) => setNextName(event.target.value)} />
          </div>
          <div className='space-y-1.5'>
            <Label>描述</Label>
            <Textarea
              rows={3}
              value={nextDescription}
              onChange={(event) => setNextDescription(event.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button disabled={update.isPending} onClick={() => update.mutate()}>
            {update.isPending ? '保存中…' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
