import { Outlet } from '@tanstack/react-router'
import { getCookie } from '@/lib/cookies'
import { cn } from '@/lib/utils'
import { LayoutProvider } from '@/context/layout-provider'
import { SearchProvider } from '@/context/search-provider'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { AppSidebar } from '@/components/layout/app-sidebar'
import { AppFooter } from '@/components/layout/app-footer'
import { SkipToMain } from '@/components/skip-to-main'

type AppLayoutProps = {
  children?: React.ReactNode
}

/**
 * 应用外壳：侧栏 + 内容区。memhub 没有登录态，所以这里不做路由守卫，
 * 守卫由 kb-api 只监听回环地址这一事实承担。
 */
export function AppLayout({ children }: AppLayoutProps) {
  const defaultOpen = getCookie('sidebar_state') !== 'false'
  return (
    <SearchProvider>
      <LayoutProvider>
        <SidebarProvider defaultOpen={defaultOpen}>
          <SkipToMain />
          <AppSidebar />
          <SidebarInset
            className={cn(
              '@container/content',
              'has-data-[layout=fixed]:h-svh',
              'peer-data-[variant=inset]:has-data-[layout=fixed]:h-[calc(100svh-(var(--spacing)*4))]',
            )}
          >
            {children ?? <Outlet />}
            <AppFooter />
          </SidebarInset>
        </SidebarProvider>
      </LayoutProvider>
    </SearchProvider>
  )
}
