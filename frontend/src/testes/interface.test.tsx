import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Cobertura } from '../componentes/Cobertura'
import { EventoCartao } from '../componentes/EventoCartao'
import { TelaTimeline } from '../componentes/TelaTimeline'
import { eventoDeAudio, eventoDeTexto, jobDeExemplo } from './dados'

describe('cobertura', () => {
  it('não anuncia 100% quando ainda falta item', () => {
    render(<Cobertura job={jobDeExemplo()} />)
    expect(screen.getByText(/99\.6%/)).toBeInTheDocument()
    expect(screen.queryByText(/Cobertura geral: 100%/)).not.toBeInTheDocument()
    expect(screen.getByText('1 com falha')).toBeInTheDocument()
  })

  it('anuncia 100% só quando tudo foi decifrado', () => {
    const job = jobDeExemplo({
      coverage: {
        categories: {
          text: { total: 10, done: 10, failed: 0, pending: 0, unsupported: 0, unresolved: 0, complete: true },
        },
        overallTotal: 10,
        overallDone: 10,
        percent: 100,
        complete: true,
      },
    })
    render(<Cobertura job={job} />)
    expect(screen.getByText(/Cobertura geral: 100%/)).toBeInTheDocument()
  })
})

describe('cartão de evento', () => {
  it('separa o conteúdo original do que a IA extraiu', () => {
    render(<EventoCartao evento={eventoDeAudio()} />)
    expect(screen.getByText('🎙 Áudio transcrito')).toBeInTheDocument()
    expect(screen.getByText(/Boa tarde, seu Rui/)).toBeInTheDocument()
    expect(screen.getAllByText(/PTT-20260825-WA0001.opus/).length).toBeGreaterThan(0)
  })

  it('mostra a legenda original separada da análise da imagem', () => {
    const evento = eventoDeAudio({
      type: 'image',
      caption: 'Olha essa condição',
      processedText: 'texto e descrição',
      metadata: { ocrText: 'Sala 705 — R$ 4.200,00', visualDescription: 'print de proposta' },
    })
    render(<EventoCartao evento={evento} />)
    expect(screen.getByText('Legenda original')).toBeInTheDocument()
    expect(screen.getByText('Olha essa condição')).toBeInTheDocument()
    expect(screen.getByText(/Sala 705/)).toBeInTheDocument()
  })

  it('mantém o evento com falha visível e oferece reprocessar', async () => {
    const aoReprocessar = vi.fn()
    const evento = eventoDeAudio({
      processingStatus: 'failed',
      processedText: null,
      processingError: 'Transcrição não concluída: provedor indisponível',
    })
    render(<EventoCartao evento={evento} aoReprocessar={aoReprocessar} />)

    expect(screen.getByRole('alert')).toHaveTextContent('Transcrição não concluída')
    await userEvent.click(screen.getByRole('button', { name: /Reprocessar este item/ }))
    expect(aoReprocessar).toHaveBeenCalledWith('e2')
  })

  it('não depende só de cor: o status vai escrito', () => {
    render(<EventoCartao evento={eventoDeAudio({ processingStatus: 'pending', processedText: null })} />)
    expect(screen.getByText('pendente')).toBeInTheDocument()
  })
})

