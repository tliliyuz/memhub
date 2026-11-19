import { useMemo, useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useQueries, useQuery } from '@tanstack/react-query'
import { Loader2, X } from 'lucide-react'
import { KINDS, api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { GraphCanvas, type GraphCanvasNode } from '@/components/graph/graph-canvas'

export const Route = createFileRoute('/_app/graph')({
  component: GlobalGraphPage,
})

function GlobalGraphPage() {
  const [selected, setSelected] = useState<GraphCanvasNode | null>(null)
  const projects = useQuery({ queryKey: ['projects'], queryFn: api.projects })
  const kbs = useMemo(() => projects.data?.items ?? [], [projects.data])
  const graphs = useQueries({
    queries: kbs.map((kb) => ({
      queryKey: ['graph', kb.id],
      queryFn: () => api.graph(kb.id),
    })),
  })

  const stamped = graphs.map((graph) => graph.dataUpdatedAt).join(',')
  const nodes = useMemo(
    () =>
      graphs.flatMap((graph, index) =>
        (graph.data?.nodes ?? []).map((node) => ({
          ...node,
          project: kbs[index].id,
        })),
      ),
    // graphs 数组每次渲染都是新引用，用数据指纹做依赖。
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [stamped, kbs],
  )
  const edges = useMemo(
    () => graphs.flatMap((graph) => graph.data?.edges ?? []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [stamped],
  )
  const loading = projects.isLoading || graphs.some((graph) => graph.isLoading)
  const failed = projects.isError || graphs.some((graph) => graph.isError)

  return (
    <>
      <Header>
        <Search />
        <ThemeSwitch />
      </Header>

      <Main fixed fluid className='flex h-[calc(100svh-4rem)] flex-col gap-2 p-4'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <div>
            <h1 className='text-lg font-semibold tracking-tight'>全局知识图谱</h1>
            <p className='text-xs text-muted-foreground'>
              所有知识库各成一个簇，颜色区分知识库；具体某个库请从左侧进入它自己的图谱。
            </p>
          </div>
          <span className='text-xs text-muted-foreground'>
            {nodes.length} 节点 · {edges.length} 边 · {kbs.length} 个知识库
          </span>
        </div>

        <div className='relative min-h-0 flex-1 overflow-hidden rounded-md border bg-background'>
          {loading && (
            <div className='absolute inset-0 z-10 flex items-center justify-center gap-2 text-sm text-muted-foreground'>
              <Loader2 className='size-4 animate-spin' /> 正在构图…
            </div>
          )}
          {failed && (
            <div className='absolute inset-0 z-10 flex items-center justify-center text-sm text-destructive'>
              {projects.error?.message ?? '图谱加载失败'}
            </div>
          )}
          {!loading && !failed && (
            <GraphCanvas
              nodes={nodes}
              edges={edges}
              colorBy='project'
              projects={kbs.map((kb) => ({ id: kb.id, name: kb.name }))}
              className='size-full'
              selectedId={selected?.id ?? null}
              onSelect={setSelected}
            />
          )}

          {selected && (
            <div className='pointer-events-none absolute inset-x-0 bottom-0 flex justify-end p-3'>
              <Card className='pointer-events-auto w-80'>
                <CardContent className='space-y-2 py-3'>
                  <div className='flex items-start justify-between gap-2'>
                    <div className='min-w-0'>
                      <div className='text-sm font-medium break-words'>
                        {selected.title}
                      </div>
                      <div className='mt-1 flex flex-wrap items-center gap-1'>
                        <Badge variant='outline' className='text-[10px]'>
                          {KINDS.find((item) => item.value === selected.kind)?.label ??
                            selected.kind}
                        </Badge>
                        <Badge variant='secondary' className='font-mono text-[10px]'>
                          {selected.project}
                        </Badge>
                        <span className='text-[10px] text-muted-foreground'>
                          度数 {selected.degree}
                        </span>
                      </div>
                    </div>
                    <Button
                      variant='ghost'
                      size='icon'
                      className='size-7 shrink-0'
                      onClick={() => setSelected(null)}
                    >
                      <X className='size-3.5' />
                    </Button>
                  </div>
                  <div className='font-mono text-[10px] break-all text-muted-foreground'>
                    {selected.id}
                  </div>
                  <div className='grid grid-cols-2 gap-2'>
                    <Button asChild size='sm' variant='outline'>
                      <Link
                        to='/kb/$project'
                        params={{ project: selected.project ?? '' }}
                      >
                        知识库
                      </Link>
                    </Button>
                    <Button asChild size='sm'>
                      <Link to='/nodes/$' params={{ _splat: selected.id }}>
                        节点详情
                      </Link>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      </Main>
    </>
  )
}
