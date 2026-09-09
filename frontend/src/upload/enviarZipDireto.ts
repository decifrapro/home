/**
 * Envio do ZIP direto para o armazenamento (Supabase), sem passar pela função.
 *
 * Na Vercel a requisição que chega ao servidor é limitada a poucos megabytes —
 * um ZIP de conversa não passa por ali. O servidor então devolve um link
 * temporário e o próprio celular envia o arquivo para o armazenamento.
 */

import type { ProgressoDoEnvio } from './enviarZip'
import { EnvioCancelado } from './enviarZip'

export interface OpcoesDeEnvioDireto {
  arquivo: File
  aoProgredir?: (progresso: ProgressoDoEnvio) => void
  sinal?: AbortSignal
  requisitar?: typeof fetch
  enviarArquivo?: typeof enviarComProgresso
}

async function corpoDeErro(resposta: Response): Promise<string> {
  try {
    const corpo = await resposta.json()
    return corpo?.detail ? String(corpo.detail) : `Erro ${resposta.status}`
  } catch {
    return `Erro ${resposta.status}`
  }
}

/** PUT com barra de progresso de verdade — `fetch` não informa progresso de envio. */
export function enviarComProgresso(
  url: string,
  arquivo: File,
  aoProgredir?: (enviados: number, total: number) => void,
  sinal?: AbortSignal,
): Promise<void> {
  return new Promise((resolver, rejeitar) => {
    const requisicao = new XMLHttpRequest()
    requisicao.open('PUT', url, true)
    requisicao.setRequestHeader('content-type', arquivo.type || 'application/zip')
    requisicao.setRequestHeader('x-upsert', 'true')

    requisicao.upload.onprogress = (evento) => {
      if (evento.lengthComputable) aoProgredir?.(evento.loaded, evento.total)
    }
    requisicao.onload = () => {
      if (requisicao.status >= 200 && requisicao.status < 300) resolver()
      else rejeitar(new Error(`O envio falhou (${requisicao.status}). Tente de novo.`))
    }
    requisicao.onerror = () => rejeitar(new Error('A conexão caiu durante o envio.'))
    requisicao.onabort = () => rejeitar(new EnvioCancelado())

    sinal?.addEventListener('abort', () => requisicao.abort(), { once: true })
    requisicao.send(arquivo)
  })
}

export async function enviarZipDireto(opcoes: OpcoesDeEnvioDireto): Promise<string> {
  const {
    arquivo,
    aoProgredir,
    sinal,
    requisitar = fetch,
    enviarArquivo = enviarComProgresso,
  } = opcoes

  if (sinal?.aborted) throw new EnvioCancelado()

  const criacao = await requisitar('/api/jobs', { method: 'POST', credentials: 'same-origin' })
  if (!criacao.ok) throw new Error(await corpoDeErro(criacao))
  const { id: jobId } = (await criacao.json()) as { id: string }

  const link = await requisitar(`/api/jobs/${jobId}/upload/link`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename: arquivo.name, size: arquivo.size }),
  })
  if (!link.ok) throw new Error(await corpoDeErro(link))
  const { uploadUrl } = (await link.json()) as { uploadUrl: string }

  await enviarArquivo(
    uploadUrl,
    arquivo,
    (enviados, total) =>
      aoProgredir?.({
        enviados,
        total,
        porcentagem: total ? Math.round((enviados / total) * 100) : 100,
        pedacoAtual: 1,
        totalDePedacos: 1,
      }),
    sinal,
  )

  if (sinal?.aborted) throw new EnvioCancelado()

  // O arquivo já subiu; agora o servidor lê a conversa de dentro dele. É a
  // parte mais demorada, e precisa dizer isso em vez de parecer parada.
  aoProgredir?.({
    enviados: arquivo.size,
    total: arquivo.size,
    porcentagem: 100,
    pedacoAtual: 1,
    totalDePedacos: 1,
    etapa: 'lendo',
  })

  const registro = await requisitar(`/api/jobs/${jobId}/upload/registrado`, {
    method: 'POST',
    credentials: 'same-origin',
  })
  if (!registro.ok) throw new Error(await corpoDeErro(registro))

  return jobId
}