describe('tela da timeline', () => {
  const respostas: Record<string, unknown> = {}

  beforeEach(() => {
    respostas['/api/jobs/job123/events'] = {
      total: 2,
      events: [eventoDeTexto(), eventoDeAudio()],
    }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const chave = url.split('?')[0]
        const corpo = respostas[chave] ?? { total: 0, events: [] }
        return new Response(JSON.stringify(corpo), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('mostra os eventos, o inventário e os botões de download', async () => {
    render(<TelaTimeline job={jobDeExemplo()} aoAtualizar={vi.fn()} aoApagar={vi.fn()} />)

    await waitFor(() => expect(screen.getByText(/Boa tarde, Sr. Rui/)).toBeInTheDocument())
    expect(screen.getByText('Inventário da conversa')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Baixar TXT' })).toHaveAttribute(
      'href',
      '/api/jobs/job123/export/txt',
    )
    expect(screen.getByRole('link', { name: 'Baixar Markdown' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Baixar JSON' })).toBeInTheDocument()
    expect(screen.getByText(/Este histórico está incompleto/)).toBeInTheDocument()
  })

  it('filtra por tipo de mídia pedindo ao servidor', async () => {
    render(<TelaTimeline job={jobDeExemplo()} aoAtualizar={vi.fn()} aoApagar={vi.fn()} />)
    await waitFor(() => expect(screen.getByText(/Boa tarde, Sr. Rui/)).toBeInTheDocument())

    await userEvent.selectOptions(screen.getByLabelText('Filtrar por tipo de mídia'), 'audio')

    await waitFor(() => {
      const chamadas = (fetch as unknown as { mock: { calls: string[][] } }).mock.calls.map((c) => c[0])
      expect(chamadas.some((url) => url.includes('type=audio'))).toBe(true)
    })
  })

  it('busca textual chega ao servidor', async () => {
    render(<TelaTimeline job={jobDeExemplo()} aoAtualizar={vi.fn()} aoApagar={vi.fn()} />)
    await waitFor(() => expect(screen.getByText(/Boa tarde, Sr. Rui/)).toBeInTheDocument())

    await userEvent.type(screen.getByLabelText('Buscar na conversa'), 'proposta')

    await waitFor(() => {
      const chamadas = (fetch as unknown as { mock: { calls: string[][] } }).mock.calls.map((c) => c[0])
      expect(chamadas.some((url) => url.includes('search=proposta'))).toBe(true)
    })
  })
})

describe('atalho do iPhone', () => {
  afterEach(() => vi.unstubAllGlobals())

  function responder(corpo: unknown) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(corpo), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })),
    )
  }

  it('mostra o passo a passo com a chave escondida', async () => {
    const { AtalhoIphone } = await import('../componentes/AtalhoIphone')
    responder({
      disponivel: true,
      chave: 'a'.repeat(40),
      cabecalho: 'x-decifra-chave',
      urlPreparar: 'https://app.exemplo/api/atalho/preparar',
      urlConcluir: 'https://app.exemplo/api/atalho/concluir',
    })

    render(<AtalhoIphone />)
    await waitFor(() => expect(screen.getByText('Enviar direto do WhatsApp (iPhone)')).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: 'Ver o passo a passo' }))

    expect(screen.getByText('•'.repeat(40))).toBeInTheDocument()
    expect(screen.queryByText('a'.repeat(40))).not.toBeInTheDocument()
    expect(screen.getByText('https://app.exemplo/api/atalho/preparar')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Mostrar' }))
    expect(screen.getByText('a'.repeat(40))).toBeInTheDocument()
  })

  it('explica o que falta quando o servidor não tem o segredo configurado', async () => {
    const { AtalhoIphone } = await import('../componentes/AtalhoIphone')
    responder({ disponivel: false, motivo: 'Falta definir APP_SESSION_SECRET no servidor.' })

    render(<AtalhoIphone />)
    await waitFor(() =>
      expect(screen.getByText(/Falta definir APP_SESSION_SECRET/)).toBeInTheDocument(),
    )
    expect(screen.queryByRole('button', { name: 'Ver o passo a passo' })).not.toBeInTheDocument()
  })
})

