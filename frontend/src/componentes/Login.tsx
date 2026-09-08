import { useState } from 'react'

import { api } from '../api/cliente'

/** Gate de acesso por senha, ativado por variável de ambiente no servidor. */
export function Login({ aoEntrar, appName }: { aoEntrar: () => void; appName: string }) {
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)

  return (
    <div className="pagina">
      <form
        className="cartao"
        onSubmit={async (evento) => {
          evento.preventDefault()
          setOcupado(true)
          setErro(null)
          try {
            await api.entrar(senha)
            aoEntrar()
          } catch (falha) {
            setErro((falha as Error).message)
          } finally {
            setOcupado(false)
          }
        }}
      >
        <h1>{appName}</h1>
        <p className="fraco">Este aplicativo está protegido por senha.</p>
        <p>
          <label htmlFor="senha">Senha de acesso</label>
          <br />
          <input
            id="senha"
            type="password"
            value={senha}
            onChange={(evento) => setSenha(evento.target.value)}
            autoComplete="current-password"
            style={{ width: '100%' }}
          />
        </p>
        {erro && (
          <p className="aviso aviso--erro" role="alert">
            {erro}
          </p>
        )}
        <button type="submit" className="botao" disabled={ocupado}>
          {ocupado ? 'Entrando…' : 'Entrar'}
        </button>
      </form>
    </div>
  )
}
