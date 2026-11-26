import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { HardDrive, LogOut } from 'lucide-react'
import { api } from '@/lib/api'
import { Button } from '../ui/button'
import { SidebarMenu, SidebarMenuItem } from '@/components/ui/sidebar'

/**
 * 侧栏底部：登录身份（GitHub，经 oauth2-proxy）——头像 + 用户名 + 退出登录。
 * 本地直连（没有认证网关注入身份）时退回原「本地直连」占位，不放退出按钮。
 */
export function NavUser() {
  const me = useQuery({ queryKey: ['me'], queryFn: api.me })

  const user = me.data?.user ?? null
  const avatarUrl = me.data?.avatar_url ?? null
  const authenticated = me.data?.authenticated ?? false
  // 头像走 githubusercontent，被墙 / 离线时 img 会破图；失败后退回占位图标。
  const [avatarFailed, setAvatarFailed] = useState(false)

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <div className='flex items-center gap-2 rounded-md px-2 py-1.5'>
          {authenticated && avatarUrl && !avatarFailed ? (
            <img
              src={avatarUrl}
              alt={user ?? ''}
              className='size-8 rounded-lg object-cover'
              referrerPolicy='no-referrer'
              onError={() => setAvatarFailed(true)}
            />
          ) : (
            <div className='flex size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground'>
              <HardDrive className='size-4' />
            </div>
          )}
          <div className='grid flex-1 text-start text-sm leading-tight'>
            <span className='truncate font-medium'>{user ?? '本地直连'}</span>
            <span className='truncate text-xs text-muted-foreground'>
              {authenticated ? 'GitHub 登录' : '未经过认证网关'}
            </span>
          </div>
          {authenticated ? (
            <Button
              variant='ghost'
              size='icon'
              className='size-7 text-muted-foreground'
              title='退出登录'
              aria-label='退出登录'
              onClick={() => {
                // 不跳回受保护的首页，否则 nginx 会立即重新发起 GitHub 登录。
                window.location.assign('/oauth2/sign_out?rd=/oauth2/sign_in')
              }}
            >
              <LogOut className='size-4' />
            </Button>
          ) : null}
        </div>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
