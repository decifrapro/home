import { useEffect, useState } from 'react'

import { api } from '../api/cliente'
import type { Job } from '../api/tipos'
import { NOME_POR_STATUS_DO_JOB, formatarData, formatarTamanho } from './comum'

/**
 * Conversas já enviadas, de qualquer aparelho.
 *
 * É o que liga o celular ao computador sem nenhuma configuração: o corretor
 * manda a conversa pelo iPhone e depois abre o aplicativo no computador, onde
 * ela já está esperando — a leitura de uma transcrição longa é bem melhor na
 * tela grande.
 */
export function ListaDeAtendimentos({ aoAbrir }: { aoAbrir: (jobId: string) => void }) {
  const [jobs, setJobs] = useState<Job[]>([])
  const [carregando, setCarregando] = useState(true)

  useEffect(() => {
    let ativo = true
    api
      .listarJobs()
      .then((resposta) => ativo && setJobs(resposta.jobs))
      .catch(() => ativo && setJobs([]))
      .finally(() => ativo && setCarregando(false))
    return () => {
      ativo = false
    }
  }, [])

  if (carregando || jobs.length === 0) return null

  return (
    <section className="cartao" aria-labelledby="titulo-atendimentos">
      <h2 id="titulo-atendimentos">Conversas enviadas</h2>
      <p className="fraco">
        Enviou pelo celular? Ela aparece aqui no computador também — é a mesma conta.
      </p>

      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {jobs.map((job) => (
          <li key={job.id}>
            <button
              type="button"
              className="atendimento"
              onClick={() => aoAbrir(job.id)}
              aria-label={`Abrir ${job.originalFilename ?? 'conversa'}`}
            >
              <span className="atendimento__nome">{job.originalFilename ?? 'Conversa'}</span>
              <span className="fraco">
                {formatarData(job.createdAt)}
                {job.eventCount > 0 && ` · ${job.eventCount} mensagens`}
                {job.zipSize > 0 && ` · ${formatarTamanho(job.zipSize)}`}
              </span>
              <span className={`selo ${seloDoStatus(job)}`}>
                {job.status === 'completed'
                  ? 'pronta'
                  : job.status === 'partial'
                    ? `${job.coverage.percent}% decifrado`
                    : NOME_POR_STATUS_DO_JOB[job.status]}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

function seloDoStatus(job: Job): string {
  if (job.status === 'failed') return 'selo--falha'
  if (job.status === 'completed') return 'selo--decifrado'
  if (job.status === 'partial') return 'selo--decifrado'
  return 'selo--pendente'
}
