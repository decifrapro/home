import { useCallback, useEffect, useState } from 'react'

import { api } from './api/cliente'
import type { ConfiguracaoPublica } from './api/tipos'
import { InstalarApp } from './componentes/InstalarApp'
import { Login } from './componentes/Login'
import { BotaoDeTema, useTema } from './componentes/Tema'
import { TelaProcessando } from './componentes/TelaProcessando'
import { TelaTimeline } from './componentes/TelaTimeline'
import { TelaUpload } from './componentes/TelaUpload'
import { useJob } from './hooks/useJob'

function lerJobDaUrl(): string | null {
  return new URLSearchParams(window.location.search).get('atendimento')
}

function escreverJobNaUrl(jobId: string | null) {
  const url = new URL(window.location.href)
  if (jobId) url.searchParams.set('atendimento', jobId)
  else url.searchParams.delete('atendimento')
  window.history.replaceState({}, '', url)
}

export function App() {
  const [configuracao, setConfiguracao] = useState<ConfiguracaoPublica | null>(null)
  const [jobId, setJobId] = useState<string | null>(lerJobDaUrl)
  const [verConversa, setVerConversa] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  const { tema, alternar } = useTema()
  const { job, atualizar } = useJob(jobId, 2000, configuracao?.storageMode === 'supabase')

  const carregarConfiguracao = useCallback(async () => {
    try {
      setConfiguracao(await api.configuracao())
    } catch {
      setConfiguracao(null)
    }
  }, [])

  useEffect(() => {
    carregarConfiguracao()
  }, [carregarConfiguracao])

  useEffect(() => {
    escreverJobNaUrl(jobId)
  }, [jobId])

  if (!configuracao) {
    return (
      <div className="pagina">
        <p className="fraco">Carregando…</p>
      </div>
    )
  }

  if (configuracao.accessGate && !configuracao.authenticated) {
    return <Login appName={configuracao.appName} aoEntrar={carregarConfiguracao} />
  }

  const mostrarTimeline =
    job && (verConversa || ['partial', 'completed', 'cancelled'].includes(job.status))

  return (
    <>
      <header className="cabecalho">
        <div className="cabecalho__marca">
          <img src="/icon.svg" alt="" width={28} height={28} />
          <span>{configuracao.appName}</span>
        </div>
        <div className="cabecalho__acoes">
          <BotaoDeTema tema={tema} aoAlternar={alternar} />
          {jobId && (
            <button
              type="button"
              className="botao botao--secundario botao--pequeno"
              onClick={() => {
                setJobId(null)
                setVerConversa(false)
              }}
            >
              Nova conversa
            </button>
          )}
        </div>
      </header>

      <div className="pagina" style={{ paddingBottom: 0 }}>
        <InstalarApp />
      </div>

      {!jobId && (
        <TelaUpload
          configuracao={configuracao}
          aoEnviar={(id) => {
            setJobId(id)
            setVerConversa(false)
          }}
        />
      )}

      {jobId && job && !mostrarTimeline && (
        <TelaProcessando
          job={job}
          ocupado={ocupado}
          aoConfirmar={async () => {
            setOcupado(true)
            try {
              await api.confirmar(job.id)
              await atualizar()
            } finally {
              setOcupado(false)
            }
          }}
          aoCancelar={async () => {
            await api.cancelar(job.id)
            await atualizar()
          }}
          aoVerConversa={() => setVerConversa(true)}
        />
      )}

      {jobId && job && mostrarTimeline && (
        <TelaTimeline
          job={job}
          aoAtualizar={atualizar}
          aoApagar={() => {
            setJobId(null)
            setVerConversa(false)
          }}
        />
      )}

      {jobId && !job && (
        <div className="pagina">
          <p className="fraco">Carregando o atendimento…</p>
        </div>
      )}
    </>
  )
}
