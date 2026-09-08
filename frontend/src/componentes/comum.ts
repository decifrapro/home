/** Rótulos, ícones e formatações compartilhados pela interface. */

import type { Evento, StatusProcessamento, TipoEvento } from '../api/tipos'

export const ICONE_POR_TIPO: Record<TipoEvento, string> = {
  text: '💬',
  audio: '🎙',
  image: '🖼',
  pdf: '📄',
  video: '🎥',
  link: '🔗',
  document: '📎',
  system: '⚙',
  unknown: '❔',
}

export const NOME_POR_TIPO: Record<TipoEvento, string> = {
  text: 'Texto',
  audio: 'Áudio',
  image: 'Imagem',
  pdf: 'PDF',
  video: 'Vídeo',
  link: 'Link',
  document: 'Documento',
  system: 'Sistema',
  unknown: 'Não identificado',
}

export const NOME_POR_CATEGORIA: Record<string, string> = {
  text: 'Texto',
  audio: 'Áudios',
  image: 'Imagens',
  pdf: 'PDFs',
  video: 'Vídeos',
  document: 'Documentos',
  link: 'Links',
}

export const NOME_POR_STATUS: Record<StatusProcessamento, string> = {
  pending: 'pendente',
  processing: 'processando',
  done: 'decifrado',
  failed: 'falhou',
  unsupported: 'não suportado',
  unresolved: 'arquivo não associado',
}

export const NOME_POR_STATUS_DO_JOB: Record<string, string> = {
  created: 'criado',
  uploading: 'enviando',
  uploaded: 'enviado',
  parsing: 'lendo a conversa',
  awaiting_confirmation: 'aguardando sua confirmação',
  processing: 'processando',
  partial: 'concluído em parte',
  completed: 'concluído',
  failed: 'falhou',
  cancelled: 'cancelado',
}

export function classeDoEvento(evento: Evento): string {
  if (evento.processingStatus === 'failed') return 'evento evento--falha'
  if (evento.processingStatus === 'done' && evento.type !== 'text' && evento.type !== 'system') {
    return 'evento evento--decifrado'
  }
  if (evento.processingStatus === 'pending' || evento.processingStatus === 'processing') {
    return 'evento evento--pendente'
  }
  return 'evento'
}

export function formatarTamanho(bytes: number): string {
  if (!bytes) return '0 B'
  const unidades = ['B', 'KB', 'MB', 'GB']
  const indice = Math.min(unidades.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)))
  return `${(bytes / 1024 ** indice).toFixed(indice === 0 ? 0 : 1)} ${unidades[indice]}`
}

export function formatarDuracao(segundos?: number | null): string {
  if (!segundos && segundos !== 0) return ''
  const minutos = Math.floor(segundos / 60)
  const resto = Math.round(segundos % 60)
  return minutos ? `${minutos} min ${resto}s` : `${resto}s`
}

export function formatarData(iso: string | null): string {
  if (!iso) return ''
  const data = new Date(iso)
  if (Number.isNaN(data.getTime())) return ''
  return data.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
}

export function formatarDinheiro(valor: number): string {
  return `US$ ${valor.toFixed(valor < 1 ? 4 : 2)}`
}
