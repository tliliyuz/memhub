/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** explorer 地址；默认由 kb-api 托管的 127.0.0.1:8703。 */
  readonly VITE_GRAPH_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
