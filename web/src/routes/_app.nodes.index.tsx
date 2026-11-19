import { createFileRoute } from '@tanstack/react-router'
import { KINDS, TIERS, type Kind, type Tier } from '@/lib/api'
import { NodesBrowser } from '@/components/nodes/nodes-browser'

type NodesSearch = { kind?: Kind; tier?: Tier }

export const Route = createFileRoute('/_app/nodes/')({
  validateSearch: (search: Record<string, unknown>): NodesSearch => ({
    kind: KINDS.some((item) => item.value === search.kind)
      ? (search.kind as Kind)
      : undefined,
    tier: TIERS.some((item) => item.value === search.tier)
      ? (search.tier as Tier)
      : undefined,
  }),
  component: NodesPage,
})

function NodesPage() {
  const search = Route.useSearch()
  return (
    <NodesBrowser
      heading='全部知识节点'
      description='跨知识库的平铺视图；要看某个库自己的节点，请从左侧进入该知识库。'
      initialKind={search.kind}
      initialTier={search.tier}
    />
  )
}
