import { useEffect, useState } from 'react'

import { api } from '../api/cliente'
import type { DadosDoAtalho } from '../api/tipos'
import { ehIosOuIpad } from './InstalarApp'

/**
 * Enviar do WhatsApp em um toque, pelo iPhone.
 *
 * A Apple só deixa aparecer no botão Compartilhar um aplicativo publicado na App
 * Store. O caminho que existe, e não custa nada, é o app Atalhos: um atalho
 * montado uma vez aparece no Compartilhar como se fosse um aplicativo. A partir
 * daí é WhatsApp → Compartilhar → tocar no atalho, e pronto.
 */
export function AtalhoIphone() {
  const [dados, setDados] = useState<DadosDoAtalho | null>(null)
  const [aberto, setAberto] = useState(false)
  const [mostrarChave, setMostrarChave] = useState(false)
  const [copiado, setCopiado] = useState<string | null>(null)

  useEffect(() => {
    api
      .atalho()
      .then(setDados)
      .catch(() => setDados(null))
  }, [])

  if (!dados) return null

  async function copiar(rotulo: string, valor: string) {
    try {
      await navigator.clipboard.writeText(valor)
      setCopiado(rotulo)
      setTimeout(() => setCopiado(null), 2000)
    } catch {
      setCopiado(null)
    }
  }

  if (!dados.disponivel) {
    return (
      <section className="cartao">
        <h2>Enviar direto do WhatsApp (iPhone)</h2>
        <p className="fraco">{dados.motivo}</p>
      </section>
    )
  }

  const chave = dados.chave ?? ''
  const chaveVisivel = mostrarChave ? chave : '•'.repeat(40)

  return (
    <section className="cartao">
      <h2>Enviar direto do WhatsApp (iPhone)</h2>
      <p className="fraco">
        Dá para mandar a conversa sem abrir este aplicativo: no WhatsApp, toque em Compartilhar e
        escolha o atalho. Você monta o atalho uma vez, em uns cinco minutos, e nunca mais mexe.
        {!ehIosOuIpad() && ' Faça isso pelo próprio iPhone — é lá que o app Atalhos existe.'}
      </p>

      <div className="linha">
        <button
          type="button"
          className="botao botao--secundario"
          onClick={() => setAberto(!aberto)}
          aria-expanded={aberto}
        >
          {aberto ? 'Esconder o passo a passo' : 'Ver o passo a passo'}
        </button>
        <button
          type="button"
          className="botao botao--secundario"
          onClick={() => copiar('chave', chave)}
        >
          {copiado === 'chave' ? 'Chave copiada' : 'Copiar minha chave'}
        </button>
      </div>

      {aberto && (
        <div style={{ marginTop: 14 }}>
          <p className="aviso">
            A chave abaixo vale como senha: quem tiver ela pode mandar conversas para o seu
            aplicativo. Cole apenas dentro do atalho, no seu iPhone.
          </p>

          <ValorParaCopiar
            rotulo="Minha chave"
            valor={chaveVisivel}
            aoCopiar={() => copiar('chave', chave)}
            copiado={copiado === 'chave'}
            extra={
              <button
                type="button"
                className="botao botao--secundario botao--pequeno"
                onClick={() => setMostrarChave(!mostrarChave)}
              >
                {mostrarChave ? 'Esconder' : 'Mostrar'}
              </button>
            }
          />

          <h3 style={{ marginTop: 16 }}>No iPhone, abra o app Atalhos e crie um atalho novo</h3>
          <ol>
            <li>
              Toque em <strong>+</strong> para criar. No topo, abra as informações do atalho e
              ligue <strong>Mostrar no Menu Compartilhar</strong>. Em “Tipos de entrada”, deixe
              marcado <strong>Arquivos</strong>.
            </li>
            <li>
              Dê o nome de <strong>Decifra Pro</strong> — é esse nome que vai aparecer no
              Compartilhar do WhatsApp.
            </li>
            <li>
              Adicione a ação <strong>Obter conteúdo do URL</strong> e preencha:
              <ul>
                <li>
                  URL: <code>{dados.urlPreparar}</code>
                </li>
                <li>
                  Método: <strong>POST</strong>
                </li>
                <li>
                  Cabeçalho: <code>{dados.cabecalho}</code> com o valor da sua chave
                </li>
                <li>
                  Corpo da requisição: <strong>JSON</strong>, com um campo de texto chamado{' '}
                  <code>filename</code> e o valor <code>conversa.zip</code>
                </li>
              </ul>
            </li>
            <li>
              Adicione <strong>Definir variável</strong> com o nome <code>Resposta</code>.
            </li>
            <li>
              Adicione outra <strong>Obter conteúdo do URL</strong>:
              <ul>
                <li>
                  URL: use <strong>Obter valor do dicionário</strong> <code>uploadUrl</code> da
                  variável <code>Resposta</code>
                </li>
                <li>
                  Método: <strong>PUT</strong>
                </li>
                <li>
                  Corpo da requisição: <strong>Arquivo</strong> → escolha{' '}
                  <strong>Entrada do Atalho</strong>
                </li>
              </ul>
            </li>
            <li>
              Adicione a última <strong>Obter conteúdo do URL</strong>:
              <ul>
                <li>
                  URL: <code>{dados.urlConcluir}</code>
                </li>
                <li>
                  Método: <strong>POST</strong>, mesmo cabeçalho <code>{dados.cabecalho}</code> com
                  a chave
                </li>
                <li>
                  Corpo <strong>JSON</strong>: campo <code>jobId</code> com o valor do dicionário{' '}
                  <code>jobId</code> da variável <code>Resposta</code>
                </li>
              </ul>
            </li>
            <li>
              Termine com <strong>Mostrar notificação</strong> usando o valor do dicionário{' '}
              <code>mensagem</code>. Assim o iPhone avisa que a conversa chegou.
            </li>
          </ol>

          <h3>Como usar depois de pronto</h3>
          <ol>
            <li>No WhatsApp, abra a conversa e exporte com “Incluir mídia”.</li>
            <li>
              Na tela de compartilhar que aparecer, toque em <strong>Decifra Pro</strong>.
            </li>
            <li>Pronto. O aviso do iPhone conta o que foi recebido, e o resto acontece sozinho.</li>
          </ol>

          <p className="fraco">
            Pelo atalho o processamento começa automaticamente, sem passar pela tela de
            confirmação de custo — não haveria ninguém olhando para confirmar. Quem segura o gasto
            é o teto por atendimento, que continua valendo.
          </p>
        </div>
      )}
    </section>
  )
}

function ValorParaCopiar({
  rotulo,
  valor,
  aoCopiar,
  copiado,
  extra,
}: {
  rotulo: string
  valor: string
  aoCopiar: () => void
  copiado: boolean
  extra?: React.ReactNode
}) {
  return (
    <div style={{ marginTop: 10 }}>
      <div className="evento__rotulo">{rotulo}</div>
      <div className="linha">
        <code style={{ overflowWrap: 'anywhere', flex: '1 1 200px' }}>{valor}</code>
        {extra}
        <button type="button" className="botao botao--secundario botao--pequeno" onClick={aoCopiar}>
          {copiado ? 'Copiado' : 'Copiar'}
        </button>
      </div>
    </div>
  )
}
