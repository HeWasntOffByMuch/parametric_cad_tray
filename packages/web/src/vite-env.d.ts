/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  /** The model listing page this generator belongs to; the header link is
   *  hidden when it is unset. */
  readonly VITE_MODEL_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
