/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_NODUS_WS_URL?: string
  readonly VITE_NODUS_API_KEY?: string
  readonly VITE_NODUS_DEMO?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
