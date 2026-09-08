import { useEffect, useState } from 'react'

/**
 * Modo claro é o padrão: a tela principal é um paredão de texto e leitura longa
 * cansa menos em fundo claro. O modo escuro fica como escolha da pessoa.
 */
const CHAVE = 'decifra:tema'
export type ModoDeTema = 'claro' | 'escuro'

export function lerTemaSalvo(): ModoDeTema {
  try {
    return localStorage.getItem(CHAVE) === 'escuro' ? 'escuro' : 'claro'
  } catch {
    return 'claro'
  }
}

export function useTema() {
  const [tema, setTema] = useState<ModoDeTema>(lerTemaSalvo)

  useEffect(() => {
    document.documentElement.dataset.tema = tema
    try {
      localStorage.setItem(CHAVE, tema)
    } catch {
      /* navegador sem armazenamento local */
    }
  }, [tema])

  return { tema, alternar: () => setTema(tema === 'claro' ? 'escuro' : 'claro') }
}

export function BotaoDeTema({ tema, aoAlternar }: { tema: ModoDeTema; aoAlternar: () => void }) {
  return (
    <button
      type="button"
      className="botao botao--secundario botao--pequeno"
      onClick={aoAlternar}
      aria-pressed={tema === 'escuro'}
    >
      {tema === 'claro' ? 'Modo escuro' : 'Modo claro'}
    </button>
  )
}
