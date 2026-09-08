/** Registro do service worker. Só o app shell é cacheado — nada de conversa. */
export function registrarServiceWorker() {
  if (!('serviceWorker' in navigator)) return
  if (import.meta.env?.DEV) return
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      /* sem service worker o aplicativo continua funcionando normalmente */
    })
  })
}
