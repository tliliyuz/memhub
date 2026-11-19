import { type QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, Outlet } from '@tanstack/react-router'
import { Toaster } from '@/components/ui/sonner'
import { NavigationProgress } from '@/components/navigation-progress'
import { GeneralErrorPage, NotFoundPage } from '@/components/error-pages'

export const Route = createRootRouteWithContext<{
  queryClient: QueryClient
}>()({
  component: () => (
    <>
      <NavigationProgress />
      <Outlet />
      <Toaster duration={5000} />
    </>
  ),
  notFoundComponent: NotFoundPage,
  errorComponent: ({ error }) => (
    <GeneralErrorPage error={error instanceof Error ? error : new Error(String(error))} />
  ),
})
