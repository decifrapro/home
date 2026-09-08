/** Cliente HTTP da API. Nenhum segredo mora aqui — a chave de IA fica no servidor. */

import type { ConfiguracaoPublica, Evento, Job } from './tipos'

export class ErroDaApi extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ErroDaApi'
  }
}

async function pedir<T>(caminho: string, init?: RequestInit): Promise<T> {
  const resposta = await fetch(caminho, {
    credentials: 'same-origin',
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof Blob) ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })
  if (!resposta.ok) {
    let detalhe = `Falha na requisição (${resposta.status})`
    try {
      const corpo = await resposta.json()
      if (corpo?.detail) detalhe = String(corpo.detail)
    } catch {
      /* resposta sem corpo JSON */
    }
    throw new ErroDaApi(detalhe, resposta.status)
  }
  if (resposta.status === 204) return undefined as T
  return (await resposta.json()) as T
}

export const api = {
  configuracao: () => pedir<ConfiguracaoPublica>('/api/config'),

  entrar: (senha: string) =>
    pedir<{ authenticated: boolean }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ password: senha }),
    }),

  sair: () => pedir<{ authenticated: boolean }>('/api/auth/logout', { method: 'POST' }),

  criarJob: () => pedir<Job>('/api/jobs', { method: 'POST' }),

  job: (id: string) => pedir<Job>(`/api/jobs/${id}`),

  listarJobs: () => pedir<{ jobs: Job[] }>('/api/jobs'),

  eventos: (id: string, filtros: { type?: string; search?: string } = {}) => {
    const busca = new URLSearchParams()
    if (filtros.type && filtros.type !== 'all') busca.set('type', filtros.type)
    if (filtros.search) busca.set('search', filtros.search)
    const sufixo = busca.toString() ? `?${busca}` : ''
    return pedir<{ total: number; events: Evento[] }>(`/api/jobs/${id}/events${sufixo}`)
  },

  confirmar: (id: string) => pedir<{ status: string }>(`/api/jobs/${id}/confirm`, { method: 'POST' }),

  /** Empurra um pedaço do processamento (modo Vercel, sem processo de fundo). */
  tick: (id: string) =>
    pedir<{ status: string; processados: number; restantes: number }>(`/api/jobs/${id}/tick`, {
      method: 'POST',
    }),

  cancelar: (id: string) => pedir<Job>(`/api/jobs/${id}/cancel`, { method: 'POST' }),

  reprocessarTudo: (id: string) => pedir<{ status: string }>(`/api/jobs/${id}/retry`, { method: 'POST' }),

  reprocessarEvento: (id: string, eventoId: string) =>
    pedir<{ status: string }>(`/api/jobs/${id}/events/${eventoId}/retry`, { method: 'POST' }),

  apagar: (id: string) => pedir<{ deleted: boolean }>(`/api/jobs/${id}`, { method: 'DELETE' }),

  exportar: async (id: string, formato: 'txt' | 'md' | 'json') => {
    const resposta = await fetch(`/api/jobs/${id}/export/${formato}`, { credentials: 'same-origin' })
    if (!resposta.ok) throw new ErroDaApi('Não foi possível gerar o arquivo.', resposta.status)
    return resposta.text()
  },

  urlDeExport: (id: string, formato: 'txt' | 'md' | 'json') => `/api/jobs/${id}/export/${formato}`,
}
