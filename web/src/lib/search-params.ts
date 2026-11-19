import { z } from 'zod'

/**
 * 多选筛选参数的 schema。
 *
 * 坑：TanStack Router 解析 URL 时，`?brand=H%26M` 得到的是**字符串**，
 * 只有重复参数（`?brand=a&brand=b`）才是数组。直接写 `z.array(z.enum(...))`
 * 会在单值时报错，再被 `.catch([])` 静默吞成空数组 —— 表现就是
 * 「链接里明明带了筛选条件，表格却还是全量」。
 *
 * 这里统一把单值归一化为单元素数组，两种写法都能用。
 */
export function csvEnum<T extends string>(values: readonly T[]) {
  return z
    .preprocess(
      (raw) => {
        if (Array.isArray(raw)) return raw
        if (typeof raw === 'string' && raw.trim() !== '') return [raw]
        return []
      },
      z.array(z.enum(values as readonly [T, ...T[]])).catch([])
    )
    .optional()
}

/** 单个字符串筛选项（搜索框），同样容忍重复参数带来的数组。 */
export function singleString() {
  return z
    .preprocess((raw) => {
      if (Array.isArray(raw)) return typeof raw[0] === 'string' ? raw[0] : ''
      return typeof raw === 'string' ? raw : ''
    }, z.string().catch(''))
    .optional()
}

/**
 * 多选的自由文本筛选项（如搜索词）。
 *
 * 取值来自真实数据而非固定枚举，因此不做枚举校验；格式归一与 `csvEnum` 一致。
 */
export function csvString() {
  return z
    .preprocess((raw) => {
      if (Array.isArray(raw)) return raw
      if (typeof raw === 'string' && raw.trim() !== '') return [raw]
      return []
    }, z.array(z.string()).catch([]))
    .optional()
}
