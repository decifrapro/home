import type { Job } from '../api/tipos'
import { Cobertura } from './Cobertura'
import { NOME_POR_CATEGORIA, NOME_POR_STATUS_DO_JOB, formatarDinheiro } from './comum'
import { Progresso } from './Progresso'

interface Props {
  job: Job
  aoConfirmar: () => void
  aoCancelar: () => void
  aoVerConversa: () => void
  ocupado?: boolean
}

/** Acompanhamento do processamento e a confirmação de custo antes de gastar. */
export function TelaProcessando({ job, aoConfirmar, aoCancelar, aoVerConversa, ocupado }: Props) {
  const emAndamento = ['uploaded', 'parsing', 'processing'].includes(job.status)
  const aguardando = job.status === 'awaiting_confirmation'

  return (
    <div className="pagina">
      <section className="cartao">
        <h1>{aguardando ? 'Pronto para decifrar' : `Atendimento ${NOME_POR_STATUS_DO_JOB[job.status]}`}</h1>
        <p className="fraco">
          {job.originalFilename} · {job.eventCount} eventos
        </p>

        {emAndamento && <Progresso job={job} />}

        {job.error && (
          <p className="aviso aviso--erro" role="alert">
            {job.error}
          </p>
        )}

        {job.warnings.map((aviso) => (
          <p className="aviso" key={aviso.code}>
            {aviso.message}
            {aviso.detail && <span className="fraco"> {aviso.detail}</span>}
          </p>
        ))}
      </section>

      {aguardando && job.estimate && (
        <section className="cartao">
          <h2>Estimativa de custo</h2>
          <p>
            Processar as mídias deste atendimento deve custar cerca de{' '}
            <strong>{formatarDinheiro(job.estimate.total_usd)}</strong>. O teto configurado é{' '}
            {formatarDinheiro(job.estimate.cap_usd)}.
          </p>
          <table className="tabela-cobertura">
            <tbody>
              {job.estimate.audio_seconds > 0 && (
                <tr>
                  <th scope="row">Áudios</th>
                  <td>{Math.round(job.estimate.audio_seconds / 60)} min</td>
                </tr>
              )}
              {job.estimate.images > 0 && (
                <tr>
                  <th scope="row">Imagens</th>
                  <td>{job.estimate.images}</td>
                </tr>
              )}
              {job.estimate.pdf_pages > 0 && (
                <tr>
                  <th scope="row">Páginas de PDF</th>
                  <td>{job.estimate.pdf_pages}</td>
                </tr>
              )}
              {job.estimate.video_frames > 0 && (
                <tr>
                  <th scope="row">Vídeos</th>
                  <td>
                    {Math.round(job.estimate.video_seconds)}s · {job.estimate.video_frames} quadros
                  </td>
                </tr>
              )}
              {job.estimate.links > 0 && (
                <tr>
                  <th scope="row">Links</th>
                  <td>{job.estimate.links}</td>
                </tr>
              )}
            </tbody>
          </table>
          {job.estimate.notes.map((nota) => (
            <p className="fraco" key={nota}>
              {nota}
            </p>
          ))}
          <div className="linha">
            <button type="button" className="botao" onClick={aoConfirmar} disabled={ocupado}>
              Decifrar as mídias
            </button>
            <button type="button" className="botao botao--secundario" onClick={aoVerConversa}>
              Ver a conversa sem decifrar
            </button>
          </div>
        </section>
      )}

      {job.eventCount > 0 && <Cobertura job={job} />}

      <div className="linha">
        {emAndamento && (
          <button type="button" className="botao botao--secundario" onClick={aoCancelar}>
            Cancelar processamento
          </button>
        )}
        {job.eventCount > 0 && (
          <button type="button" className="botao" onClick={aoVerConversa}>
            Ver conversa completa
          </button>
        )}
      </div>

      {job.cost.totalUsd > 0 && (
        <p className="fraco">
          Custo consumido até aqui: {formatarDinheiro(job.cost.totalUsd)}
          {Object.entries(job.cost)
            .filter(([chave, valor]) => chave.endsWith('_usd') && valor > 0)
            .map(([chave, valor]) => ` · ${NOME_POR_CATEGORIA[chave.replace('_usd', '')] ?? chave}: ${formatarDinheiro(valor)}`)
            .join('')}
        </p>
      )}
    </div>
  )
}
