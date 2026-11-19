import { useMemo, useState } from 'react'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  type ColumnDef,
  type ColumnFiltersState,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getFacetedRowModel,
  getFacetedUniqueValues,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { Plus } from 'lucide-react'
import { toast } from 'sonner'
import {
  KINDS,
  TIERS,
  api,
  type Kind,
  type NodeSummary,
  type Tier,
} from '@/lib/api'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
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
import { Textarea } from '@/components/ui/textarea'
import {
  DataTableColumnHeader,
  DataTablePagination,
  DataTableToolbar,
} from '@/components/data-table'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

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

const facetFilter = (value: unknown, selected: unknown) =>
  Array.isArray(selected) && selected.includes(value)

const columns: ColumnDef<NodeSummary>[] = [
  {
    accessorKey: 'title',
    header: ({ column }) => <DataTableColumnHeader column={column} title='标题' />,
    cell: ({ row }) => (
      <Link
        to='/nodes/$'
        params={{ _splat: row.original.id }}
        className='font-medium hover:underline'
      >
        {row.original.title}
      </Link>
    ),
  },
  {
    accessorKey: 'kind',
    header: ({ column }) => <DataTableColumnHeader column={column} title='类型' />,
    filterFn: facetFilter,
    cell: ({ row }) => <Badge variant='outline'>{row.original.kind}</Badge>,
  },
  {
    accessorKey: 'tier',
    header: ({ column }) => <DataTableColumnHeader column={column} title='层级' />,
    filterFn: facetFilter,
    cell: ({ row }) => (
      <Badge variant={row.original.tier === 'canonical' ? 'default' : 'secondary'}>
        {row.original.tier}
      </Badge>
    ),
  },
  {
    accessorKey: 'project',
    header: ({ column }) => <DataTableColumnHeader column={column} title='项目' />,
    cell: ({ row }) => (
      <span className='font-mono text-xs'>{row.original.project}</span>
    ),
  },
  {
    id: 'tags',
    accessorFn: (row) => row.tags.join(','),
    header: ({ column }) => <DataTableColumnHeader column={column} title='标签' />,
    enableSorting: false,
    cell: ({ row }) => (
      <div className='flex flex-wrap gap-1'>
        {row.original.tags.slice(0, 3).map((tag) => (
          <span key={tag} className='rounded bg-muted px-1.5 py-0.5 text-xs'>
            {tag}
          </span>
        ))}
      </div>
    ),
  },
  {
    accessorKey: 'updated_at',
    header: ({ column }) => <DataTableColumnHeader column={column} title='更新' />,
    cell: ({ row }) => (
      <span className='text-xs whitespace-nowrap text-muted-foreground'>
        {new Date(row.original.updated_at).toLocaleString('zh-CN')}
      </span>
    ),
  },
]

