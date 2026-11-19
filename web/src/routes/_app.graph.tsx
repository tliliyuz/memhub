import { useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export const Route = createFileRoute('/_app/graph')({
  component: GraphPage,
})

const GRAPH_URL = import.meta.env.VITE_GRAPH_URL ?? 'http://127.0.0.1:8703/'

function GraphPage() {
  const queryClient = useQueryClient()
  // 重建后 explorer 会被 kb-api 重启，iframe 需要换一个 key 才会重新加载。
  const [generation, setGeneration] = useState(0)
  const projection = useQuery({
    queryKey: ['projection'],
    queryFn: api.projection,
    refetchInterval: 10_000,
  })

  const rebuild = useMutation({
    mutationFn: api.rebuild,
    onSuccess: async (result) => {
      toast.success(`投影已重建：${result.nodes} 节点 / ${result.edges} 边`)
      setGeneration((value) => value + 1)
      await queryClient.invalidateQueries()
    },
    onError: (error) => toast.error(error.message),
  })

  return (
    <>
      <Header>
        <div className='me-auto flex items-center gap-2 text-sm'>
          <span className='font-medium'>知识图谱</span>
          <span className='text-xs text-muted-foreground'>
            {projection.data
              ? `${projection.data.nodes} 节点 / ${projection.data.edges} 边${projection.data.stale ? ' · 投影已过期' : ''}`
              : '加载中…'}
          </span>
        </div>
        <Button
          variant='outline'
          size='sm'
          onClick={() => rebuild.mutate()}
          disabled={rebuild.isPending || projection.data?.running}
        >
          <RefreshCw className={rebuild.isPending ? 'animate-spin' : ''} />
          重建并刷新
        </Button>
        <Button asChild variant='ghost' size='sm'>
          <a href={GRAPH_URL} target='_blank' rel='noreferrer'>
            <ExternalLink /> 新窗口打开
          </a>
        </Button>
        <Search />
        <ThemeSwitch />
      </Header>

      <Main fixed fluid className='h-[calc(100svh-4rem)] p-4'>
        <div className='min-h-0 flex-1 overflow-hidden rounded-md border'>
          <iframe
            key={generation}
            title='semantica explorer'
            src={GRAPH_URL}
            className='size-full border-0'
            allow='fullscreen'
          />
        </div>
      </Main>
    </>
  )
}