describe('atalho: saber se ele chegou ao servidor', () => {
  afterEach(() => vi.unstubAllGlobals())

  function responder(corpo: unknown) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(corpo), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })),
    )
  }

  const base = {
    disponivel: true,
    chave: 'b'.repeat(40),
    cabecalho: 'x-decifra-chave',
    urlPreparar: 'https://app.exemplo/api/atalho/preparar',
    urlConcluir: 'https://app.exemplo/api/atalho/concluir',
  }

  it('avisa quando o atalho nunca chegou ao servidor', async () => {
    const { AtalhoIphone } = await import('../componentes/AtalhoIphone')
    responder({ ...base, ultimoEnvio: null })

    render(<AtalhoIphone />)
    await waitFor(() => expect(screen.getByText('Enviar direto do WhatsApp (iPhone)')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Ver o passo a passo' }))

    expect(screen.getByText(/ainda nunca falou com este servidor/)).toBeInTheDocument()
  })

  it('mostra a data do último envio quando já funcionou', async () => {
    const { AtalhoIphone } = await import('../componentes/AtalhoIphone')
    responder({ ...base, ultimoEnvio: '2026-08-25T10:52:00' })

    render(<AtalhoIphone />)
    await waitFor(() => expect(screen.getByText('Enviar direto do WhatsApp (iPhone)')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Ver o passo a passo' }))

    expect(screen.getByText(/Última vez que o atalho falou/)).toBeInTheDocument()
  })

  it('explica que o atalho não aparece na fileira de ícones do compartilhar', async () => {
    const { AtalhoIphone } = await import('../componentes/AtalhoIphone')
    responder({ ...base, ultimoEnvio: null })

    render(<AtalhoIphone />)
    await waitFor(() => expect(screen.getByText('Enviar direto do WhatsApp (iPhone)')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Ver o passo a passo' }))

    expect(screen.getByText(/não aparece na fileira/)).toBeInTheDocument()
    expect(screen.getByText(/Editar ações/)).toBeInTheDocument()
  })
})

describe('conversas enviadas (celular e computador)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lista o que já foi enviado e abre ao tocar', async () => {
    const { ListaDeAtendimentos } = await import('../componentes/ListaDeAtendimentos')
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            jobs: [
              jobDeExemplo({ id: 'job1', originalFilename: 'Conversa com Rui.zip' }),
              jobDeExemplo({
                id: 'job2',
                originalFilename: 'Conversa com Isabela.zip',
                status: 'completed',
                coverage: {
                  categories: {},
                  overallTotal: 4,
                  overallDone: 4,
                  percent: 100,
                  complete: true,
                },
              }),
            ],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    const abrir = vi.fn()
    render(<ListaDeAtendimentos aoAbrir={abrir} />)

    await waitFor(() => expect(screen.getByText('Conversa com Rui.zip')).toBeInTheDocument())
    expect(screen.getByText('99.6% decifrado')).toBeInTheDocument()
    expect(screen.getByText('pronta')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Abrir Conversa com Rui.zip/ }))
    expect(abrir).toHaveBeenCalledWith('job1')
  })

  it('não ocupa espaço quando ainda não há conversa nenhuma', async () => {
    const { ListaDeAtendimentos } = await import('../componentes/ListaDeAtendimentos')
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ jobs: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    const { container } = render(<ListaDeAtendimentos aoAbrir={vi.fn()} />)
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })
})

describe('Progresso', () => {
  it('mostra a porcentagem e avisa quando o avanço para', async () => {
    const { Progresso } = await import('../componentes/Progresso')
    const job = {
      coverage: { percent: 40, overallDone: 2, overallTotal: 5, complete: false, categories: {} },
    } as never

    render(<Progresso job={job} />)
    expect(screen.getByText(/40%/)).toBeInTheDocument()
    expect(screen.getByText(/2 de 5 itens decifrados/)).toBeInTheDocument()
    expect(screen.getByText(/Trabalhando/)).toBeInTheDocument()
  })
})

describe('tela de processamento', () => {
  it('mostra o giro e a porcentagem enquanto decifra', async () => {
    const { TelaProcessando } = await import('../componentes/TelaProcessando')
    const job = jobDeExemplo({ status: 'processing' })

    const { container } = render(
      <TelaProcessando
        job={job}
        aoConfirmar={vi.fn()}
        aoCancelar={vi.fn()}
        aoVerConversa={vi.fn()}
      />,
    )

    expect(container.querySelector('.progresso__giro')).not.toBeNull()
    expect(screen.getByText(/itens decifrados/)).toBeInTheDocument()
  })
})

describe('esperas com sinal de vida', () => {
  it('diz que está lendo a conversa antes de existir item', async () => {
    const { Progresso } = await import('../componentes/Progresso')
    const job = {
      coverage: { percent: 0, overallDone: 0, overallTotal: 0, complete: false, categories: {} },
    } as never

    const { container } = render(<Progresso job={job} />)
    expect(screen.getByText(/Lendo a conversa/)).toBeInTheDocument()
    expect(screen.queryByText(/0 de 0/)).not.toBeInTheDocument()
    expect(container.querySelector('.progresso__giro')).not.toBeNull()
  })
})