function NodesPage() {
  const search = Route.useSearch()
  const query = useQuery({
    queryKey: ['nodes', 'all'],
    queryFn: () => api.listNodes({ limit: 500 }),
  })
  const [globalFilter, setGlobalFilter] = useState('')
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>(() => {
    const initial: ColumnFiltersState = []
    if (search.kind) initial.push({ id: 'kind', value: [search.kind] })
    if (search.tier) initial.push({ id: 'tier', value: [search.tier] })
    return initial
  })
  const [sorting, setSorting] = useState<SortingState>([{ id: 'updated_at', desc: true }])

  const data = useMemo(() => query.data?.items ?? [], [query.data])
  const filtered = useMemo(() => {
    if (!globalFilter.trim()) return data
    const needle = globalFilter.trim().toLowerCase()
    return data.filter((node) =>
      [node.id, node.title, node.tags.join(' ')].join(' ').toLowerCase().includes(needle),
    )
  }, [data, globalFilter])

  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: filtered,
    columns,
    state: { columnFilters, sorting, globalFilter },
    onColumnFiltersChange: setColumnFilters,
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getFacetedRowModel: getFacetedRowModel(),
    getFacetedUniqueValues: getFacetedUniqueValues(),
    initialState: { pagination: { pageSize: 20 } },
  })

  return (
    <>
      <Header>
        <Search />
        <ThemeSwitch />
      </Header>

      <Main className='flex flex-1 flex-col gap-4'>
        <div className='flex flex-wrap items-end justify-between gap-2'>
          <div>
            <h1 className='text-2xl font-bold tracking-tight'>知识节点</h1>
            <p className='text-sm text-muted-foreground'>
              每个节点就是 knowledge/ 下的一个 markdown 文件，编辑会直接改真源并 git 提交。
            </p>
          </div>
          <CreateNodeDialog />
        </div>

        <Card>
          <CardContent className='space-y-3 py-4'>
            <DataTableToolbar
              table={table}
              searchPlaceholder='搜索标题 / 标签 / id…'
              filters={[
                {
                  columnId: 'kind',
                  title: '类型',
                  options: KINDS.map((kind) => ({ label: kind.label, value: kind.value })),
                },
                {
                  columnId: 'tier',
                  title: '层级',
                  options: TIERS.map((tier) => ({ label: tier.label, value: tier.value })),
                },
              ]}
            />

            {query.isError && (
              <p className='py-6 text-center text-sm text-destructive'>
                {query.error.message}
              </p>
            )}

            <div className='overflow-x-auto rounded-md border'>
              <Table>
                <TableHeader>
                  {table.getHeaderGroups().map((group) => (
                    <TableRow key={group.id}>
                      {group.headers.map((header) => (
                        <TableHead key={header.id}>
                          {header.isPlaceholder
                            ? null
                            : flexRender(
                                header.column.columnDef.header,
                                header.getContext(),
                              )}
                        </TableHead>
                      ))}
                    </TableRow>
                  ))}
                </TableHeader>
                <TableBody>
                  {table.getRowModel().rows.length ? (
                    table.getRowModel().rows.map((row) => (
                      <TableRow key={row.id} className={cn('hover:bg-accent/40')}>
                        {row.getVisibleCells().map((cell) => (
                          <TableCell key={cell.id} className='py-2'>
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell
                        colSpan={columns.length}
                        className='h-24 text-center text-sm text-muted-foreground'
                      >
                        {query.isLoading ? '加载中…' : '没有匹配的节点'}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>

            <div className='flex items-center justify-between text-xs text-muted-foreground'>
              <span>
                共 {filtered.length} 个节点
                {filtered.length !== data.length && `（从 ${data.length} 中筛选）`}
              </span>
              <DataTablePagination table={table} />
            </div>
          </CardContent>
        </Card>
      </Main>
    </>
  )
}

function CreateNodeDialog() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<Kind>('fact')
  const [title, setTitle] = useState('')
  const [project, setProject] = useState('memhub')
  const [tags, setTags] = useState('')
  const [body, setBody] = useState('')

  const create = useMutation({
    mutationFn: () =>
      api.createNode({
        kind,
        title: title.trim(),
        project: project.trim() || 'memhub',
        tags: tags
          .split(',')
          .map((tag) => tag.trim())
          .filter(Boolean),
        body,
      }),
    onSuccess: async (result) => {
      toast.success(`已创建 ${result.id}`)
      setOpen(false)
      setTitle('')
      setTags('')
      setBody('')
      await queryClient.invalidateQueries()
      await navigate({ to: '/nodes/$', params: { _splat: result.id } })
    },
    onError: (error) => toast.error(error.message),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size='sm'>
          <Plus /> 新建节点
        </Button>
      </DialogTrigger>
      <DialogContent className='sm:max-w-xl'>
        <DialogHeader>
          <DialogTitle>新建知识节点</DialogTitle>
          <DialogDescription>
            写入 markdown 真源；slug 由标题生成，无法生成时使用随机短码。
          </DialogDescription>
        </DialogHeader>
        <div className='space-y-3'>
          <div className='grid grid-cols-2 gap-3'>
            <div className='space-y-1.5'>
              <Label>类型</Label>
              <Select value={kind} onValueChange={(value) => setKind(value as Kind)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {KINDS.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}（{item.value}）
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className='space-y-1.5'>
              <Label>项目</Label>
              <Input value={project} onChange={(event) => setProject(event.target.value)} />
            </div>
          </div>
          <div className='space-y-1.5'>
            <Label>标题</Label>
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder='一句话说清这条知识'
            />
          </div>
          <div className='space-y-1.5'>
            <Label>标签（逗号分隔）</Label>
            <Input value={tags} onChange={(event) => setTags(event.target.value)} />
          </div>
          <div className='space-y-1.5'>
            <Label>正文（markdown）</Label>
            <Textarea
              rows={8}
              value={body}
              onChange={(event) => setBody(event.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button
            disabled={!title.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            {create.isPending ? '创建中…' : '创建'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
