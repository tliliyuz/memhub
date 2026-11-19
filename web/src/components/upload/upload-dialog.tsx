/**
 * 上传文档弹窗：选择知识库 → 多选/拖拽文件 → 入队 → 轮询批次状态。
 *
 * 上传只把文件送进提炼队列（见 ADR-0006），201 只代表「已入队」；
 * 抽取由 worker 异步完成，且只在时间窗口内搬运，白天长时间 queued 是正常排队。
 */

import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  FileText,
  Loader2,
  Upload,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  ApiError,
  api,
  type UploadFileStatus,
  type UploadRejected,
  type UploadResult,
} from '@/lib/api'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

const MAX_FILES = 20
const MAX_CHARS = 60_000

const STATUS_LABELS: Record<UploadFileStatus, string> = {
  queued: '已入队',
  processed: '已提炼',
  failed: '提炼失败',
  missing: '文件缺失',
}

const REASON_LABELS: Record<string, string> = {
  unsupported_type: '仅支持 .md / .txt / .jsonl',
  not_utf8: '不是 UTF-8 文本',
  empty: '空文件',
  too_large: `超过 ${MAX_CHARS.toLocaleString('en-US')} 字符`,
  invalid_name: '文件名非法',
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function UploadDialog() {
  const [open, setOpen] = useState(false)
  const [project, setProject] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [dragging, setDragging] = useState(false)
  const [result, setResult] = useState<UploadResult | null>(null)
  const [batchId, setBatchId] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  const projects = useQuery({ queryKey: ['projects'], queryFn: api.projects })
  const projectItems = projects.data?.items ?? []

  const upload = useMutation({
    mutationFn: () => api.uploadDocuments(project, files),
    onSuccess: (data) => {
      setResult(data)
      if (data.accepted.length > 0) setBatchId(data.batch_id)
      if (data.rejected.length > 0) {
        toast.warning(`${data.rejected.length} 个文件未通过校验`)
      } else {
        toast.success(`已入队 ${data.accepted.length} 个文件`)
      }
    },
    onError: () => {
      // 具体原因（逐文件 rejected、队列满、未配置 DATA_DIR）在弹窗里展示。
    },
  })

  const batch = useQuery({
    queryKey: ['upload-batch', batchId],
    queryFn: () => api.uploadStatus(batchId as string),
    enabled: Boolean(batchId),
    refetchInterval: (query) => {
      const data = query.state.data
      return data && data.counts.queued > 0 ? 5000 : false
    },
  })

  const addFiles = (incoming: File[]) => {
    setFiles((previous) => {
      const merged = [...previous]
      for (const file of incoming) {
        if (!merged.some((item) => item.name === file.name && item.size === file.size)) {
          merged.push(file)
        }
      }
      if (merged.length > MAX_FILES) {
        toast.warning(`单批最多 ${MAX_FILES} 个文件，多余的已忽略`)
        return merged.slice(0, MAX_FILES)
      }
      return merged
    })
  }

  const handleOpenChange = (next: boolean) => {
    setOpen(next)
    if (next) return
    const processed = batch.data?.counts.processed ?? 0
    setProject('')
    setFiles([])
    setResult(null)
    setBatchId(null)
    upload.reset()
    // 已提炼过节点：关闭时刷新列表，节点数/更新时间才会变。
    if (processed > 0) void queryClient.invalidateQueries()
  }

  const error = upload.error instanceof ApiError ? upload.error : null
  const errorData = (error?.data ?? {}) as {
    rejected?: UploadRejected[]
    used?: number
    limit?: number
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button size='sm' variant='outline'>
          <Upload /> 上传文档
        </Button>
      </DialogTrigger>
      <DialogContent className='max-h-[85vh] overflow-y-auto sm:max-w-2xl'>
        <DialogHeader>
          <DialogTitle>上传文档</DialogTitle>
          <DialogDescription>
            文件进入提炼队列，由 worker 自动抽取成带类型和关系的节点（候选层级）。
            接口返回「已入队」不代表已提炼。
          </DialogDescription>
        </DialogHeader>

        {result ? (
          <UploadResultView
            result={result}
            batchFiles={batch.data?.files}
            counts={batch.data?.counts}
            polling={batch.data ? batch.data.counts.queued > 0 : Boolean(batchId)}
          />
        ) : (
          <div className='space-y-4'>
            <div className='space-y-1.5'>
              <Label>目标知识库</Label>
              <Select value={project} onValueChange={setProject}>
                <SelectTrigger>
                  <SelectValue placeholder='选择知识库' />
                </SelectTrigger>
                <SelectContent>
                  {projectItems.map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.name}（{item.id}）
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {!projects.isLoading && projectItems.length === 0 && (
                <p className='text-xs text-destructive'>
                  还没有知识库，先新建一个再上传。
                </p>
              )}
            </div>

            <div className='space-y-1.5'>
              <Label>文件</Label>
              <div
                role='button'
                tabIndex={0}
                onClick={() => inputRef.current?.click()}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    inputRef.current?.click()
                  }
                }}
                onDragOver={(event) => {
                  event.preventDefault()
                  setDragging(true)
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => {
                  event.preventDefault()
                  setDragging(false)
                  addFiles(Array.from(event.dataTransfer.files))
                }}
                className={cn(
                  'flex cursor-pointer flex-col items-center gap-2 rounded-md border border-dashed px-4 py-8 text-center text-sm transition-colors',
                  dragging ? 'border-primary bg-accent/60' : 'border-input hover:bg-accent/30',
                )}
              >
                <Upload className='size-6 text-muted-foreground' />
                <span>点击选择或拖拽文件到这里</span>
                <span className='text-xs text-muted-foreground'>
                  支持 .md / .txt / .jsonl，UTF-8，单文件 ≤ 60000 字符，单批 ≤ {MAX_FILES} 个
                </span>
              </div>
              <input
                ref={inputRef}
                type='file'
                multiple
                accept='.md,.txt,.jsonl,text/markdown,text/plain'
                className='hidden'
                onChange={(event) => {
                  addFiles(Array.from(event.target.files ?? []))
                  event.target.value = ''
                }}
              />

              {files.length > 0 && (
                <ul className='divide-y rounded-md border'>
                  {files.map((file) => (
                    <li
                      key={`${file.name}-${file.size}`}
                      className='flex items-center gap-2 px-3 py-2 text-sm'
                    >
                      <FileText className='size-4 shrink-0 text-muted-foreground' />
                      <span className='min-w-0 flex-1 truncate' title={file.name}>
                        {file.name}
                      </span>
                      <span className='shrink-0 text-xs text-muted-foreground'>
                        {formatBytes(file.size)}
                      </span>
                      <Button
                        type='button'
                        variant='ghost'
                        size='icon'
                        className='size-6'
                        onClick={() =>
                          setFiles((previous) =>
                            previous.filter((item) => item !== file),
                          )
                        }
                        aria-label={`移除 ${file.name}`}
                      >
                        <X className='size-3.5' />
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {error && (
              <div className='rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm'>
                <div className='flex items-start gap-2'>
                  <AlertCircle className='mt-0.5 size-4 shrink-0 text-destructive' />
                  <div className='min-w-0 space-y-1'>
                    <p className='text-destructive'>{error.message}</p>
                    {errorData.rejected && errorData.rejected.length > 0 && (
                      <ul className='space-y-0.5 text-xs text-muted-foreground'>
                        {errorData.rejected.map((item, index) => (
                          <li key={`${item.name}-${index}`}>
                            {item.name || '（无文件名）'}：
                            {REASON_LABELS[item.reason] ?? item.reason}
                          </li>
                        ))}
                      </ul>
                    )}
                    {typeof errorData.limit === 'number' && (
                      <p className='text-xs text-muted-foreground'>
                        队列已用 {formatBytes(errorData.used ?? 0)} /{' '}
                        {formatBytes(errorData.limit)}，稍后重试。
                      </p>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          {result ? (
            <>
              <Button
                variant='outline'
                onClick={() => {
                  setResult(null)
                  setBatchId(null)
                  setFiles([])
                  upload.reset()
                }}
              >
                再传一批
              </Button>
              <Button onClick={() => handleOpenChange(false)}>完成</Button>
            </>
          ) : (
            <>
              <Button variant='outline' onClick={() => handleOpenChange(false)}>
                取消
              </Button>
              <Button
                disabled={!project || files.length === 0 || upload.isPending}
                onClick={() => upload.mutate()}
              >
                {upload.isPending ? (
                  <>
                    <Loader2 className='animate-spin' /> 上传中…
                  </>
                ) : (
                  <>
                    <Upload /> 上传 {files.length > 0 ? `${files.length} 个文件` : ''}
                  </>
                )}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function UploadResultView({
  result,
  batchFiles,
  counts,
  polling,
}: {
  result: UploadResult
  batchFiles?: { name: string; status: UploadFileStatus; attempts?: number }[]
  counts?: Record<UploadFileStatus, number>
  polling: boolean
}) {
  const rows: { name: string; status: UploadFileStatus; attempts?: number }[] =
    batchFiles ??
    result.accepted.map((file) => ({ name: file.name, status: 'queued' as const }))

  return (
    <div className='space-y-4'>
      <div className='flex flex-wrap gap-x-4 gap-y-1 text-sm'>
        <span className='flex items-center gap-1.5'>
          <CheckCircle2 className='size-4 text-emerald-600' />
          已入队 {result.accepted.length}
        </span>
        {result.rejected.length > 0 && (
          <span className='flex items-center gap-1.5 text-destructive'>
            <AlertCircle className='size-4' />
            被拒 {result.rejected.length}
          </span>
        )}
        {counts && (
          <span className='flex items-center gap-1.5 text-muted-foreground'>
            {polling ? (
              <Loader2 className='size-4 animate-spin' />
            ) : (
              <Clock3 className='size-4' />
            )}
            队列中 {counts.queued} · 已提炼 {counts.processed} · 失败 {counts.failed}
            {counts.missing > 0 && ` · 缺失 ${counts.missing}`}
          </span>
        )}
      </div>

      {rows.length > 0 && (
        <ul className='divide-y rounded-md border'>
          {rows.map((file) => (
            <li
              key={file.name}
              className='flex items-center gap-2 px-3 py-2 text-sm'
            >
              <FileText className='size-4 shrink-0 text-muted-foreground' />
              <span className='min-w-0 flex-1 truncate' title={file.name}>
                {file.name}
              </span>
              {file.attempts !== undefined && (
                <span className='shrink-0 text-xs text-muted-foreground'>
                  已重试 {file.attempts} 次
                </span>
              )}
              <Badge
                variant={
                  file.status === 'processed'
                    ? 'default'
                    : file.status === 'failed' || file.status === 'missing'
                      ? 'destructive'
                      : 'secondary'
                }
              >
                {STATUS_LABELS[file.status]}
              </Badge>
            </li>
          ))}
        </ul>
      )}

      {result.rejected.length > 0 && (
        <div className='rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2'>
          <p className='mb-1 text-xs font-medium text-destructive'>未通过校验的文件</p>
          <ul className='space-y-0.5 text-xs text-muted-foreground'>
            {result.rejected.map((item, index) => (
              <li key={`${item.name}-${index}`}>
                {item.name || '（无文件名）'}：{REASON_LABELS[item.reason] ?? item.reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className='text-xs text-muted-foreground'>
        批次 <span className='font-mono'>{result.batch_id.slice(0, 12)}…</span> ·
        新文件进入提炼队列，worker 在夜间窗口处理，白天长时间停留在「已入队」属正常排队。
      </p>
    </div>
  )
}
