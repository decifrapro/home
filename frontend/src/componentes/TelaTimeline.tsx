import { useMemo, useState } from 'react'

import { api } from '../api/cliente'
import type { Job, TipoEvento } from '../api/tipos'
import { useEventos } from '../hooks/useJob'
import { Cobertura } from './Cobertura'
import { EventoCartao } from './EventoCartao'
import { Inventario } from './Inventario'
import { NOME_POR_TIPO, formatarData } from './comum'

/**
 * Copia um texto que ainda vai ser buscado no servidor.
 *
 * O Safari do iPhone só deixa escrever na área de transferência enquanto o toque
 * ainda "vale". Como a busca do histórico demora, escrever depois de esperar
 * seria bloqueado — por isso entregamos a promessa ao navegador, que é a forma
 * que ele aceita. Nos outros navegadores, o caminho simples continua valendo.
 */
export async function copiarTexto(buscar: () => Promise<string>): Promise<void> {
  const suportaPromessa =
    typeof ClipboardItem !== 'undefined' && typeof navigator.clipboard?.write === 'function'

  if (suportaPromessa) {
    try {
      const item = new ClipboardItem({
        'text/plain': buscar().then((texto) => new Blob([texto], { type: 'text/plain' })),
      })
      await navigator.clipboard.write([item])
      return
    } catch {
      /* alguns navegadores recusam a promessa; segue pelo caminho simples */
    }
  }

  const texto = await buscar()
  await navigator.clipboard.writeText(texto)
}

interface Props {
  job: Job
  aoAtualizar: () => void
  aoApagar: () => void
}

const TIPOS: (TipoEvento | 'all')[] = ['all', 'text', 'audio', 'image', 'pdf', 'video', 'link', 'document']

/** Tela final: a conversa inteira, com filtro, busca, cópia e downloads. */
export function TelaTimeline({ job, aoAtualizar, aoApagar }: Props) {
  const [tipo, setTipo] = useState<TipoEvento | 'all'>('all')
  const [busca, setBusca] = useState('')
  const [mensagem, setMensagem] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const filtros = useMemo(() => ({ type: tipo, search: busca }), [tipo, busca])
  const { eventos, total, carregando, erro, recarregar } = useEventos(job.id, filtros)

  const falhas = Object.values(job.coverage.categories).reduce((soma, item) => soma + item.failed, 0)

  async function copiarHistorico() {
    setOcupado(true)
    try {
      await copiarTexto(() => api.exportar(job.id, 'txt'))
      setMensagem('Histórico copiado. É só colar onde quiser.')
    } catch {
      setMensagem('Não consegui copiar automaticamente. Baixe o TXT e copie de lá.')
    } finally {
      setOcupado(false)
    }
  }

  async function reprocessarTudo() {
    setOcupado(true)
    try {
      await api.reprocessarTudo(job.id)
      setMensagem('Reprocessamento das falhas iniciado.')
      aoAtualizar()
    } catch (falha) {
      setMensagem((falha as Error).message)
    } finally {
      setOcupado(false)
    }
  }

  async function reprocessarEvento(eventoId: string) {
    setOcupado(true)
    try {
      await api.reprocessarEvento(job.id, eventoId)
      setMensagem('Reprocessamento deste item iniciado.')
      setTimeout(() => {
        recarregar()
        aoAtualizar()
      }, 1500)
    } catch (falha) {
      setMensagem((falha as Error).message)
    } finally {
      setOcupado(false)
    }
  }

  async function apagar() {
    if (!window.confirm('Apagar este atendimento? O ZIP, as mídias e os resultados somem do servidor.')) {
      return
    }
    await api.apagar(job.id)
    aoApagar()
  }

  return (
    <div className="pagina">
      <section className="cartao">
        <h1>{job.originalFilename ?? 'Conversa'}</h1>
        <p className="fraco">
          {job.eventCount} eventos · {formatarData(job.conversationStart)} a{' '}
          {formatarData(job.conversationEnd)}
        </p>

        {job.status === 'partial' && (
          <p className="aviso">
            ⚠ Este histórico está incompleto: {job.coverage.overallTotal - job.coverage.overallDone}{' '}
            itens não foram decifrados. O que já está pronto pode ser baixado normalmente.
          </p>
        )}

        {job.warnings.map((aviso) => (
          <p className="aviso" key={aviso.code}>
            {aviso.message}
          </p>
        ))}

        <div className="linha">
          <button type="button" className="botao" onClick={copiarHistorico} disabled={ocupado}>
            Copiar histórico
          </button>
          <a className="botao botao--secundario" href={api.urlDeExport(job.id, 'txt')} download>
            Baixar TXT
          </a>
          <a className="botao botao--secundario" href={api.urlDeExport(job.id, 'md')} download>
            Baixar Markdown
          </a>
          <a className="botao botao--secundario" href={api.urlDeExport(job.id, 'json')} download>
            Baixar JSON
          </a>
          {falhas > 0 && (
            <button type="button" className="botao" onClick={reprocessarTudo} disabled={ocupado}>
              Reprocessar {falhas} falha{falhas > 1 ? 's' : ''}
            </button>
          )}
          <button type="button" className="botao botao--perigo" onClick={apagar}>
            Apagar atendimento
          </button>
        </div>

        {mensagem && (
          <p className="fraco" role="status" style={{ marginTop: 10 }}>
            {mensagem}
          </p>
        )}
      </section>

      <Cobertura job={job} />
      <Inventario job={job} />

      <div className="filtros">
        <label className="oculto-visualmente" htmlFor="filtro-tipo">
          Filtrar por tipo de mídia
        </label>
        <select id="filtro-tipo" value={tipo} onChange={(evento) => setTipo(evento.target.value as TipoEvento)}>
          {TIPOS.map((valor) => (
            <option key={valor} value={valor}>
              {valor === 'all' ? 'Todos os tipos' : NOME_POR_TIPO[valor]}
            </option>
          ))}
        </select>

        <label className="oculto-visualmente" htmlFor="busca">
          Buscar na conversa
        </label>
        <input
          id="busca"
          type="search"
          placeholder="Buscar na conversa"
          value={busca}
          onChange={(evento) => setBusca(evento.target.value)}
        />
      </div>

      <p className="fraco" aria-live="polite">
        {carregando ? 'Carregando…' : `${total} evento${total === 1 ? '' : 's'} nesta visão.`}
      </p>

      {erro && (
        <p className="aviso aviso--erro" role="alert">
          {erro}
        </p>
      )}

      {eventos.map((evento) => (
        <EventoCartao
          key={evento.id}
          evento={evento}
          aoReprocessar={reprocessarEvento}
          reprocessando={ocupado}
        />
      ))}
    </div>
  )
}
