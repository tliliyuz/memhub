import { createFileRoute } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArchiveRestore } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
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

export const Route = createFileRoute('/_app/trash')({
  component: TrashPage,
})

function TrashPage() {
  const queryClient = useQueryClient()
  const trash = useQuery({ queryKey: ['trash'], queryFn: api.trash })

  const restore = useMutation({
    mutationFn: (key: string) => api.restore(key),
    onSuccess: async (result) => {
      toast.success(`已恢复 ${result.id}`)
      await queryClient.invalidateQueries()
    },
    onError: (error) => toast.error(error.message),
  })

  return (
    <>
      <Header>
        <Search />
        <ThemeSwitch />
      </Header>

      <Main className='flex flex-1 flex-col gap-4'>
        <div>
          <h1 className='text-2xl font-bold tracking-tight'>回收站</h1>
          <p className='text-sm text-muted-foreground'>
            删除的节点移到这里（markdown 原样保留），恢复后重新出现在列表里；边不会自动恢复。
          </p>
        </div>

        <Card>
          <CardContent className='py-4'>
            <div className='overflow-x-auto rounded-md border'>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>节点</TableHead>
                    <TableHead>类型</TableHead>
                    <TableHead>删除时间</TableHead>
                    <TableHead>原因</TableHead>
                    <TableHead className='text-end'>操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(trash.data?.items ?? []).map((item) => (
                    <TableRow key={item.trash}>
                      <TableCell>
                        <div className='font-medium'>{item.title}</div>
                        <div className='font-mono text-xs text-muted-foreground'>
                          {item.id}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant='outline'>{item.kind}</Badge>
                      </TableCell>
                      <TableCell className='text-xs whitespace-nowrap text-muted-foreground'>
                        {new Date(item.deleted_at).toLocaleString('zh-CN')}
                      </TableCell>
                      <TableCell className='max-w-64 truncate text-sm'>
                        {item.reason || '—'}
                      </TableCell>
                      <TableCell className='text-end'>
                        <Button
                          variant='outline'
                          size='sm'
                          disabled={restore.isPending}
                          onClick={() => restore.mutate(item.trash)}
                        >
                          <ArchiveRestore /> 恢复
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                  {(trash.data?.items.length ?? 0) === 0 && (
                    <TableRow>
                      <TableCell
                        colSpan={5}
                        className='h-24 text-center text-sm text-muted-foreground'
                      >
                        {trash.isLoading ? '加载中…' : '回收站是空的'}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </Main>
    </>
  )
}
