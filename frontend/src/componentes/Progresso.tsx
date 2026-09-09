import { useEffect, useRef, useState } from 'react'

import type { Job } from '../api/tipos'

interface UltimoBloco {
  segundos: number
  segundosDePreparo: number
  itens: number
}

/**
 * Sinal de vida do processamento.
 *
 * Enquanto o servidor decifra, a tela mostra o giro, a porcentagem e há quanto
 * tempo algo avançou pela última vez. Sem isso, um trabalho que só está
 * demorando é indistinguível de um travado — e quem olha desiste.
 */
export function Progresso({ job }: { job: Job }) {
  const feitos = job.coverage.overallDone
  const total = job.coverage.overallTotal
  const ultimoBloco = (job.metadata as Record<string, UltimoBloco | undefined>)?.ultimoBloco
  const [desdeOUltimoAvanco, setDesdeOUltimoAvanco] = useState(0)
  const marcoDoAvanco = useRef({ feitos, quando: Date.now() })

  useEffect(() => {
    if (feitos !== marcoDoAvanco.current.feitos) {
      marcoDoAvanco.current = { feitos, quando: Date.now() }
      setDesdeOUltimoAvanco(0)
    }
  }, [feitos])

  useEffect(() => {
    const relogio = window.setInterval(() => {
      setDesdeOUltimoAvanco(Math.round((Date.now() - marcoDoAvanco.current.quando) / 1000))
    }, 1000)
    return () => window.clearInterval(relogio)
  }, [])

  return (
    <div className="progresso">
      <span className="progresso__giro" aria-hidden="true" />
      <div className="progresso__texto">
        <p aria-live="polite">
          <strong>{job.coverage.percent}%</strong> — {feitos} de {total} itens decifrados.
        </p>
        {ultimoBloco && (
          <p className="fraco">
            Última rodada: {ultimoBloco.segundos}s · {ultimoBloco.itens} item(ns) · preparo{' '}
            {ultimoBloco.segundosDePreparo}s
          </p>
        )}
        <p className="fraco">
          {desdeOUltimoAvanco < 45
            ? 'Trabalhando… pode fechar esta aba, o servidor continua.'
            : `Sem avanço há ${desdeOUltimoAvanco}s. Ainda tentando — se falhar, o motivo aparece aqui.`}
        </p>
      </div>
    </div>
  )
}
