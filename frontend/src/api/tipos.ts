/** Tipos do que a API devolve. Espelham o modelo interno do backend. */

export type TipoEvento =
  | 'text'
  | 'audio'
  | 'image'
  | 'pdf'
  | 'video'
  | 'link'
  | 'document'
  | 'system'
  | 'unknown'

export type StatusProcessamento =
  | 'pending'
  | 'processing'
  | 'done'
  | 'failed'
  | 'unsupported'
  | 'unresolved'

export type StatusJob =
  | 'created'
  | 'uploading'
  | 'uploaded'
  | 'parsing'
  | 'awaiting_confirmation'
  | 'processing'
  | 'partial'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface LinkDoEvento {
  id: string
  eventId: string
  url: string
  status: StatusProcessamento
  title: string | null
  description: string | null
  content: string | null
  error: string | null
}

export interface PaginaPdf {
  page: number
  text: string
  source: string
}

export interface Evento {
  id: string
  index: number
  rawTimestamp: string
  timestamp: string | null
  sender: string | null
  type: TipoEvento
  rawText: string
  caption: string | null
  attachmentName: string | null
  detectedMime: string | null
  processedText: string | null
  processingStatus: StatusProcessamento
  processingError: string | null
  metadata: {
    durationSeconds?: number | null
    pagesCount?: number | null
    frames?: number | null
    fileSize?: number | null
    ocrText?: string | null
    visualDescription?: string | null
    transcript?: string | null
    pages?: PaginaPdf[] | null
    mimeMismatch?: { extension: string; detected: string } | null
    mediaOmitted?: boolean | null
    edited?: boolean | null
    forwarded?: boolean | null
    deleted?: boolean | null
  }
  links: LinkDoEvento[]
}

export interface CoberturaCategoria {
  total: number
  done: number
  failed: number
  pending: number
  unsupported: number
  unresolved: number
  complete: boolean
}

export interface Job {
  id: string
  status: StatusJob
  createdAt: string | null
  updatedAt: string | null
  originalFilename: string | null
  zipSize: number
  error: string | null
  warnings: { code: string; message: string; detail?: string | null }[]
  inventory: {
    text: number
    audio: number
    image: number
    pdf: number
    video: number
    document: number
    system: number
    unknown: number
    links: number
    attachmentsReferenced: number
    attachmentsMatched: number
    attachmentsUnresolved: number
    orphanFiles: number
    orphanNames: string[]
  }
  coverage: {
    categories: Record<string, CoberturaCategoria>
    overallTotal: number
    overallDone: number
    percent: number
    complete: boolean
  }
  estimate: {
    breakdown: Record<string, number>
    audio_seconds: number
    images: number
    pdf_pages: number
    video_seconds: number
    video_frames: number
    links: number
    total_usd: number
    exceeds_cap: boolean
    cap_usd: number
    notes: string[]
  } | null
  cost: Record<string, number> & { totalUsd: number }
  confirmed: boolean
  conversationStart: string | null
  conversationEnd: string | null
  eventCount: number
  metadata: Record<string, unknown>
  schemaVersion: number
}

export interface ConfiguracaoPublica {
  appName: string
  appShortName: string
  appDescription: string
  accessGate: boolean
  aiEnabled: boolean
  uploadChunkBytes: number
  maxZipMb: number
  maxJobCostUsd: number
  jobRetentionHours: number
  autoConfirmProcessing: boolean
  authenticated: boolean
  storageMode: 'local' | 'supabase'
  ffmpegAvailable: boolean
  videoSupported: boolean
}
