import { useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, ExternalLink, Loader2, X } from 'lucide-react'
import { KINDS, api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { BackButton } from '@/components/layout/back-button'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { GraphCanvas, type GraphCanvasNode } from '@/components/graph/graph-canvas'

export const Route = createFileRoute('/_app/kb/$project/graph')({
  component: KbGraphPage,
})

function KbGraphPage() {
  const { project } = Route.useParams()
  const [selected, setSelected] = useState<GraphCanvasNode | null>(null)
  const projects = useQuery({ queryKey: ['projects'], queryFn: api.projects })
  const graph = useQuery({ queryKey: ['graph', project], queryFn: () => api.graph(project) })
  const kb = projects.data?.items.find((item) => item.id === project)

  return (
    <>
      <Header>
        <Search />
        <ThemeSwitch />
      </Header>

      <Main fixed fluid className='flex h-[calc(100svh-4rem)] flex-col gap-2 p-4'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <div className='flex items-center gap-1 text-sm'>
            <BackButton fallbackTo={`/kb/${project}`} />
            <Link to='/' className='text-muted-foreground hover:underline'>
              知识库
            </Link>
            <ChevronRight className='size-3.5 text-muted-foreground' />
            <Link
              to='/kb/$project'
              params={{ project }}
              className='font-medium hover:underline'
            >
              {kb?.name ?? project}
            </Link>
            <ChevronRight className='size-3.5 text-muted-foreground' />
            <span className='text-muted-foreground'>知识图谱</span>
          </div>
          <div className='flex items-center gap-2 text-xs text-muted-foreground'>
            <span>
              {graph.data
                ? `${graph.data.nodes.length} 节点 · ${graph.data.edges.length} 边`
                : '加载中…'}
            </span>
            {graph.data && graph.data.unresolved_edges > 0 && (
              <Badge variant='outline' className='text-[10px]'>
                {graph.data.unresolved_edges} 条未解析边
              </Badge>
            )}
            <Button asChild variant='ghost' size='sm'>
              <Link to='/kb/$project/nodes' params={{ project }}>
                节点列表 <ExternalLink />
              </Link>
            </Button>
          </div>
        </div>

        <div className='relative min-h-0 flex-1 overflow-hidden rounded-md border bg-background'>
          {graph.isLoading && (
            <div className='absolute inset-0 z-10 flex items-center justify-center gap-2 text-sm text-muted-foreground'>
              <Loader2 className='size-4 animate-spin' /> 正在构图…
            </div>
          )}
          {graph.isError && (
            <div className='absolute inset-0 z-10 flex items-center justify-center text-sm text-destructive'>
              {graph.error.message}
            </div>
          )}
          {graph.data && (
            <GraphCanvas
              key={project}
              nodes={graph.data.nodes}
              edges={graph.data.edges}
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
                        <Badge
                          variant={selected.tier === 'canonical' ? 'default' : 'secondary'}
                          className='text-[10px]'
                        >
                          {selected.tier}
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
                  {selected.tags.length > 0 && (
                    <div className='flex flex-wrap gap-1'>
                      {selected.tags.map((tag) => (
                        <span
                          key={tag}
                          className='rounded bg-muted px-1.5 py-0.5 text-[10px]'
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className='font-mono text-[10px] break-all text-muted-foreground'>
                    {selected.id}
                  </div>
                  <Button asChild size='sm' className='w-full'>
                    <Link to='/nodes/$' params={{ _splat: selected.id }}>
                      打开节点详情
                    </Link>
                  </Button>
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      </Main>
    </>
  )
}
