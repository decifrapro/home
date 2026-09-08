import { useState } from 'react'

import type { Evento } from '../api/tipos'
import {
  ICONE_POR_TIPO,
  NOME_POR_STATUS,
  NOME_POR_TIPO,
  classeDoEvento,
  formatarDuracao,
} from './comum'

interface Props {
  evento: Evento
  aoReprocessar?: (eventoId: string) => void
  reprocessando?: boolean
}

const LIMITE_DE_CONTEUDO_LONGO = 900

/**
 * Um evento da timeline.
 *
 * O que a pessoa escreveu ou enviou fica em cima; o que a IA extraiu fica em
 * bloco separado e rotulado, para não se confundir com o original.
 */
export function EventoCartao({ evento, aoReprocessar, reprocessando }: Props) {
  const decifrado = evento.processingStatus === 'done'
  const falhou = evento.processingStatus === 'failed'
  const ehMidia = evento.type !== 'text' && evento.type !== 'system'

  return (
    <article className={classeDoEvento(evento)} aria-label={`${NOME_POR_TIPO[evento.type]} de ${evento.sender ?? 'sistema'}`}>
      <header className="evento__topo">
        <span aria-hidden="true">{ICONE_POR_TIPO[evento.type]}</span>
        <span className="evento__quem">{evento.sender ?? 'Sistema'}</span>
        <span>{evento.rawTimestamp}</span>
        <span className="selo">{NOME_POR_TIPO[evento.type]}</span>
        {ehMidia && (
          <span
            className={`selo ${
              falhou ? 'selo--falha' : decifrado ? 'selo--decifrado' : 'selo--pendente'
            }`}
          >
            {NOME_POR_STATUS[evento.processingStatus]}
          </span>
        )}
        {evento.metadata.edited && <span className="selo">editada</span>}
        {evento.metadata.forwarded && <span className="selo">encaminhada</span>}
      </header>

      {evento.attachmentName && (
        <p className="fraco" style={{ margin: '6px 0 0' }}>
          Arquivo: {evento.attachmentName}
          {evento.metadata.durationSeconds ? ` · ${formatarDuracao(evento.metadata.durationSeconds)}` : ''}
          {evento.metadata.pagesCount ? ` · ${evento.metadata.pagesCount} páginas` : ''}
        </p>
      )}

      {evento.caption && (
        <div className="evento__original">
          <span className="evento__rotulo">Legenda original</span>
          {evento.caption}
        </div>
      )}

      {!evento.attachmentName && evento.rawText.trim() && (
        <p className="evento__original">{evento.rawText}</p>
      )}

      {decifrado && ehMidia && <ConteudoDecifrado evento={evento} />}

      {evento.links.map((link) => (
        <div className="evento__decifrado" key={link.id}>
          <span className="evento__rotulo">🔗 Link {link.status === 'done' ? 'lido' : NOME_POR_STATUS[link.status]}</span>
          <a href={link.url} target="_blank" rel="noreferrer noopener">
            {link.url}
          </a>
          {link.title && <p style={{ marginTop: 6 }}>{link.title}</p>}
          {link.description && <p className="fraco">{link.description}</p>}
          {link.content && <TextoRecolhivel titulo="Conteúdo da página" texto={link.content} />}
          {link.error && <p className="fraco">{link.error}</p>}
        </div>
      ))}

      {(falhou || evento.processingStatus === 'unresolved' || evento.processingStatus === 'unsupported') &&
        evento.processingError && (
          <div className={falhou ? 'evento__erro' : 'aviso'} role={falhou ? 'alert' : undefined}>
            <strong>{falhou ? '⚠ Falha:' : 'Aviso:'}</strong> {evento.processingError}
            {falhou && aoReprocessar && (
              <p style={{ marginTop: 8, marginBottom: 0 }}>
                <button
                  type="button"
                  className="botao botao--pequeno"
                  onClick={() => aoReprocessar(evento.id)}
                  disabled={reprocessando}
                >
                  {reprocessando ? 'Reprocessando…' : 'Reprocessar este item'}
                </button>
              </p>
            )}
          </div>
        )}

      <DetalhesTecnicos evento={evento} />
    </article>
  )
}

