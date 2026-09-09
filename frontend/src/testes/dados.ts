/** Objetos de exemplo usados nos testes de interface. */

import type { Evento, Job } from '../api/tipos'

export function eventoDeTexto(parcial: Partial<Evento> = {}): Evento {
  return {
    id: 'e1',
    index: 0,
    rawTimestamp: '25/08/2026 10:45',
    timestamp: '2026-08-25T10:45:00',
    sender: 'Sanchai',
    type: 'text',
    rawText: 'Boa tarde, Sr. Rui',
    caption: null,
    attachmentName: null,
    detectedMime: null,
    processedText: null,
    processingStatus: 'done',
    processingError: null,
    metadata: {},
    links: [],
    ...parcial,
  }
}

export function eventoDeAudio(parcial: Partial<Evento> = {}): Evento {
  return eventoDeTexto({
    id: 'e2',
    index: 1,
    type: 'audio',
    rawTimestamp: '25/08/2026 10:52',
    rawText: 'PTT-20260825-WA0001.opus (arquivo anexado)',
    attachmentName: 'PTT-20260825-WA0001.opus',
    detectedMime: 'audio/ogg',
    processedText: 'Boa tarde, seu Rui. Sobre aquela sala…',
    processingStatus: 'done',
    metadata: { durationSeconds: 42 },
    ...parcial,
  })
}

export function jobDeExemplo(parcial: Partial<Job> = {}): Job {
  return {
    id: 'job123',
    status: 'partial',
    createdAt: '2026-08-25T10:00:00',
    updatedAt: '2026-08-25T10:30:00',
    originalFilename: 'Conversa do WhatsApp com Cliente.zip',
    zipSize: 1024,
    error: null,
    warnings: [],
    inventory: {
      text: 184,
      audio: 41,
      image: 12,
      pdf: 9,
      video: 2,
      document: 0,
      system: 1,
      unknown: 0,
      links: 4,
      attachmentsReferenced: 64,
      attachmentsMatched: 64,
      attachmentsUnresolved: 0,
      orphanFiles: 0,
      orphanNames: [],
    },
    coverage: {
      categories: {
        text: { total: 185, done: 185, failed: 0, pending: 0, unsupported: 0, partial: 0, unresolved: 0, complete: true },
        audio: { total: 41, done: 40, failed: 1, pending: 0, unsupported: 0, partial: 0, unresolved: 0, complete: false },
      },
      overallTotal: 226,
      overallDone: 225,
      percent: 99.6,
      complete: false,
    },
    estimate: null,
    cost: { audio_usd: 0.12, totalUsd: 0.12 },
    confirmed: true,
    conversationStart: '2026-08-25T10:40:00',
    conversationEnd: '2026-08-25T12:05:00',
    eventCount: 226,
    metadata: {},
    schemaVersion: 2,
    ...parcial,
  }
}
