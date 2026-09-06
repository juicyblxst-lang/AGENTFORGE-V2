/// <reference types="vite/client" />

interface ImportMeta {
  readonly env: ImportMetaEnv
}

interface ImportMetaEnv {
  readonly VITE_API_URL: string
  readonly VITE_CHAIN_ID: string
  [key: string]: string | undefined
}