function ConteudoDecifrado({ evento }: { evento: Evento }) {
  const meta = evento.metadata

  if (evento.type === 'audio') {
    return (
      <div className="evento__decifrado">
        <span className="evento__rotulo">🎙 Áudio transcrito</span>
        {evento.processedText}
      </div>
    )
  }

  if (evento.type === 'image') {
    return (
      <div className="evento__decifrado">
        <span className="evento__rotulo">🖼 Imagem analisada</span>
        {meta.ocrText ? (
          <p style={{ whiteSpace: 'pre-wrap' }}>
            <strong>Texto identificado:</strong> {meta.ocrText}
          </p>
        ) : null}
        {meta.visualDescription ? (
          <p style={{ marginBottom: 0 }}>
            <strong>Descrição visual:</strong> {meta.visualDescription}
          </p>
        ) : null}
        {!meta.ocrText && !meta.visualDescription ? evento.processedText : null}
      </div>
    )
  }

  if (evento.type === 'pdf') {
    return (
      <div className="evento__decifrado">
        <span className="evento__rotulo">📄 PDF lido</span>
        <TextoRecolhivel titulo="Conteúdo completo do PDF" texto={evento.processedText ?? ''} />
      </div>
    )
  }

  if (evento.type === 'video') {
    return (
      <div className="evento__decifrado">
        <span className="evento__rotulo">🎥 Vídeo analisado</span>
        {meta.transcript ? (
          <p style={{ whiteSpace: 'pre-wrap' }}>
            <strong>Transcrição do áudio:</strong> {meta.transcript}
          </p>
        ) : null}
        {meta.visualDescription ? (
          <p style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
            <strong>Descrição visual:</strong> {meta.visualDescription}
          </p>
        ) : null}
      </div>
    )
  }

  return (
    <div className="evento__decifrado">
      <span className="evento__rotulo">Conteúdo extraído</span>
      <TextoRecolhivel titulo="Conteúdo completo" texto={evento.processedText ?? ''} />
    </div>
  )
}

/** Conteúdo longo pode ser recolhido na tela — mas continua inteiro no export. */
function TextoRecolhivel({ titulo, texto }: { titulo: string; texto: string }) {
  const [aberto, setAberto] = useState(false)
  if (texto.length <= LIMITE_DE_CONTEUDO_LONGO) {
    return <div style={{ whiteSpace: 'pre-wrap' }}>{texto}</div>
  }
  return (
    <div>
      <div className={aberto ? 'conteudo-longo' : undefined} style={{ whiteSpace: 'pre-wrap' }}>
        {aberto ? texto : `${texto.slice(0, LIMITE_DE_CONTEUDO_LONGO)}…`}
      </div>
      <button type="button" className="botao botao--secundario botao--pequeno" onClick={() => setAberto(!aberto)}>
        {aberto ? 'Recolher' : `Ver ${titulo.toLowerCase()}`}
      </button>
      <p className="fraco" style={{ marginTop: 6, marginBottom: 0 }}>
        O conteúdo completo sai inteiro nos arquivos baixados.
      </p>
    </div>
  )
}

function DetalhesTecnicos({ evento }: { evento: Evento }) {
  if (!evento.attachmentName && !evento.detectedMime) return null
  return (
    <details>
      <summary>Detalhes técnicos</summary>
      <ul className="fraco">
        {evento.attachmentName && <li>Arquivo: {evento.attachmentName}</li>}
        {evento.detectedMime && <li>Tipo real: {evento.detectedMime}</li>}
        {evento.metadata.mimeMismatch && (
          <li>
            A extensão dizia {evento.metadata.mimeMismatch.extension}, mas o conteúdo é{' '}
            {evento.metadata.mimeMismatch.detected}. Valeu o conteúdo.
          </li>
        )}
        {evento.metadata.frames ? <li>Quadros analisados: {evento.metadata.frames}</li> : null}
        <li>Posição na conversa: {evento.index + 1}</li>
      </ul>
    </details>
  )
}
