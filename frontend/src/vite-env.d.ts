/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend origin, no trailing slash. Empty in dev, where Vite proxies /api. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
