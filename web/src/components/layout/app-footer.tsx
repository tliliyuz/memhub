const ICP_HREF = 'https://beian.miit.gov.cn/'
const ICP_TEXT = '鄂ICP备2025150807号-2'
// 公安联网备案查询（新平台）；code 与备案号数字部分一致。
const PSB_HREF = 'https://beian.mps.gov.cn/#/query/webSearch?code=42110002000542'
const PSB_TEXT = '鄂公网安备42110002000542号'

/**
 * 备案信息页脚：按工信部与公安联网备案要求，在各页面底部展示备案号并链接到
 * 对应查询平台首页/查询页。
 */
export function AppFooter() {
  return (
    <footer className='shrink-0 border-t px-4 py-3 text-center text-xs text-muted-foreground'>
      <div className='flex flex-wrap items-center justify-center gap-x-4 gap-y-1'>
        <a
          href={ICP_HREF}
          target='_blank'
          rel='noopener noreferrer'
          className='transition-colors hover:text-foreground'
        >
          {ICP_TEXT}
        </a>
        <a
          href={PSB_HREF}
          target='_blank'
          rel='noopener noreferrer'
          className='transition-colors hover:text-foreground'
        >
          {PSB_TEXT}
        </a>
      </div>
    </footer>
  )
}
