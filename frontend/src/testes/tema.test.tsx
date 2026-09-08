/** Tema e regras visuais que a marca exige. */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import { BotaoDeTema, lerTemaSalvo, useTema } from '../componentes/Tema'

const css = readFileSync(resolve(__dirname, '../estilos/tema.css'), 'utf8')

describe('folha de estilo', () => {
  it('usa as cores da marca', () => {
    expect(css).toContain('--roxo: #6b4ee6')
    expect(css).toContain('--decifrado: #ffc94d')
    expect(css).toContain("[data-tema='escuro']")
  })

  it('troca o âmbar por lilás no modo escuro, como manda a marca', () => {
    const blocoEscuro = css.split("[data-tema='escuro']")[1]
    expect(blocoEscuro).toContain('--decifrado: #c8b6ff')
  })

  it('não usa verde, sombra, gradiente nem brilho', () => {
    expect(css).not.toMatch(/box-shadow|linear-gradient|radial-gradient|text-shadow/)
    expect(css).not.toMatch(/#0f0|green|#00ff/i)
  })

  it('tem alvos de toque confortáveis e ajuste para telas pequenas', () => {
    expect(css).toContain('min-height: 44px')
    expect(css).toContain('@media (max-width: 480px)')
  })

  it('usa apenas os pesos 400 e 500', () => {
    const pesos = [...css.matchAll(/font-weight:\s*(\d{3})/g)].map((achado) => achado[1])
    expect(new Set(pesos)).toEqual(new Set(['400']))
    expect(css).toContain('--peso-titulo: 500')
  })
})

function TelaDeTeste() {
  const { tema, alternar } = useTema()
  return (
    <>
      <span data-testid="tema-atual">{tema}</span>
      <BotaoDeTema tema={tema} aoAlternar={alternar} />
    </>
  )
}

describe('modo claro e escuro', () => {
  afterEach(() => localStorage.clear())

  it('começa no modo claro', () => {
    expect(lerTemaSalvo()).toBe('claro')
  })

  it('a pessoa pode escolher o modo escuro e a escolha fica guardada', async () => {
    render(<TelaDeTeste />)
    await userEvent.click(screen.getByRole('button', { name: 'Modo escuro' }))

    expect(screen.getByTestId('tema-atual')).toHaveTextContent('escuro')
    expect(document.documentElement.dataset.tema).toBe('escuro')
    expect(lerTemaSalvo()).toBe('escuro')
  })
})
