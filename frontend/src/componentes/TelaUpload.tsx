import { useRef, useState } from 'react'

import type { ConfiguracaoPublica } from '../api/tipos'
import { EnvioCancelado, enviarZip, type ProgressoDoEnvio } from '../upload/enviarZip'
import { enviarZipDireto } from '../upload/enviarZipDireto'
import { AtalhoIphone } from './AtalhoIphone'

interface Props {
  configuracao: ConfiguracaoPublica
  aoEnviar: (jobId: string) => void
}

/** Tela inicial: escolher o ZIP e acompanhar o envio, com progresso real. */
export function TelaUpload({ configuracao, aoEnviar }: Props) {
  const [progresso, setProgresso] = useState<ProgressoDoEnvio | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [arrastando, setArrastando] = useState(false)
  const entrada = useRef<HTMLInputElement>(null)
  const cancelamento = useRef<AbortController | null>(null)

  const enviando = progresso !== null

  async function iniciar(arquivo: File) {
    setErro(null)
    if (!arquivo.name.toLowerCase().endsWith('.zip')) {
      setErro('Envie o arquivo ZIP gerado pela exportação do WhatsApp.')
      return
    }
    const limite = configuracao.maxZipMb * 1024 * 1024
    if (arquivo.size > limite) {
      setErro(`O ZIP tem ${(arquivo.size / 1024 / 1024).toFixed(0)} MB e o limite é ${configuracao.maxZipMb} MB.`)
      return
    }

    const controlador = new AbortController()
    cancelamento.current = controlador
    setProgresso({ enviados: 0, total: arquivo.size, porcentagem: 0, pedacoAtual: 0, totalDePedacos: 0 })
    try {
      // Com armazenamento na nuvem o arquivo vai direto para lá; no servidor
      // próprio ele sobe em partes pela própria API.
      const jobId =
        configuracao.storageMode === 'supabase'
          ? await enviarZipDireto({
              arquivo,
              aoProgredir: setProgresso,
              sinal: controlador.signal,
            })
          : await enviarZip({
              arquivo,
              tamanhoDoPedaco: configuracao.uploadChunkBytes,
              aoProgredir: setProgresso,
              sinal: controlador.signal,
            })
      aoEnviar(jobId)
    } catch (falha) {
      if (falha instanceof EnvioCancelado) {
        setErro('Envio cancelado. Você pode escolher o arquivo de novo quando quiser.')
      } else {
        setErro((falha as Error).message)
      }
    } finally {
      setProgresso(null)
      cancelamento.current = null
    }
  }

  return (
    <div className="pagina">
      <section className="cartao">
        <h1>Decifre uma conversa</h1>
        <p className="fraco">
          Envie o ZIP da conversa exportada do WhatsApp <strong>com mídia incluída</strong>. Áudios,
          imagens, PDFs, vídeos e links entram na conversa no lugar certo.
        </p>

        <button
          type="button"
          className={`area-arrastar${arrastando ? ' area-arrastar--ativa' : ''}`}
          onClick={() => entrada.current?.click()}
          onDragOver={(evento) => {
            evento.preventDefault()
            setArrastando(true)
          }}
          onDragLeave={() => setArrastando(false)}
          onDrop={(evento) => {
            evento.preventDefault()
            setArrastando(false)
            const arquivo = evento.dataTransfer.files?.[0]
            if (arquivo) iniciar(arquivo)
          }}
          disabled={enviando}
        >
          <strong>Arraste o ZIP da conversa aqui</strong>
          <br />
          ou toque para selecionar
          <br />
          <span className="fraco">Aceita exportações do WhatsApp com mídia incluída, até {configuracao.maxZipMb} MB.</span>
        </button>

        <input
          ref={entrada}
          type="file"
          /* Sem filtro estrito de propósito: no iPhone, um `accept` fechado deixa o
             ZIP do WhatsApp esmaecido e impossível de escolher na tela de Arquivos.
             O tipo é conferido logo abaixo, em `iniciar`. */
          accept="*/*"
          className="oculto-visualmente"
          aria-label="Selecionar o ZIP da conversa"
          onChange={(evento) => {
            const arquivo = evento.target.files?.[0]
            if (arquivo) iniciar(arquivo)
            evento.target.value = ''
          }}
        />

        {progresso && (
          <div style={{ marginTop: 16 }} aria-live="polite">
            <div className="barra">
              <div className="barra__preenchimento" style={{ width: `${progresso.porcentagem}%` }} />
            </div>
            <p className="fraco" style={{ marginTop: 8 }}>
              Enviando… {progresso.porcentagem}%
              {progresso.totalDePedacos > 0 && ` (parte ${progresso.pedacoAtual} de ${progresso.totalDePedacos})`}
            </p>
            <button
              type="button"
              className="botao botao--secundario"
              onClick={() => cancelamento.current?.abort()}
            >
              Cancelar envio
            </button>
          </div>
        )}

        {erro && (
          <p className="aviso aviso--erro" role="alert" style={{ marginTop: 16 }}>
            {erro}
          </p>
        )}
      </section>

      {!configuracao.videoSupported && (
        <p className="aviso">
          Nesta instalação os vídeos não são analisados — eles continuam na conversa, no lugar
          certo, com o aviso de que não foram lidos. Áudios, imagens, PDFs e links funcionam
          normalmente.
        </p>
      )}

      {!configuracao.aiEnabled && (
        <p className="aviso">
          O servidor está sem provedor de IA configurado. A conversa vai ser montada com o texto
          completo, mas áudios, imagens, PDFs e vídeos ficam pendentes.
        </p>
      )}

      <AtalhoIphone />

      <section className="cartao">
        <h2>Como exportar a conversa</h2>
        <ol>
          <li>Abra a conversa no WhatsApp.</li>
          <li>Toque no nome do contato e escolha “Exportar conversa”.</li>
          <li>Escolha <strong>Incluir mídia</strong>.</li>
          <li>Salve o ZIP e envie aqui.</li>
        </ol>
        <p className="fraco">
          Os arquivos são apagados do servidor depois de {configuracao.jobRetentionHours} horas, e
          você pode apagar tudo antes disso quando quiser.
        </p>
      </section>
    </div>
  )
}
