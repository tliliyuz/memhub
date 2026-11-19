import { HardDrive, RefreshCw } from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar'

/**
 * 侧栏底部：本地运行状态 + 一键重建投影。
 *
 * memhub 管理台是单用户本地服务，没有登录态，所以这里不放账号菜单，
 * 放真正有用的东西：真源目录里有多少节点、投影是否过期。
 */
export function NavUser() {
  const queryClient = useQueryClient()
  const health = useQuery({
    queryKey: ['healthz'],
    queryFn: api.healthz,
    refetchInterval: 30_000,
  })
  const rebuilding = health.data?.projection.running ?? false

  const onRebuild = async () => {
    try {
      const result = await api.rebuild()
      toast.success(`投影已重建：${result.nodes} 节点 / ${result.edges} 边`)
      await queryClient.invalidateQueries()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '投影重建失败')
    }
  }

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton size='lg' tooltip='重建图谱投影' onClick={onRebuild}>
          <div className='flex size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground'>
            {rebuilding ? (
              <RefreshCw className='size-4 animate-spin' />
            ) : (
              <HardDrive className='size-4' />
            )}
          </div>
          <div className='grid flex-1 text-start text-sm leading-tight'>
            <span className='truncate font-medium'>
              {health.data ? `${health.data.nodes} 个节点` : '连接中…'}
            </span>
            <span className='truncate text-xs text-muted-foreground'>
              {health.data?.projection.stale ? '投影已过期，点此重建' : '投影是最新的'}
            </span>
          </div>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
