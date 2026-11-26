import { useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { api, type McpTrace, type TraceStatus } from '@/lib/api'
import { credentialLabel, sinceFromDays } from '@/lib/traces'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export const Route = createFileRoute('/_app/traces')({
  component: TracesPage,
})

const PAGE_SIZE = 50
const ALL = '__all__'
const RANGES = [
  { days: 1, label: '近 1 天' },
  { days: 7, label: '近 7 天' },
  { days: 30, label: '近 30 天' },
]
const STATUS_LABELS: Record<TraceStatus, string> = {
  ok: '成功',
  error: '失败',
  rejected: '拒绝',
}
const STATUS_VARIANTS: Record<TraceStatus, 'secondary' | 'destructive' | 'outline'> = {
  ok: 'secondary',
  error: 'destructive',
  rejected: 'outline',
}

function formatBytes(bytes: number | null): string {
  if (bytes === null) return '—'
  if (bytes < 1024) return `${bytes} B`
  return `${(bytes / 1024).toFixed(1)} KB`
}

function TracesPage() {
  const [days, setDays] = useState(7)
  const [tool, setTool] = useState(ALL)
  const [status, setStatus] = useState(ALL)
  const [credential, setCredential] = useState(ALL)
  const [page, setPage] = useState(0)

  const summary = useQuery({
    queryKey: ['mcp-traces-summary', days],
    queryFn: () => api.mcpTracesSummary(days),
    placeholderData: keepPreviousData,
  })
  const traces = useQuery({
    queryKey: ['mcp-traces', days, tool, status, credential, page],
    queryFn: () =>
      api.mcpTraces({
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        tool: tool === ALL ? undefined : tool,
        status: status === ALL ? undefined : (status as TraceStatus),
        credential: credential === ALL ? undefined : credential,
        since: sinceFromDays(days),
      }),
    placeholderData: keepPreviousData,
  })

  const items = traces.data?.items ?? []
  const total = traces.data?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const stats = summary.data
  const filtered = tool !== ALL || status !== ALL || credential !== ALL

  // 筛选变化后回到第一页，避免停在已不存在的页码。
  const change = (apply: () => void) => {
    apply()
    setPage(0)
  }

  return (
    <>
      <Header>
        <Search />
        <ThemeSwitch />
      </Header>

      <Main className='flex flex-1 flex-col gap-4'>
        <div>
          <h1 className='text-2xl font-bold tracking-tight'>调用轨迹</h1>
          <p className='text-sm text-muted-foreground'>
            服务端记录的每次 MCP 工具调用与鉴权拒绝，只含元数据，不含参数原文。
          </p>
        </div>

        <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-4'>
          <SummaryCard label='总调用' value={stats?.total} />
          <SummaryCard label='成功' value={stats?.ok} />
          <SummaryCard label='失败' value={stats?.error} tone='destructive' />
          <SummaryCard label='拒绝' value={stats?.rejected} />
        </div>

        <Card>
          <CardHeader>
            <CardTitle className='text-base'>按工具分布</CardTitle>
            <CardDescription>
              汇总仅按时间范围统计；平均耗时不含拒绝记录。
            </CardDescription>
          </CardHeader>
          <CardContent>
            {summary.isError ? (
              <p role='alert' className='text-sm text-destructive'>汇总加载失败，可刷新页面重试。</p>
            ) : (stats?.tools.length ?? 0) === 0 ? (
              <p className='text-sm text-muted-foreground'>
                {summary.isLoading ? '加载中…' : '所选时间范围内没有调用。'}
              </p>
            ) : (
              <div className='flex flex-wrap gap-2'>
                {stats?.tools.map((item) => (
                  <Badge key={item.tool} variant='outline' className='gap-1.5 font-mono'>
                    {item.tool}
                    <span className='text-muted-foreground'>
                      {item.count} 次 · 均 {item.avg_ms} ms
                    </span>
                  </Badge>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardContent className='pt-6'>
            <div className='mb-3 flex flex-wrap items-center gap-2'>
              <Select
                value={String(days)}
                onValueChange={(value) => change(() => setDays(Number(value)))}
              >
                <SelectTrigger className='w-32'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {RANGES.map((range) => (
                    <SelectItem key={range.days} value={String(range.days)}>
                      {range.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={tool} onValueChange={(value) => change(() => setTool(value))}>
                <SelectTrigger className='w-44'>
                  <SelectValue placeholder='全部工具' />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>全部工具</SelectItem>
                  {/* 拒绝记录没有工具名，汇总里记作 (unknown)，不能作为工具筛选值；用「状态=拒绝」筛选。 */}
                  {(stats?.tools ?? [])
                    .filter((item) => item.tool !== '(unknown)')
                    .map((item) => (
                      <SelectItem key={item.tool} value={item.tool}>
                        {item.tool}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
              <Select value={status} onValueChange={(value) => change(() => setStatus(value))}>
                <SelectTrigger className='w-32'>
                  <SelectValue placeholder='全部状态' />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>全部状态</SelectItem>
                  {(Object.keys(STATUS_LABELS) as TraceStatus[]).map((key) => (
                    <SelectItem key={key} value={key}>
                      {STATUS_LABELS[key]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={credential}
                onValueChange={(value) => change(() => setCredential(value))}
              >
                <SelectTrigger className='w-48'>
                  <SelectValue placeholder='全部凭据' />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>全部凭据</SelectItem>
                  {(stats?.credentials ?? [])
                    .filter((item) => item.id !== '')
                    .map((item) => (
                      <SelectItem key={item.id} value={item.id}>
                        {credentialLabel(item)}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
              {filtered && (
                <Button
                  variant='ghost'
                  size='sm'
                  onClick={() =>
                    change(() => {
                      setTool(ALL)
                      setStatus(ALL)
                      setCredential(ALL)
                    })
                  }
                >
                  清除
                </Button>
              )}
            </div>

            <div className='overflow-x-auto rounded-md border'>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>时间</TableHead>
                    <TableHead>请求 ID</TableHead>
                    <TableHead>工具</TableHead>
                    <TableHead>凭据</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>HTTP</TableHead>
                    <TableHead>错误码</TableHead>
                    <TableHead className='text-end'>耗时</TableHead>
                    <TableHead className='text-end'>结果大小</TableHead>
                    <TableHead>客户端</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <TraceRow key={item.trace_id} item={item} />
                  ))}
                  {items.length === 0 && (
                    <TableRow>
                      <TableCell
                        colSpan={10}
                        className='h-24 text-center text-sm text-muted-foreground'
                      >
                        {traces.isLoading
                          ? '加载中…'
                          : traces.isError
                            ? `加载失败：${traces.error.message}`
                            : '没有符合条件的调用。轨迹只保留 30 天明细，更早数据已清理。'}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>

            <div className='mt-3 flex items-center justify-between'>
              <span className='text-sm text-muted-foreground'>
                {traces.isLoading ? '加载中…' : `共 ${total} 条`}
              </span>
              <div className='flex items-center gap-2'>
                <Button
                  variant='outline'
                  size='sm'
                  disabled={page === 0 || traces.isFetching}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                >
                  <ChevronLeft /> 上一页
                </Button>
                <span className='text-sm text-muted-foreground'>
                  {page + 1} / {pageCount}
                </span>
                <Button
                  variant='outline'
                  size='sm'
                  disabled={page + 1 >= pageCount || traces.isFetching}
                  onClick={() => setPage((p) => p + 1)}
                >
                  下一页 <ChevronRight />
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </Main>
    </>
  )
}

function SummaryCard({
  label,
  value,
  tone,
}: {
  label: string
  value: number | undefined
  tone?: 'destructive'
}) {
  return (
    <Card>
      <CardHeader className='pb-2'>
        <CardDescription>{label}</CardDescription>
        <CardTitle className={`text-2xl ${tone === 'destructive' ? 'text-destructive' : ''}`}>
          {value ?? '—'}
        </CardTitle>
      </CardHeader>
    </Card>
  )
}

function TraceRow({ item }: { item: McpTrace }) {
  return (
    <TableRow>
      <TableCell className='text-xs whitespace-nowrap text-muted-foreground'>
        {new Date(item.called_at).toLocaleString('zh-CN')}
      </TableCell>
      <TableCell className='font-mono text-xs' title={item.request_id}>
        {item.request_id.slice(0, 8)}
      </TableCell>
      <TableCell className='font-mono text-xs'>{item.tool ?? '—'}</TableCell>
      <TableCell className='text-sm'>{credentialLabel(item.credential)}</TableCell>
      <TableCell>
        <Badge variant={STATUS_VARIANTS[item.status]}>{STATUS_LABELS[item.status]}</Badge>
      </TableCell>
      <TableCell className='font-mono text-xs'>{item.http_status}</TableCell>
      <TableCell className='font-mono text-xs'>
        {item.error_code ?? item.error_kind ?? '—'}
      </TableCell>
      <TableCell className='text-end font-mono text-xs'>{item.duration_ms} ms</TableCell>
      <TableCell className='text-end font-mono text-xs'>{formatBytes(item.result_bytes)}</TableCell>
      <TableCell className='max-w-48 truncate text-xs text-muted-foreground' title={item.client ?? ''}>
        {item.client ?? '—'}
      </TableCell>
    </TableRow>
  )
}
