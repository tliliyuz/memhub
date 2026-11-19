import { useNavigate, useRouter } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'

type ErrorPageProps = {
  code: string
  title: string
  detail?: string
}

function ErrorPage({ code, title, detail }: ErrorPageProps) {
  const navigate = useNavigate()
  const { history } = useRouter()
  return (
    <div className='flex h-svh w-full flex-col items-center justify-center gap-2'>
      <h1 className='text-[7rem] leading-tight font-bold'>{code}</h1>
      <span className='font-medium'>{title}</span>
      {detail && (
        <p className='max-w-xl text-center text-sm break-all text-muted-foreground'>
          {detail}
        </p>
      )}
      <div className='mt-6 flex gap-4'>
        <Button variant='outline' onClick={() => history.go(-1)}>
          返回
        </Button>
        <Button onClick={() => navigate({ to: '/' })}>回到概览</Button>
      </div>
    </div>
  )
}

export function NotFoundPage() {
  return <ErrorPage code='404' title='页面不存在' />
}

export function GeneralErrorPage({ error }: { error: Error }) {
  return (
    <ErrorPage
      code='500'
      title='页面渲染出错'
      detail={`${error.name}: ${error.message}`}
    />
  )
}
