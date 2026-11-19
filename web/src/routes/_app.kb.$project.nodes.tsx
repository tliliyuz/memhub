import { createFileRoute } from '@tanstack/react-router'
import { KINDS, type Kind } from '@/lib/api'
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
  return (
    <NodesBrowser
      heading='知识节点'
      description='这个列表只包含当前知识库的节点；其他知识库的条目不会出现在这里。'
      project={project}
      initialKind={search.kind}
    />
  )
}
