interface ImportMetaEnv {
  readonly VITE_API_URL: string
  readonly VITE_CHAIN_ID: string
  [key: string]: string | undefined
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
