/** Acompanhamento do job pelo servidor: o processamento não depende da aba aberta. */

import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../api/cliente'
import type { Evento, Job } from '../api/tipos'

const ESTADOS_EM_ANDAMENTO = new Set(['uploaded', 'parsing', 'processing'])

export function useJob(jobId: string | null, intervaloMs = 2000, empurrar = false) {
  const [job, setJob] = useState<Job | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(false)
  const temporizador = useRef<number | null>(null)

  const atualizar = useCallback(async () => {
    if (!jobId) return null
    try {
      const atual = await api.job(jobId)
      setJob(atual)
      setErro(null)
      return atual
    } catch (falha) {
      setErro((falha as Error).message)
      return null
    }
  }, [jobId])

  useEffect(() => {
    if (!jobId) {
      setJob(null)
      return
    }
    let ativo = true
    setCarregando(true)

    const rodar = async () => {
      let atual = await atualizar()
      if (!ativo) return
      setCarregando(false)

      // Quando o servidor não tem processo de fundo (Vercel), é o aplicativo que
      // pede o próximo pedaço de trabalho a cada volta.
      if (atual && empurrar && atual.status === 'processing') {
        try {
          await api.tick(atual.id)
        } catch {
          /* o agendamento automático continua de qualquer forma */
        }
        if (!ativo) return
        atual = await atualizar()
      }

      if (atual && ESTADOS_EM_ANDAMENTO.has(atual.status)) {
        temporizador.current = window.setTimeout(rodar, intervaloMs)
      }
    }
    rodar()

    return () => {
      ativo = false
      if (temporizador.current) window.clearTimeout(temporizador.current)
    }
  }, [jobId, intervaloMs, atualizar, empurrar])

  return { job, erro, carregando, atualizar }
}

export function useEventos(jobId: string | null, filtros: { type: string; search: string }) {
  const [eventos, setEventos] = useState<Evento[]>([])
  const [total, setTotal] = useState(0)
  const [carregando, setCarregando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)

  const buscar = useCallback(async () => {
    if (!jobId) return
    setCarregando(true)
    try {
      const resposta = await api.eventos(jobId, filtros)
      setEventos(resposta.events)
      setTotal(resposta.total)
      setErro(null)
    } catch (falha) {
      setErro((falha as Error).message)
    } finally {
      setCarregando(false)
    }
  }, [jobId, filtros.type, filtros.search])

  useEffect(() => {
    buscar()
  }, [buscar])

  return { eventos, total, carregando, erro, recarregar: buscar }
}
