import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight } from 'lucide-react'
import { KINDS, api, type Kind } from '@/lib/api'
import { NodesBrowser } from '@/components/nodes/nodes-browser'

type KbNodesSearch = { kind?: Kind }

export const Route = createFileRoute('/_app/kb/$project/nodes')({
  validateSearch: (search: Record<string, unknown>): KbNodesSearch => ({
    kind: KINDS.some((item) => item.value === search.kind)
      ? (search.kind as Kind)
      : undefined,
  }),
  component: KbNodesPage,
})

function KbNodesPage() {
  const { project } = Route.useParams()
  const search = Route.useSearch()
  const projects = useQuery({ queryKey: ['projects'], queryFn: api.projects })
  const kb = projects.data?.items.find((item) => item.id === project)

  return (
    <NodesBrowser
      heading='知识节点'
      description='这个列表只包含当前知识库的节点；其他知识库的条目不会出现在这里。'
      project={project}
      initialKind={search.kind}
      backTo={`/kb/${project}`}
      breadcrumbs={
        <>
          <Link to='/' className='hover:underline'>
            知识库
          </Link>
          <ChevronRight className='size-3' />
          <Link to='/kb/$project' params={{ project }} className='hover:underline'>
            {kb?.name ?? project}
          </Link>
          <ChevronRight className='size-3' />
          <span>节点</span>
        </>
      }
    />
  )
}
