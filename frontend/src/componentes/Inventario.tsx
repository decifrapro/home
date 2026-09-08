import type { Job } from '../api/tipos'

/** Inventário cru do que foi encontrado no ZIP. Sem maquiagem. */
export function Inventario({ job }: { job: Job }) {
  const inventario = job.inventory
  const linhas: [string, number, string?][] = [
    ['Mensagens de texto', inventario.text],
    ['Áudios', inventario.audio],
    ['Imagens', inventario.image],
    ['PDFs', inventario.pdf],
    ['Vídeos', inventario.video],
    ['Documentos', inventario.document],
    ['Links', inventario.links],
    ['Mensagens do sistema', inventario.system],
  ]

  return (
    <section className="cartao" aria-labelledby="titulo-inventario">
      <h2 id="titulo-inventario">Inventário da conversa</h2>
      <table className="tabela-cobertura">
        <tbody>
          {linhas
            .filter(([, quantidade]) => quantidade > 0)
            .map(([rotulo, quantidade]) => (
              <tr key={rotulo}>
                <th scope="row">{rotulo}</th>
                <td>{quantidade}</td>
              </tr>
            ))}
          <tr>
            <th scope="row">Anexos associados</th>
            <td>
              {inventario.attachmentsMatched} / {inventario.attachmentsReferenced}
            </td>
          </tr>
          <tr>
            <th scope="row">Não associados</th>
            <td>{inventario.attachmentsUnresolved}</td>
          </tr>
          <tr>
            <th scope="row">Arquivos órfãos</th>
            <td>{inventario.orphanFiles}</td>
          </tr>
        </tbody>
      </table>

      {inventario.orphanFiles > 0 && (
        <details>
          <summary>Ver arquivos que não são citados na conversa</summary>
          <ul className="fraco">
            {inventario.orphanNames.map((nome) => (
              <li key={nome}>{nome}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
