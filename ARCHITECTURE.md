# Arquitetura — Decifra Pro

## Ideia central

O `.txt` da exportação é a **fonte da cronologia**. Todo o resto — mídia, anexo,
transcrição, descrição, leitura de PDF, conteúdo de link — é conteúdo pendurado
em um evento que já tem posição definida no tempo. Nada é reordenado por data de
arquivo, nada é reconstruído por nome de arquivo.

Por isso o sistema tem duas fases bem separadas:

```
ZIP ──► FASE 1: MOTOR ─────────────► timeline fiel, mídias em "pending"
                                          │
                                          ▼
                              FASE 2: PROCESSADORES ──► conteúdo decifrado
```

A fase 1 não faz nenhuma chamada de IA e não custa dinheiro. A fase 2 preenche
o campo de conteúdo processado de cada evento, um processador por tipo de mídia,
sem nunca mexer no conteúdo original.

## Um servidor só

```
┌──────────────────────── container ────────────────────────┐
│  uvicorn                                                  │
│   ├── FastAPI  (/api/…) …………… requisições curtas          │
│   ├── frontend compilado ……… servido como arquivos        │
│   └── JobRunner (asyncio) ……… trabalho longo em background│
│                                                            │
│  /data ├── decifra.sqlite3  (status, eventos, links)       │
│        └── jobs/<id>/ ├── conversa.zip                     │
│                       ├── upload/  (partes do upload)      │
│                       ├── extracted/ (conteúdo do ZIP)     │
│                       └── work/  (conversões temporárias)  │
└────────────────────────────────────────────────────────────┘
```

Sem microserviços, sem fila externa, sem Redis. O worker roda no mesmo processo,
em tarefa separada do request HTTP: fechar a aba não interrompe nada, e o status
vive no SQLite — o servidor pode reiniciar e retomar (`JobRunner.pending_tasks`).

## Fluxo de um atendimento

```
POST /api/jobs                  cria o atendimento
POST …/upload/init              declara nome, tamanho e nº de partes
PUT  …/upload/chunk?index=N     uma parte por vez (retry por parte)
POST …/upload/complete          junta, confere tamanho/sha256, enfileira o parse
        │
        ▼
 parse_job()   extrai o ZIP com limites  → cataloga arquivos (magic bytes)
               escolhe o TXT principal   → parseia a conversa
               associa anexos            → monta a timeline
               calcula inventário/cobertura e a estimativa de custo
        │
        ├── sem provedor de IA  → job "partial", mídias pendentes
        └── com provedor        → job "awaiting_confirmation"
                                       │  POST …/confirm
                                       ▼
 process_job() semáforo por tipo, teto de custo, retry do provedor
               cada item vira done | failed | unsupported | unresolved
               cobertura recalculada → job "completed" ou "partial"
```

## Mapa dos módulos

| Caminho | Responsabilidade |
| --- | --- |
| `backend/app/config.py` | Toda a configuração (nome, limites, modelos, preços) |
| `backend/app/parsers/whatsapp.py` | Leitura do TXT: cabeçalhos, multilinha, anexos, mídia oculta, URLs |
| `backend/app/services/zip_service.py` | Extração segura (Zip Slip, zip bomb, limites) e escolha do TXT |
| `backend/app/services/mime.py` | Tipo real por magic bytes; a extensão é só palpite |
| `backend/app/services/matcher.py` | Associação TXT ↔ arquivo, do estrito ao tolerante, sem chute |
| `backend/app/services/timeline.py` | Junta parse + arquivos e produz os eventos e o inventário |
| `backend/app/services/coverage.py` | Cobertura por categoria; 100% só quando é 100% |
| `backend/app/services/cost.py` | Estimativa antes de gastar e contabilidade do custo real |
| `backend/app/services/exporters.py` | TXT, Markdown e JSON, sempre com os dois níveis de conteúdo |
| `backend/app/processors/*` | Um processador por mídia, com contrato comum em `base.py` |
| `backend/app/providers/*` | Abstração do provedor de IA (hoje OpenAI) |
| `backend/app/jobs/worker.py` | Fila, concorrência, teto de custo, retomada e retenção |
| `backend/app/api/*` | Endpoints HTTP e o gate opcional por senha |
| `frontend/src/upload/enviarZip.ts` | Upload em partes com progresso, retry e cancelamento |
| `frontend/src/componentes/*` | Telas: envio, processamento, timeline, instalação |
| `frontend/src/estilos/tema.css` | Tema único, com as cores de `MARCA.md` |

## Estados

**Job**: `created → uploading → uploaded → parsing → awaiting_confirmation →
processing → completed | partial`, além de `failed` e `cancelled`.

`awaiting_confirmation` existe porque processar mídia custa dinheiro: o usuário
vê a estimativa antes de autorizar. Com `AUTO_CONFIRM_PROCESSING=true` o passo é
pulado.

**Evento**: `pending → processing → done | failed | unsupported | unresolved`.

- `unresolved` — o TXT citou um arquivo que não existe no ZIP (ou havia dois com
  o mesmo nome, e associar seria chute).
- `unsupported` — o formato não é lido, ou a exportação veio sem mídia.
- `failed` — deu erro de verdade; fica visível e pode ser reprocessado.

Nenhum desses estados apaga o evento da timeline.

## Extensão: um novo tipo de mídia

1. Implemente `MediaProcessor` em `backend/app/processors/`, com `category`,
   `handles` e `process()` devolvendo `ProcessingOutcome`.
2. Registre em `processors/registry.py` (e, se precisar de semáforo próprio,
   acrescente a categoria em `CONCURRENCY_KEYS`).
3. Se o custo for relevante, some a estimativa em `services/cost.py`.
4. Se a apresentação for específica, trate o tipo em `services/exporters.py` e
   em `frontend/src/componentes/EventoCartao.tsx`.

## Extensão: outro provedor de IA

Implemente o protocolo `AIProvider` (`transcribe` e `describe_image`) em
`backend/app/providers/` e devolva-o em `build_provider()`. Os processadores não
sabem qual provedor está em uso, e nenhum nome de modelo aparece fora dessa camada.

## Decisões e por quê

- **SQLite, não Postgres** — um usuário por vez, um servidor, dados temporários.
  Sobrevive a reinício com volume persistente e não pede infraestrutura extra.
- **Worker no mesmo processo** — evita fila externa; o volume de trabalho é de
  um atendimento por vez, com paralelismo dentro do job.
- **Extração em disco, em streaming** — ZIPs de centenas de MB não cabem
  confortavelmente na memória, nem no navegador nem no servidor.
- **Associação conservadora** — mostrar “arquivo não associado” é melhor do que
  colar o conteúdo de uma mídia na mensagem errada.
- **Conteúdo original e conteúdo de IA sempre separados** — no banco, na API, na
  tela e nos três exports.
- **Modo claro por padrão** — a tela é um paredão de texto longo (`MARCA.md`).

## Versão do JSON exportado

`schemaVersion: 2`.

- **1** — Parte 1: timeline fiel, mídias em `pending`, sem conteúdo processado.
- **2** — Parte 2: acrescenta `processed.text`, `links` processados como
  subitens, `coverage`, `cost` e metadados de mídia por evento.
