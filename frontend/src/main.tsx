import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'
import './estilos/tema.css'
import { registrarServiceWorker } from './pwa/registrarServiceWorker'
import { lerTemaSalvo } from './componentes/Tema'

document.documentElement.dataset.tema = lerTemaSalvo()

createRoot(document.getElementById('raiz')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

registrarServiceWorker()
