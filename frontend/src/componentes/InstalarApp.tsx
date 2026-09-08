import { useEffect, useState } from 'react'

/**
 * Instalação do aplicativo.
 *
 * No Android o navegador oferece o fluxo nativo (`beforeinstallprompt`).
 * No iPhone e no iPad não existe prompt: o caminho é o menu Compartilhar do
 * Safari, então mostramos a instrução — dispensável e sem bloquear o uso.
 */

interface EventoDeInstalacao extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

const CHAVE_DISPENSA = 'decifra:instalacao-dispensada'

export function estaEmModoAplicativo(): boolean {
  return (
    window.matchMedia?.('(display-mode: standalone)').matches ||
    (window.navigator as { standalone?: boolean }).standalone === true
  )
}

export function ehIosOuIpad(userAgent = navigator.userAgent): boolean {
  const ios = /iPad|iPhone|iPod/.test(userAgent)
  const ipadModerno = /Macintosh/.test(userAgent) && navigator.maxTouchPoints > 1
  return ios || ipadModerno
}

export function InstalarApp({ forcarAbertura = false }: { forcarAbertura?: boolean }) {
  const [prompt, setPrompt] = useState<EventoDeInstalacao | null>(null)
  const [dispensado, setDispensado] = useState(() => {
    try {
      return localStorage.getItem(CHAVE_DISPENSA) === '1'
    } catch {
      return false
    }
  })

  useEffect(() => {
    const aoReceber = (evento: Event) => {
      evento.preventDefault()
      setPrompt(evento as EventoDeInstalacao)
    }
    window.addEventListener('beforeinstallprompt', aoReceber)
    return () => window.removeEventListener('beforeinstallprompt', aoReceber)
  }, [])

  if (estaEmModoAplicativo()) return null
  if (dispensado && !forcarAbertura) return null

  function dispensar() {
    try {
      localStorage.setItem(CHAVE_DISPENSA, '1')
    } catch {
      /* navegador sem armazenamento local */
    }
    setDispensado(true)
  }

  if (prompt) {
    return (
      <div className="instalar">
        <strong>Instalar aplicativo</strong>
        <p className="fraco">Fica com ícone próprio e abre em tela cheia, sem barra do navegador.</p>
        <div className="linha">
          <button
            type="button"
            className="botao"
            onClick={async () => {
              await prompt.prompt()
              await prompt.userChoice
              setPrompt(null)
            }}
          >
            Instalar aplicativo
          </button>
          <button type="button" className="botao botao--secundario" onClick={dispensar}>
            Agora não
          </button>
        </div>
      </div>
    )
  }

  if (ehIosOuIpad()) {
    return (
      <div className="instalar">
        <strong>Instalar no iPhone ou iPad</strong>
        <ol>
          <li>Toque no botão Compartilhar do Safari (o quadrado com a seta para cima).</li>
          <li>Role a lista e escolha “Adicionar à Tela de Início”.</li>
          <li>Confirme em “Adicionar”.</li>
        </ol>
        <button type="button" className="botao botao--secundario botao--pequeno" onClick={dispensar}>
          Entendi
        </button>
      </div>
    )
  }

  return null
}
