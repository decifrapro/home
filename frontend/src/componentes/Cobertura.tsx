import type { Job } from '../api/tipos'
import { NOME_POR_CATEGORIA } from './comum'

/**
 * Cobertura do atendimento. A barra fica roxa enquanto há pendência e âmbar
 * (lilás no modo escuro) quando tudo foi decifrado — e 100% só aparece quando
 * é 100% de verdade.
 */
export function Cobertura({ job }: { job: Job }) {
  const categorias = Object.entries(job.coverage.categories).filter(([, dados]) => dados.total > 0)
  const completo = job.coverage.complete

  return (
    <section className="cartao" aria-labelledby="titulo-cobertura">
      <h2 id="titulo-cobertura">Cobertura do atendimento</h2>

      <div className="barra" role="img" aria-label={`Cobertura de ${job.coverage.percent}%`}>
        <div
          className={`barra__preenchimento${completo ? ' barra__preenchimento--completo' : ''}`}
          style={{ width: `${job.coverage.percent}%` }}
        />
      </div>
      <p className="fraco" style={{ marginTop: 8 }}>
        {completo
          ? `Cobertura geral: 100% — todo o conteúdo foi decifrado.`
          : `Cobertura geral: ${job.coverage.percent}% — ${job.coverage.overallDone} de ${job.coverage.overallTotal} itens.`}
      </p>

      <table className="tabela-cobertura">
        <thead>
          <tr>
            <th scope="col">Categoria</th>
            <th scope="col">Decifrado</th>
          </tr>
        </thead>
        <tbody>
          {categorias.map(([nome, dados]) => (
            <tr key={nome}>
              <th scope="row">{NOME_POR_CATEGORIA[nome] ?? nome}</th>
              <td>
                {dados.done} / {dados.total}{' '}
                {dados.complete ? (
                  <span className="selo selo--decifrado">completo</span>
                ) : dados.failed ? (
                  <span className="selo selo--falha">{dados.failed} com falha</span>
                ) : dados.unsupported && dados.done + dados.unsupported === dados.total ? (
                  // Nada está na fila: estes itens esta instalação não consegue ler.
                  <span className="selo selo--pendente">
                    {dados.unsupported} sem suporte aqui
                  </span>
                ) : (
                  <span className="selo selo--pendente">
                    {dados.total - dados.done} pendente{dados.total - dados.done > 1 ? 's' : ''}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
