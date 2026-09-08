/*
 * Service worker do Decifra Pro.
 *
 * Regra de privacidade: só o app shell e os ícones ficam em cache.
 * Nada de /api, nada de ZIP, transcrição, PDF ou conteúdo de conversa —
 * esses dados nunca tocam o cache do navegador.
 */
const VERSAO = 'decifra-shell-v2'
const APP_SHELL = [
  '/',
  '/index.html',
  '/manifest.webmanifest',
  '/icon.svg',
  '/icon-192.png',
  '/icon-512.png',
  '/maskable-512.png',
  '/apple-touch-icon.png',
  '/favicon.ico',
]

self.addEventListener('install', (evento) => {
  evento.waitUntil(
    caches.open(VERSAO).then((cache) => cache.addAll(APP_SHELL)).then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (evento) => {
  evento.waitUntil(
    caches
      .keys()
      .then((chaves) => Promise.all(chaves.filter((chave) => chave !== VERSAO).map((chave) => caches.delete(chave))))
      .then(() => self.clients.claim()),
  )
})

function podeCachear(url) {
  const destino = new URL(url)
  if (destino.origin !== self.location.origin) return false
  if (destino.pathname.startsWith('/api')) return false
  return true
}

self.addEventListener('fetch', (evento) => {
  const requisicao = evento.request
  if (requisicao.method !== 'GET' || !podeCachear(requisicao.url)) return

  const aceita = requisicao.headers.get('accept') || ''
  if (requisicao.mode === 'navigate' || aceita.includes('text/html')) {
    evento.respondWith(fetch(requisicao).catch(() => caches.match('/index.html')))
    return
  }

  evento.respondWith(
    caches.match(requisicao).then((emCache) => {
      if (emCache) return emCache
      return fetch(requisicao).then((resposta) => {
        if (resposta.ok && podeCachear(requisicao.url)) {
          const copia = resposta.clone()
          caches.open(VERSAO).then((cache) => cache.put(requisicao, copia))
        }
        return resposta
      })
    }),
  )
})
