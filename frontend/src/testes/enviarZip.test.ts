import { describe, expect, it, vi } from 'vitest'

import { EnvioCancelado, enviarZip, fatiar } from '../upload/enviarZip'

function arquivoFalso(tamanho: number, nome = 'conversa.zip'): File {
  const conteudo = new Uint8Array(tamanho).fill(65)
  return new File([conteudo], nome, { type: 'application/zip' })
}

function respostaOk(corpo: unknown = {}) {
  return new Response(JSON.stringify(corpo), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

describe('fatiar', () => {
  it('divide o arquivo em pedaços do tamanho pedido', () => {
    expect(fatiar(10, 4)).toEqual([
      [0, 4],
      [4, 8],
      [8, 10],
    ])
  })

  it('trata arquivo vazio sem quebrar', () => {
    expect(fatiar(0, 4)).toEqual([[0, 0]])
  })
})

describe('enviarZip', () => {
  it('envia todos os pedaços em ordem e informa progresso real', async () => {
    const chamadas: string[] = []
    const progresso: number[] = []
    const requisitar = vi.fn(async (url: string) => {
      chamadas.push(url)
      if (url === '/api/jobs') return respostaOk({ id: 'abc123' })
      return respostaOk({ ok: true })
    }) as unknown as typeof fetch

    const jobId = await enviarZip({
      arquivo: arquivoFalso(2500),
      tamanhoDoPedaco: 1000,
      requisitar,
      aoProgredir: (info) => progresso.push(info.porcentagem),
    })

    expect(jobId).toBe('abc123')
    expect(chamadas).toEqual([
      '/api/jobs',
      '/api/jobs/abc123/upload/init',
      '/api/jobs/abc123/upload/chunk?index=0',
      '/api/jobs/abc123/upload/chunk?index=1',
      '/api/jobs/abc123/upload/chunk?index=2',
      '/api/jobs/abc123/upload/complete',
    ])
    expect(progresso).toEqual([40, 80, 100])
  })

  it('reenvia o pedaço que falhou e segue em frente', async () => {
    let falhasRestantes = 2
    const tentativasPorPedaco: string[] = []
    const requisitar = vi.fn(async (url: string) => {
      if (url === '/api/jobs') return respostaOk({ id: 'job1' })
      if (url.includes('/chunk')) {
        tentativasPorPedaco.push(url)
        if (falhasRestantes > 0) {
          falhasRestantes -= 1
          throw new TypeError('rede caiu')
        }
      }
      return respostaOk({})
    }) as unknown as typeof fetch

    const jobId = await enviarZip({
      arquivo: arquivoFalso(100),
      tamanhoDoPedaco: 100,
      requisitar,
      esperar: async () => undefined,
    })

    expect(jobId).toBe('job1')
    expect(tentativasPorPedaco).toHaveLength(3) // duas falhas e o envio que deu certo
  })

  it('desiste com mensagem clara depois de esgotar as tentativas', async () => {
    const requisitar = vi.fn(async (url: string) => {
      if (url === '/api/jobs') return respostaOk({ id: 'job1' })
      if (url.includes('/chunk')) throw new TypeError('sem rede')
      return respostaOk({})
    }) as unknown as typeof fetch

    await expect(
      enviarZip({
        arquivo: arquivoFalso(10),
        tamanhoDoPedaco: 10,
        requisitar,
        tentativasPorPedaco: 3,
        esperar: async () => undefined,
      }),
    ).rejects.toThrow(/não foi enviada depois de 3 tentativas/)
  })

  it('cancela o envio quando a pessoa pede', async () => {
    const controlador = new AbortController()
    const requisitar = vi.fn(async (url: string) => {
      if (url === '/api/jobs') return respostaOk({ id: 'job1' })
      if (url.includes('index=0')) {
        controlador.abort()
        return respostaOk({})
      }
      return respostaOk({})
    }) as unknown as typeof fetch

    await expect(
      enviarZip({
        arquivo: arquivoFalso(300),
        tamanhoDoPedaco: 100,
        requisitar,
        sinal: controlador.signal,
      }),
    ).rejects.toBeInstanceOf(EnvioCancelado)
  })

  it('propaga a mensagem de erro que o servidor devolveu', async () => {
    const requisitar = vi.fn(async (url: string) => {
      if (url === '/api/jobs') return respostaOk({ id: 'job1' })
      if (url.includes('/upload/init')) {
        return new Response(JSON.stringify({ detail: 'O ZIP tem 900 MB e o limite é 500 MB.' }), {
          status: 413,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return respostaOk({})
    }) as unknown as typeof fetch

    await expect(
      enviarZip({ arquivo: arquivoFalso(10), tamanhoDoPedaco: 10, requisitar }),
    ).rejects.toThrow('O ZIP tem 900 MB e o limite é 500 MB.')
  })
})

describe('enviarZipDireto (modo nuvem)', () => {
  it('pede o link, envia o arquivo direto e avisa o servidor', async () => {
    const { enviarZipDireto } = await import('../upload/enviarZipDireto')
    const chamadas: string[] = []
    const progresso: number[] = []

    const requisitar = vi.fn(async (url: string) => {
      chamadas.push(url)
      if (url === '/api/jobs') return respostaOk({ id: 'job9' })
      if (url.includes('/upload/link')) {
        return respostaOk({ uploadUrl: 'https://projeto.supabase.co/enviar?token=abc' })
      }
      return respostaOk({ id: 'job9', status: 'awaiting_confirmation' })
    }) as unknown as typeof fetch

    const enviarArquivo = vi.fn(async (url: string, arquivo: File, aoProgredir?: (e: number, t: number) => void) => {
      expect(url).toContain('token=abc')
      aoProgredir?.(arquivo.size / 2, arquivo.size)
      aoProgredir?.(arquivo.size, arquivo.size)
    })

    const jobId = await enviarZipDireto({
      arquivo: arquivoFalso(1000),
      requisitar,
      enviarArquivo,
      aoProgredir: (info) => progresso.push(info.porcentagem),
    })

    expect(jobId).toBe('job9')
    expect(chamadas).toEqual([
      '/api/jobs',
      '/api/jobs/job9/upload/link',
      '/api/jobs/job9/upload/registrado',
    ])
    expect(progresso).toEqual([50, 100])
    expect(enviarArquivo).toHaveBeenCalledOnce()
  })

  it('mostra a mensagem do servidor quando o ZIP passa do limite', async () => {
    const { enviarZipDireto } = await import('../upload/enviarZipDireto')
    const requisitar = vi.fn(async (url: string) => {
      if (url === '/api/jobs') return respostaOk({ id: 'job9' })
      return new Response(JSON.stringify({ detail: 'O ZIP tem 900 MB e o limite é 500 MB.' }), {
        status: 413,
        headers: { 'Content-Type': 'application/json' },
      })
    }) as unknown as typeof fetch

    await expect(
      enviarZipDireto({ arquivo: arquivoFalso(10), requisitar, enviarArquivo: async () => {} }),
    ).rejects.toThrow('O ZIP tem 900 MB e o limite é 500 MB.')
  })

  it('não avisa o servidor se o envio for cancelado', async () => {
    const { enviarZipDireto } = await import('../upload/enviarZipDireto')
    const { EnvioCancelado } = await import('../upload/enviarZip')
    const controlador = new AbortController()
    const chamadas: string[] = []

    const requisitar = vi.fn(async (url: string) => {
      chamadas.push(url)
      if (url === '/api/jobs') return respostaOk({ id: 'job9' })
      return respostaOk({ uploadUrl: 'https://projeto.supabase.co/enviar?token=abc' })
    }) as unknown as typeof fetch

    await expect(
      enviarZipDireto({
        arquivo: arquivoFalso(10),
        requisitar,
        sinal: controlador.signal,
        enviarArquivo: async () => {
          controlador.abort()
        },
      }),
    ).rejects.toBeInstanceOf(EnvioCancelado)
    expect(chamadas.some((url) => url.includes('registrado'))).toBe(false)
  })
})
