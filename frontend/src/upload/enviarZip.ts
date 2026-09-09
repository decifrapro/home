/**
 * Envio do ZIP em partes.
 *
 * O arquivo nunca é carregado inteiro na memória do navegador: cada pedaço é
 * uma fatia do File enviada direto. Pedaço que falha é reenviado com espera
 * crescente, e o usuário pode cancelar a qualquer momento.
 */

/**
 * Em que ponto está o envio.
 *
 * Depois que o arquivo termina de subir ainda falta ler a conversa inteira de
 * dentro dele, e isso demora. Sem distinguir as duas etapas, a tela ficava
 * parada em "Enviando… 100%" e parecia travada justamente na parte mais lenta.
 */
export type EtapaDoEnvio = 'enviando' | 'lendo'

export interface ProgressoDoEnvio {
  enviados: number
  total: number
  porcentagem: number
  pedacoAtual: number
  totalDePedacos: number
  etapa?: EtapaDoEnvio
}

export interface OpcoesDeEnvio {
  arquivo: File
  tamanhoDoPedaco: number
  aoProgredir?: (progresso: ProgressoDoEnvio) => void
  sinal?: AbortSignal
  tentativasPorPedaco?: number
  esperar?: (milissegundos: number) => Promise<void>
  requisitar?: typeof fetch
}

export class EnvioCancelado extends Error {
  constructor() {
    super('Envio cancelado.')
    this.name = 'EnvioCancelado'
  }
}

const esperaPadrao = (ms: number) => new Promise<void>((resolver) => setTimeout(resolver, ms))

function conferirCancelamento(sinal?: AbortSignal) {
  if (sinal?.aborted) throw new EnvioCancelado()
}

async function comCorpoJson(resposta: Response): Promise<string> {
  try {
    const corpo = await resposta.json()
    return corpo?.detail ? String(corpo.detail) : `Erro ${resposta.status}`
  } catch {
    return `Erro ${resposta.status}`
  }
}

export function fatiar(tamanhoTotal: number, tamanhoDoPedaco: number): [number, number][] {
  const fatias: [number, number][] = []
  const passo = Math.max(1, tamanhoDoPedaco)
  for (let inicio = 0; inicio < tamanhoTotal; inicio += passo) {
    fatias.push([inicio, Math.min(inicio + passo, tamanhoTotal)])
  }
  return fatias.length ? fatias : [[0, 0]]
}

export async function enviarZip(opcoes: OpcoesDeEnvio): Promise<string> {
  const {
    arquivo,
    tamanhoDoPedaco,
    aoProgredir,
    sinal,
    tentativasPorPedaco = 4,
    esperar = esperaPadrao,
    requisitar = fetch,
  } = opcoes

  conferirCancelamento(sinal)

  const criacao = await requisitar('/api/jobs', { method: 'POST', credentials: 'same-origin' })
  if (!criacao.ok) throw new Error(await comCorpoJson(criacao))
  const { id: jobId } = (await criacao.json()) as { id: string }

  const fatias = fatiar(arquivo.size, tamanhoDoPedaco)

  const inicio = await requisitar(`/api/jobs/${jobId}/upload/init`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      filename: arquivo.name,
      size: arquivo.size,
      totalChunks: fatias.length,
    }),
  })
  if (!inicio.ok) throw new Error(await comCorpoJson(inicio))

  let enviados = 0
  for (let indice = 0; indice < fatias.length; indice += 1) {
    conferirCancelamento(sinal)
    const [comeco, fim] = fatias[indice]
    const pedaco = arquivo.slice(comeco, fim)

    let ultimoErro: unknown = null
    let entregue = false
    for (let tentativa = 0; tentativa < tentativasPorPedaco && !entregue; tentativa += 1) {
      conferirCancelamento(sinal)
      try {
        const resposta = await requisitar(`/api/jobs/${jobId}/upload/chunk?index=${indice}`, {
          method: 'PUT',
          credentials: 'same-origin',
          body: pedaco,
          signal: sinal,
        })
        if (!resposta.ok) throw new Error(await comCorpoJson(resposta))
        entregue = true
      } catch (erro) {
        if (sinal?.aborted) throw new EnvioCancelado()
        ultimoErro = erro
        if (tentativa < tentativasPorPedaco - 1) await esperar(2 ** tentativa * 500)
      }
    }
    if (!entregue) {
      throw new Error(
        `A parte ${indice + 1} de ${fatias.length} não foi enviada depois de ${tentativasPorPedaco} tentativas. ` +
          `Verifique a conexão e tente de novo. (${(ultimoErro as Error)?.message ?? 'erro desconhecido'})`,
      )
    }

    enviados += fim - comeco
    aoProgredir?.({
      enviados,
      total: arquivo.size,
      porcentagem: arquivo.size ? Math.round((enviados / arquivo.size) * 100) : 100,
      pedacoAtual: indice + 1,
      totalDePedacos: fatias.length,
    })
  }

  conferirCancelamento(sinal)
  aoProgredir?.({
    enviados: arquivo.size,
    total: arquivo.size,
    porcentagem: 100,
    pedacoAtual: fatias.length,
    totalDePedacos: fatias.length,
    etapa: 'lendo',
  })
  const conclusao = await requisitar(`/api/jobs/${jobId}/upload/complete`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ totalChunks: fatias.length, size: arquivo.size }),
  })
  if (!conclusao.ok) throw new Error(await comCorpoJson(conclusao))

  return jobId
}
