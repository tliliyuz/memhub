import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { ISSUE_LABELS, api, type Issue } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export const Route = createFileRoute('/_app/audit')({
  component: AuditPage,
})

const ORDER: Issue['type'][] = [
  'contradiction',
  'broken_link',
  'orphan',
  'low_confidence',
  'stale',
]

function AuditPage() {
  const audit = useQuery({ queryKey: ['audit'], queryFn: () => api.audit(500) })
  const groups = new Map<Issue['type'], Issue[]>()
  for (const issue of audit.data?.issues ?? []) {
    const list = groups.get(issue.type) ?? []
    list.push(issue)
    groups.set(issue.type, list)
  }

  return (
    <>
      <Header>
        <Search />
        <ThemeSwitch />
      </Header>

      <Main className='flex flex-1 flex-col gap-4'>
        <div>
          <h1 className='text-2xl font-bold tracking-tight'>治理审计</h1>
          <p className='text-sm text-muted-foreground'>
            问题是现算的：矛盾、断链、孤立节点、低置信、陈旧。修复从点开节点开始。
          </p>
        </div>

        {ORDER.map((type) => {
          const issues = groups.get(type) ?? []
          if (issues.length === 0) return null
          return (
            <Card key={type}>
              <CardHeader className='flex-row items-center gap-2'>
                <CardTitle className='text-base'>{ISSUE_LABELS[type]}</CardTitle>
                <Badge variant='secondary'>{issues.length}</Badge>
              </CardHeader>
              <CardContent className='space-y-1'>
                {issues.map((issue, index) => (
                  <IssueRow key={`${type}-${index}`} issue={issue} />
                ))}
              </CardContent>
            </Card>
          )
        })}

        {audit.isSuccess && (audit.data?.issues.length ?? 0) === 0 && (
          <Card>
            <CardContent className='py-10 text-center text-sm text-muted-foreground'>
              没有发现治理问题。
            </CardContent>
          </Card>
        )}
      </Main>
    </>
  )
}

function IssueRow({ issue }: { issue: Issue }) {
  if (Array.isArray(issue.target)) {
    return (
      <div className='rounded px-2 py-1.5 text-sm hover:bg-accent/40'>
        <span className='font-mono text-xs'>{issue.target.join(' ↔ ')}</span>
      </div>
    )
  }
  const target = issue.target
  // 断链的 target 是 "source -predicate-> target" 文本，不可跳转；其余是节点 id。
  if (issue.type === 'broken_link') {
    return (
      <div className='rounded px-2 py-1.5 font-mono text-xs hover:bg-accent/40'>
        {target}
      </div>
    )
  }
  return (
    <Link
      to='/nodes/$'
      params={{ _splat: target }}
      className='block rounded px-2 py-1.5 font-mono text-xs hover:bg-accent'
    >
      {target}
    </Link>
  )
}
