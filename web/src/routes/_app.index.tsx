import { createFileRoute, Link } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, GitFork, Network, RefreshCw, Waypoints } from 'lucide-react'
import { toast } from 'sonner'
import { KINDS, TIERS, api, type Kind } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export const Route = createFileRoute('/_app/')({
  component: Dashboard,
})

function Dashboard() {
  const queryClient = useQueryClient()
  const stats = useQuery({ queryKey: ['stats'], queryFn: api.stats })
  const projection = useQuery({ queryKey: ['projection'], queryFn: api.projection })
  const recent = useQuery({
    queryKey: ['nodes', 'recent'],
    queryFn: () => api.listNodes({ limit: 8 }),
  })

  const rebuild = useMutation({
    mutationFn: api.rebuild,
    onSuccess: async (result) => {
      toast.success(`投影已重建：${result.nodes} 节点 / ${result.edges} 边`)
      await queryClient.invalidateQueries()
    },
    onError: (error) => toast.error(error.message),
  })

  const byKind = stats.data?.by_kind ?? {}

  return (
    <>
      <Header>
        <Search />
        <ThemeSwitch />
      </Header>

      <Main className='flex flex-1 flex-col gap-4'>
        <div>
          <h1 className='text-2xl font-bold tracking-tight'>知识库概览</h1>
          <p className='text-sm text-muted-foreground'>
            markdown 是真源，图谱是由真源重建的投影。这里的每个数字都来自真源目录。
          </p>
        </div>

        {(projection.data?.stale || projection.data?.error) && (
          <Card className='border-amber-500/40 bg-amber-500/5'>
            <CardContent className='flex flex-wrap items-center gap-3 py-4'>
              <AlertTriangle className='size-5 text-amber-600' />
              <div className='flex-1'>
                <div className='text-sm font-medium'>
                  {projection.data?.error
                    ? `上次重建失败：${projection.data.error}`
                    : '真源有更新，图谱投影已过期'}
                </div>
                <div className='text-xs text-muted-foreground'>
                  重建后 explorer 会自动重启并加载新图谱。
                </div>
              </div>
              <Button
                size='sm'
                onClick={() => rebuild.mutate()}
                disabled={rebuild.isPending || projection.data?.running}
              >
                <RefreshCw className={rebuild.isPending ? 'animate-spin' : ''} />
                重建投影
              </Button>
            </CardContent>
          </Card>
        )}

        <div className='grid gap-3 sm:grid-cols-2 xl:grid-cols-4'>
          <StatCard
            icon={<Network className='size-4' />}
            label='知识节点'
            value={stats.data?.nodes ?? 0}
            hint={`${Object.keys(byKind).length} 种类型`}
          />
          <StatCard
            icon={<GitFork className='size-4' />}
            label='关系边'
            value={stats.data?.edges ?? 0}
            hint={
              stats.data?.unresolved_edges
                ? `${stats.data.unresolved_edges} 条未解析`
                : '全部已解析'
            }
          />
          <StatCard
            icon={<Waypoints className='size-4' />}
            label='孤立节点'
            value={stats.data?.orphans ?? 0}
            hint='没有任何边的节点'
          />
          <StatCard
            icon={<RefreshCw className='size-4' />}
            label='投影'
            value={projection.data?.nodes ?? 0}
            hint={
              projection.data?.graph_mtime
                ? `更新于 ${new Date(projection.data.graph_mtime).toLocaleString('zh-CN')}`
                : '尚未生成'
            }
          />
        </div>

        <div className='grid gap-4 lg:grid-cols-2'>
          <Card>
            <CardHeader>
              <CardTitle className='text-base'>按类型</CardTitle>
              <CardDescription>node.kind 分布</CardDescription>
            </CardHeader>
            <CardContent className='flex flex-wrap gap-2'>
              {KINDS.map((kind) => (
                <Link
                  key={kind.value}
                  to='/nodes'
                  search={{ kind: kind.value }}
                  className='rounded-md border px-2 py-1 text-sm hover:bg-accent'
                >
                  {kind.label}
                  <span className='ms-2 font-mono text-xs text-muted-foreground'>
                    {byKind[kind.value as Kind] ?? 0}
                  </span>
                </Link>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className='text-base'>按层级</CardTitle>
              <CardDescription>candidate 是抽取产物，canonical 是确认过的</CardDescription>
            </CardHeader>
            <CardContent className='flex flex-wrap gap-2'>
              {TIERS.map((tier) => (
                <Link
                  key={tier.value}
                  to='/nodes'
                  search={{ tier: tier.value }}
                  className='rounded-md border px-2 py-1 text-sm hover:bg-accent'
                >
                  {tier.label}
                  <span className='ms-2 font-mono text-xs text-muted-foreground'>
                    {stats.data?.by_tier[tier.value] ?? 0}
                  </span>
                </Link>
              ))}
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader className='flex-row items-center justify-between'>
            <div>
              <CardTitle className='text-base'>最近更新</CardTitle>
              <CardDescription>按 updated_at 倒序</CardDescription>
            </div>
            <Button asChild variant='outline' size='sm'>
              <Link to='/nodes'>全部节点</Link>
            </Button>
          </CardHeader>
          <CardContent className='space-y-1'>
            {(recent.data?.items ?? []).map((node) => (
              <Link
                key={node.id}
                to='/nodes/$'
                params={{ _splat: node.id }}
                className='flex items-center gap-3 rounded-md px-2 py-2 hover:bg-accent'
              >
                <Badge variant='outline' className='shrink-0'>
                  {node.kind}
                </Badge>
                <span className='min-w-0 flex-1 truncate text-sm'>{node.title}</span>
                <span className='hidden shrink-0 font-mono text-xs text-muted-foreground sm:block'>
                  {node.id}
                </span>
              </Link>
            ))}
            {recent.data && recent.data.items.length === 0 && (
              <p className='py-6 text-center text-sm text-muted-foreground'>
                还没有知识节点。worker 提炼或手动新建之后会出现在这里。
              </p>
            )}
          </CardContent>
        </Card>
      </Main>
    </>
  )
}

function StatCard({
  icon,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode
  label: string
  value: number
  hint: string
}) {
  return (
    <Card>
      <CardContent className='flex items-start gap-3 py-4'>
        <div className='mt-0.5 flex size-8 items-center justify-center rounded-md bg-muted text-muted-foreground'>
          {icon}
        </div>
        <div className='min-w-0'>
          <div className='text-xs text-muted-foreground'>{label}</div>
          <div className='text-2xl font-semibold tabular-nums'>{value}</div>
          <div className='truncate text-xs text-muted-foreground'>{hint}</div>
        </div>
      </CardContent>
    </Card>
  )
}
