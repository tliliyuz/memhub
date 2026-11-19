/**
 * 统一的「返回上一级」按钮。浏览器没有历史可退时（直接打开深层链接），
 * 退回到调用方给的 fallbackTo。
 */

import { useRouter } from '@tanstack/react-router'
import { ArrowLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'

export function BackButton({ fallbackTo = '/' }: { fallbackTo?: string }) {
  const router = useRouter()
  return (
    <Button
      variant='ghost'
      size='sm'
      className='h-6 gap-1 px-1.5 text-xs text-muted-foreground'
      onClick={() => {
        if (router.history.canGoBack()) router.history.back()
        else router.history.push(fallbackTo)
      }}
    >
      <ArrowLeft className='size-3.5' />
      返回
    </Button>
  )
}
