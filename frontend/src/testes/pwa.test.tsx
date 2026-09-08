/** Testes do PWA: manifest, service worker e instalação em Android e iOS. */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { InstalarApp, ehIosOuIpad, estaEmModoAplicativo } from '../componentes/InstalarApp'

const raiz = resolve(__dirname, '../..')
const manifest = JSON.parse(readFileSync(resolve(raiz, 'public/manifest.webmanifest'), 'utf8'))
const codigoDoServiceWorker = readFileSync(resolve(raiz, 'public/sw.js'), 'utf8')

describe('manifest', () => {
  it('tem os campos mínimos exigidos para instalar', () => {
    expect(manifest.name).toBe('Decifra Pro')
    expect(manifest.short_name).toBe('Decifra')
    expect(manifest.start_url).toBe('/')
    expect(manifest.display).toBe('standalone')
    expect(manifest.theme_color).toBe('#6B4EE6')
    expect(manifest.background_color).toBe('#FAF9FC')
  })

  it('tem ícones 192, 512 e maskable', () => {
    const tamanhos = manifest.icons.map((icone: { sizes: string }) => icone.sizes)
    expect(tamanhos).toContain('192x192')
    expect(tamanhos).toContain('512x512')
    expect(manifest.icons.some((icone: { purpose: string }) => icone.purpose === 'maskable')).toBe(true)
  })

  it('aponta para arquivos de ícone que existem', () => {
    for (const icone of manifest.icons as { src: string }[]) {
      expect(() => readFileSync(resolve(raiz, 'public', icone.src.replace(/^\//, '')))).not.toThrow()
    }
  })
})

function montarServiceWorker() {
  const ouvintes: Record<string, (evento: unknown) => void> = {}
  const escopo = {
    addEventListener: (nome: string, funcao: (evento: unknown) => void) => {
      ouvintes[nome] = funcao
    },
    location: { origin: 'https://decifra.exemplo' },
    skipWaiting: () => undefined,
    clients: { claim: () => undefined },
  }
  const caches = { open: async () => ({ addAll: async () => undefined }), keys: async () => [] }
  // eslint-disable-next-line no-new-func
  new Function('self', 'caches', 'fetch', codigoDoServiceWorker)(escopo, caches, async () => undefined)
  return ouvintes
}

describe('service worker', () => {
  it('cacheia apenas o app shell', () => {
    expect(codigoDoServiceWorker).toContain("'/index.html'")
    expect(codigoDoServiceWorker).not.toContain('/api/jobs')
  })

  it('não intercepta nem cacheia chamadas de API com dados da conversa', () => {
    const ouvintes = montarServiceWorker()
    const respondidos: unknown[] = []
    const evento = {
      request: {
        url: 'https://decifra.exemplo/api/jobs/abc/events',
        method: 'GET',
        mode: 'cors',
        headers: { get: () => 'application/json' },
      },
      respondWith: (resposta: unknown) => respondidos.push(resposta),
    }
    ouvintes.fetch(evento)
    expect(respondidos).toHaveLength(0)
  })

  it('responde o app shell para navegação', () => {
    const ouvintes = montarServiceWorker()
    const respondidos: unknown[] = []
    const evento = {
      request: {
        url: 'https://decifra.exemplo/',
        method: 'GET',
        mode: 'navigate',
        headers: { get: () => 'text/html' },
      },
      respondWith: (resposta: unknown) => respondidos.push(resposta),
    }
    ouvintes.fetch(evento)
    expect(respondidos).toHaveLength(1)
  })
})

describe('instalação', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('reconhece iPhone e iPad', () => {
    expect(ehIosOuIpad('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari')).toBe(true)
    expect(ehIosOuIpad('Mozilla/5.0 (Linux; Android 14) Chrome')).toBe(false)
  })

  it('reconhece o modo aplicativo instalado', () => {
    vi.stubGlobal('matchMedia', () => ({ matches: true, media: '', addEventListener: () => undefined }))
    expect(estaEmModoAplicativo()).toBe(true)
  })

  it('mostra a instrução do iOS e permite dispensar', async () => {
    vi.stubGlobal('matchMedia', () => ({ matches: false, media: '', addEventListener: () => undefined }))
    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(
      'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari',
    )

    const { unmount } = render(<InstalarApp />)
    expect(screen.getByText('Instalar no iPhone ou iPad')).toBeInTheDocument()
    expect(screen.getByText(/Adicionar à Tela de Início/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Entendi' }))
    expect(screen.queryByText('Instalar no iPhone ou iPad')).not.toBeInTheDocument()
    expect(localStorage.getItem('decifra:instalacao-dispensada')).toBe('1')

    unmount()
    render(<InstalarApp />)
    expect(screen.queryByText('Instalar no iPhone ou iPad')).not.toBeInTheDocument()
  })

  it('mostra o botão nativo do Android quando o navegador oferece', async () => {
    vi.stubGlobal('matchMedia', () => ({ matches: false, media: '', addEventListener: () => undefined }))
    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue('Mozilla/5.0 (Linux; Android 14) Chrome')

    render(<InstalarApp />)
    expect(screen.queryByRole('button', { name: 'Instalar aplicativo' })).not.toBeInTheDocument()

    const prompt = vi.fn(async () => undefined)
    const evento = new Event('beforeinstallprompt') as Event & {
      prompt: () => Promise<void>
      userChoice: Promise<{ outcome: string }>
    }
    evento.prompt = prompt
    evento.userChoice = Promise.resolve({ outcome: 'accepted' })
    act(() => {
      window.dispatchEvent(evento)
    })

    const botao = await screen.findByRole('button', { name: 'Instalar aplicativo' })
    await userEvent.click(botao)
    expect(prompt).toHaveBeenCalled()
  })

  it('não aparece quando o app já está instalado', () => {
    vi.stubGlobal('matchMedia', () => ({ matches: true, media: '', addEventListener: () => undefined }))
    const { container } = render(<InstalarApp />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('iPhone: detalhes que costumam quebrar', () => {
  it('o seletor de arquivo não filtra por tipo (no iOS isso esmaece o ZIP)', () => {
    const tela = readFileSync(resolve(raiz, 'src/componentes/TelaUpload.tsx'), 'utf8')
    expect(tela).not.toContain('accept=".zip')
    expect(tela).toContain('accept="*/*"')
    expect(tela).toContain("endsWith('.zip')") // a conferência é feita no código
  })

  it('copia usando a promessa, que é o jeito que o Safari aceita', async () => {
    const { copiarTexto } = await import('../componentes/TelaTimeline')
    const escritos: unknown[] = []

    class ItemFalso {
      constructor(readonly dados: Record<string, unknown>) {}
    }
    vi.stubGlobal('ClipboardItem', ItemFalso)
    vi.stubGlobal('navigator', {
      ...navigator,
      clipboard: {
        write: async (itens: unknown[]) => {
          escritos.push(...itens)
        },
        writeText: async () => {
          throw new Error('não deveria cair aqui no Safari')
        },
      },
    })

    await copiarTexto(async () => 'histórico da conversa')

    expect(escritos).toHaveLength(1)
    expect(escritos[0]).toBeInstanceOf(ItemFalso)
  })

  it('usa o caminho simples em navegador sem suporte à promessa', async () => {
    const { copiarTexto } = await import('../componentes/TelaTimeline')
    let copiado = ''
    vi.stubGlobal('ClipboardItem', undefined)
    vi.stubGlobal('navigator', {
      ...navigator,
      clipboard: {
        writeText: async (texto: string) => {
          copiado = texto
        },
      },
    })

    await copiarTexto(async () => 'histórico da conversa')
    expect(copiado).toBe('histórico da conversa')
  })
})
