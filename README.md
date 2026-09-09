# Decifra Pro

Leitor multimodal de conversas exportadas do WhatsApp.

Você envia o ZIP da conversa (com mídia incluída) e recebe a conversa inteira
como uma linha do tempo fiel: os áudios transcritos, as imagens descritas, os
PDFs lidos página a página, os vídeos transcritos e descritos e os links lidos —
cada um na posição exata em que apareceram.

O resultado serve para ler e para colar em outra IA: sai em TXT, Markdown e JSON.

> **O que ele não é.** Não é CRM, não classifica lead, não sugere resposta e não
> interpreta intenção comercial. Também não corrige, resume nem traduz o que foi
> escrito: o conteúdo original é preservado exatamente como veio, e o que a IA
> extrai das mídias aparece sempre em bloco separado e identificado.

---

## Versão

O número aparece ao lado da logo (`v008`) e em `GET /api/config`, no campo
`versao`. Serve para saber, olhando a tela, se o que está publicado já contém
determinado ajuste.

**Regra:** todo ajuste publicado sobe o número em um. A fonte única é
`backend/app/versao.py`; nenhum outro lugar guarda cópia.

---

## Índice

- [Dois jeitos de rodar](#dois-jeitos-de-rodar)
- [Publicar na Vercel com Supabase (passo a passo)](#publicar-na-vercel-com-supabase-passo-a-passo)
- [Requisitos](#requisitos)
- [Rodar com Docker](#rodar-com-docker)
- [Rodar em desenvolvimento](#rodar-em-desenvolvimento)
- [Abrir pelo celular na rede local](#abrir-pelo-celular-na-rede-local)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Processar a primeira conversa](#processar-a-primeira-conversa)
- [Custo](#custo)
- [Trocar os modelos de IA](#trocar-os-modelos-de-ia)
- [Instalar como aplicativo](#instalar-como-aplicativo)
- [Mandar pelo celular, ler no computador](#mandar-pelo-celular-ler-no-computador)
- [Enviar direto do WhatsApp no iPhone](#enviar-direto-do-whatsapp-no-iphone)
- [Publicar](#publicar)
- [Apagar um atendimento](#apagar-um-atendimento)
- [Limites](#limites)
- [Testes](#testes)
- [Solução de problemas](#solução-de-problemas)
- [Privacidade](#privacidade)

---

## Dois jeitos de rodar

O mesmo código roda de duas formas. A diferença está no que a máquina por baixo
permite fazer.

| | **Vercel + Supabase** | **Servidor próprio** (Docker, VPS) |
| --- | --- | --- |
| Texto, áudio, imagem, PDF, link | ✅ | ✅ |
| Vídeo | ❌ fica marcado como não analisado | ✅ transcrito e descrito |
| Áudio muito longo (acima de 24 MB) | ❌ fica de fora, com aviso | ✅ dividido e transcrito inteiro |
| Onde ficam os dados | Supabase (banco e arquivos) | disco do servidor |
| Processa com o app fechado | ✅ pelo agendamento automático | ✅ pelo processo do servidor |
| Custo de hospedagem | o que você já paga | a partir de uns US$ 5/mês |

O motivo da diferença é uma só ferramenta: o **FFmpeg**, que corta áudio e extrai
cenas de vídeo. Ele precisa estar instalado na máquina, e a Vercel não permite
instalar programas assim. Sem ele:

- o áudio do WhatsApp continua sendo transcrito — o `.opus` é enviado como
  `.ogg`, sem conversão nenhuma;
- **do vídeo sai a transcrição da fala** (o MP4 vai inteiro para a transcrição,
  que aceita esse formato), mas **não sai a descrição do que aparece na
  imagem** — para isso seria preciso extrair quadros, e é aí que o FFmpeg faz
  falta. Por isso o vídeo continua contando como não decifrado, e a cobertura
  não chega a 100%.

Você escolhe preenchendo (ou não) as variáveis do Supabase. Sem elas, o sistema
usa disco e banco locais; com elas, passa a usar o Supabase.

---

## Mandar pelo celular, ler no computador

Exportar conversa só existe no celular — o WhatsApp não oferece isso no
WhatsApp Web nem no aplicativo de computador. Mas ler uma conversa longa é bem
melhor na tela grande, então o caminho natural é este:

1. **No celular**, envie a conversa (pelo atalho, ou escolhendo o arquivo).
2. **No computador**, abra o mesmo endereço. A conversa está esperando em
   **Conversas enviadas**, na tela inicial.

Não precisa transferir arquivo entre aparelhos, nem copiar link: é o mesmo
servidor, e a lista mostra tudo que foi enviado de qualquer aparelho.

No computador dá também para **arrastar** o ZIP para a área de envio ou
**colar** com Ctrl+V, se o arquivo já estiver na sua máquina.

---

## Enviar direto do WhatsApp no iPhone

No Android, um aplicativo instalado pela tela de início pode aparecer no botão
Compartilhar. No iPhone isso não existe: a Apple só deixa aparecer ali um
aplicativo publicado na App Store.

A saída, sem loja e sem custo, é o app **Atalhos**, que já vem no iPhone. Um
atalho montado uma vez aparece no Compartilhar como se fosse um aplicativo. Aí o
uso fica assim:

```
WhatsApp → Exportar conversa (com mídia) → Compartilhar → Decifra Pro → pronto
```

Não precisa abrir o aplicativo, nem salvar em Arquivos, nem procurar o arquivo.
O iPhone avisa por notificação o que foi recebido, e o processamento começa
sozinho — sem passar pela tela de confirmação de custo, porque não há ninguém
olhando para confirmar. Quem segura o gasto continua sendo o `MAX_JOB_COST_USD`.

**Como montar:** abra o Decifra Pro, na tela inicial, no cartão *Enviar direto do
WhatsApp (iPhone)* → **Ver o passo a passo**. Ali estão a sua chave pessoal e a
sequência exata de ações, com os endereços já preenchidos. Leva uns cinco
minutos, uma vez só.

**Duas coisas que fazem o atalho parecer quebrado, e não estão quebradas:**

1. **O atalho não aparece entre os ícones de aplicativo** no topo da tela de
   compartilhar. A Apple só coloca ali aplicativo baixado da App Store. Ele fica
   na **lista de baixo**, junto de “Copiar” e “Salvar em Arquivos”, e pode ser
   fixado no topo por *Editar ações*.
2. **Mandar o arquivo direto para a função dá erro silencioso.** A Vercel recusa
   requisição acima de ~4,5 MB, e uma conversa com mídia passa longe disso. Por
   isso o atalho daqui pede um endereço antes e manda o arquivo **direto para o
   armazenamento** — o ZIP nunca passa pela função.

O cartão mostra **a última vez que o atalho falou com o servidor**. Se continuar
em “nunca” depois de você rodar o atalho, o problema é do lado do iPhone (chave
colada errada, ou a ação de envio mal configurada) e não do servidor.

**Sobre a chave:** ela vale como senha — quem a tiver pode mandar conversas para
o seu aplicativo. Ela é derivada do `APP_SESSION_SECRET` do servidor, não fica
guardada em lugar nenhum, e trocar esse segredo invalida a chave antiga (é assim
que se revoga). Sem `APP_SESSION_SECRET` definido, o cartão explica que falta
configurar isso em vez de entregar uma chave que mudaria sozinha.

**Por dentro**, o atalho faz três chamadas: pede um endereço de envio
(`/api/atalho/preparar`), manda o arquivo direto para o armazenamento e avisa que
terminou (`/api/atalho/concluir`). O arquivo nunca passa pela função da Vercel,
então o limite de tamanho de requisição não atrapalha.

---

## Publicar na Vercel com Supabase (passo a passo)

Escrito para ser seguido sem saber programar. São uns 15 minutos.

### 1. Preparar o Supabase (guarda os arquivos e os dados)

1. Entre em <https://supabase.com> e abra um projeto — pode ser um que você já
   tenha. Nada aqui atrapalha outro sistema: as tabelas começam com `decifra_` e
   os arquivos ficam num espaço separado.
2. No menu lateral, abra **SQL Editor** → **New query**.
3. Abra o arquivo `supabase/migrations/0001_decifra.sql` deste repositório, copie
   tudo, cole na janela e clique em **Run**. Deve aparecer "Success".
4. Vá em **Project Settings → API** e guarde dois valores:
   - **Project URL** (algo como `https://abcdefgh.supabase.co`);
   - a chave **service_role** (a secreta, não a `anon`).

> A chave `service_role` dá acesso total ao projeto. Ela vai **só** no painel da
> Vercel, nunca em arquivo do repositório e nunca no navegador.

### 2. Publicar na Vercel

1. Em <https://vercel.com>, clique em **Add New → Project** e escolha este
   repositório.
2. Não mexa em nada na tela de build: o arquivo `vercel.json` já diz o que fazer.
3. Antes de clicar em **Deploy**, abra **Environment Variables** e cadastre:

   | Nome | Valor |
   | --- | --- |
   | `SUPABASE_URL` | a Project URL do passo 1 |
   | `SUPABASE_SERVICE_ROLE_KEY` | a chave service_role do passo 1 |
   | `OPENAI_API_KEY` | sua chave da OpenAI |
   | `APP_ACCESS_PASSWORD` | uma senha sua, para o site não ficar aberto |
   | `APP_SESSION_SECRET` | qualquer texto longo e aleatório |
   | `MAX_JOB_COST_USD` | teto de gasto por conversa (ex.: `5`) |

4. Clique em **Deploy** e espere. No fim, abra o endereço que a Vercel mostrar.

### 3. Conferir se ficou tudo certo

- Abra `https://seu-endereco.vercel.app/api/health` — deve aparecer
  `{"status":"ok", ...}`.
- Abra o site, digite a senha e envie um ZIP pequeno de conversa.

### Sobre o plano da Vercel

O `vercel.json` já vem com o agendamento que continua o processamento quando o
aplicativo está fechado, rodando **a cada minuto**. Isso exige o plano Pro. No
plano gratuito (Hobby), a Vercel só aceita agendamento **uma vez por dia**: mude
a linha `"schedule": "* * * * *"` para `"schedule": "0 3 * * *"`. O sistema
continua funcionando — só que o processamento anda enquanto o aplicativo estiver
aberto na tela, o que para uma conversa normal leva poucos minutos.

O tempo máximo de cada chamada também muda: `maxDuration: 300` é do plano Pro.
No Hobby, troque para `60`. O processamento é feito em blocos justamente para
caber nos dois casos.

---

## Requisitos

Para rodar com Docker, só Docker.

Para desenvolvimento local:

- Python 3.11+
- Node.js 20+
- **FFmpeg e ffprobe** (obrigatórios para áudio e vídeo)
- libmagic (opcional; melhora a detecção de tipo de arquivo)

```bash
# Debian / Ubuntu
sudo apt-get install ffmpeg libmagic1

# macOS
brew install ffmpeg libmagic
```

---

## Rodar com Docker

```bash
cp .env.example .env      # ajuste o que precisar
docker compose up --build
```

Abra <http://localhost:8000>.

O `docker-compose.yml` monta `./data` no `/data` do container: os atendimentos
sobrevivem a reinícios. Sem esse volume, tudo é perdido quando o container morre.

Sem `OPENAI_API_KEY` o sistema roda em modo somente-motor: a conversa é montada
com o texto completo e as mídias ficam pendentes, com aviso claro na tela.

---

## Rodar em desenvolvimento

Dois terminais.

**Backend**

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
DATA_DIR=../data .venv/bin/uvicorn app.main:app --reload --port 8000
```

**Frontend**

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173, com proxy para a API na porta 8000
```

O frontend em desenvolvimento encaminha `/api` para `http://localhost:8000`.
Para apontar para outro backend: `VITE_API_TARGET=http://192.168.0.10:8000 npm run dev`.

Em produção o backend serve o frontend compilado (`FRONTEND_DIST`), tudo na
mesma porta.

---

## Abrir pelo celular na rede local

1. Descubra o IP do computador (`ip addr` no Linux, `ipconfig` no Windows,
   `ipconfig getifaddr en0` no macOS).
2. Suba o servidor (Docker, ou `npm run dev` — o Vite já escuta em toda a rede).
3. No celular, na mesma rede Wi-Fi, abra `http://SEU_IP:8000`.

Para **instalar como aplicativo** o navegador exige HTTPS (ou `localhost`). Em
rede local sem HTTPS o site funciona normalmente, mas o botão de instalar não
aparece — veja [Publicar](#publicar).

---

## Variáveis de ambiente

Tudo está em `.env.example`, comentado. As que mais importam:

| Variável | Para quê |
| --- | --- |
| `APP_NAME` | Nome exibido no aplicativo (backend e frontend leem daqui) |
| `DATA_DIR` | Onde ficam banco e arquivos dos atendimentos (`/data` no container) |
| `APP_ACCESS_PASSWORD` | Vazia: app aberto. Preenchida: exige senha antes do upload |
| `OPENAI_API_KEY` | Chave do provedor de IA. **Só no servidor**, nunca no frontend |
| `OPENAI_TRANSCRIPTION_MODEL` | Modelo de transcrição (padrão `gpt-4o-transcribe`) |
| `OPENAI_VISION_MODEL` | Modelo de visão (padrão `gpt-4.1-mini`) |
| `MAX_JOB_COST_USD` | Teto de gasto por atendimento |
| `AUTO_CONFIRM_PROCESSING` | `true` (padrão) decifra as mídias assim que o ZIP é lido; `false` mostra a tela de confirmação de custo antes |
| `JOB_RETENTION_HOURS` | Depois disso o atendimento é apagado automaticamente |
| `MAX_ZIP_MB` e afins | Limites de upload e de extração |
| `*_CONCURRENCY` | Quantas chamadas simultâneas por tipo de mídia |
| `ENABLE_PLAYWRIGHT` | Fallback de navegador headless para links com JavaScript |

---

## Processar a primeira conversa

1. **No celular**, abra a conversa no WhatsApp → nome do contato → *Exportar
   conversa* → **Incluir mídia**. Salve o ZIP.
2. Abra o Decifra Pro e arraste o ZIP (ou toque para selecionar). O upload é
   feito em partes, com progresso real; se a rede cair, a parte é reenviada.
3. O servidor lê a conversa e mostra o **inventário**: quantos textos, áudios,
   imagens, PDFs, vídeos e links existem, quantos anexos foram associados, o que
   ficou sem associação e quais arquivos do ZIP não são citados na conversa.
4. Com IA configurada, aparece a **estimativa de custo**. Você decide se autoriza.
5. O processamento roda no servidor: pode bloquear a tela, trocar de aplicativo
   ou fechar a aba. Ao voltar, o progresso continua.
6. No final, leia a conversa, copie o histórico ou baixe TXT, Markdown ou JSON.

Se algum item falhar, ele **continua visível** na posição certa, com o motivo, e
pode ser reprocessado sozinho ou em bloco.

---

## Custo

Processar mídia custa dinheiro de verdade. O sistema:

- estima o custo antes de começar e pede confirmação;
- respeita o teto `MAX_JOB_COST_USD` — ao atingir, pausa, marca o atendimento
  como parcial e avisa, sem apagar nada;
- registra o custo real consumido por categoria, na tela e no JSON exportado.

Só o que passa por IA custa: transcrição de áudio e de vídeo, visão em imagens e
em páginas de PDF sem texto extraível. Texto do WhatsApp, PDFs com texto e
leitura de links são processados no próprio servidor, de graça.

Os preços usados na estimativa vêm do `.env`
(`PRICE_TRANSCRIPTION_PER_MINUTE`, `PRICE_VISION_INPUT_PER_MTOK`,
`PRICE_VISION_OUTPUT_PER_MTOK`) — ajuste conforme o seu contrato.

---

## Trocar os modelos de IA

Nenhum nome de modelo está escrito no código: mude no `.env` e reinicie.

```env
OPENAI_TRANSCRIPTION_MODEL=gpt-4o-transcribe
OPENAI_VISION_MODEL=gpt-4.1-mini
```

Para outro provedor compatível com a API da OpenAI, aponte `OPENAI_BASE_URL`
para ele. Para um provedor com API diferente, implemente o protocolo
`AIProvider` (veja `ARCHITECTURE.md` → *Extensão: outro provedor de IA*).

---

## Instalar como aplicativo

Precisa estar em HTTPS (ou `localhost`).

**Android (Chrome)** — o navegador oferece o fluxo nativo e o aplicativo mostra
o botão **Instalar aplicativo**. Se já estiver instalado, o botão não aparece.

**iPhone e iPad (Safari)** — o iOS não tem prompt automático:

1. Toque no botão **Compartilhar** (quadrado com seta para cima).
2. Role e escolha **Adicionar à Tela de Início**.
3. Confirme em **Adicionar**.

O aplicativo mostra essa instrução no primeiro acesso; ela é dispensável e não
bloqueia o uso.

**Desktop (Chrome/Edge)** — ícone de instalar na barra de endereço.

---

## Mandar pelo celular, ler no computador

Exportar conversa só existe no celular — o WhatsApp não oferece isso no
WhatsApp Web nem no aplicativo de computador. Mas ler uma conversa longa é bem
melhor na tela grande, então o caminho natural é este:

1. **No celular**, envie a conversa (pelo atalho, ou escolhendo o arquivo).
2. **No computador**, abra o mesmo endereço. A conversa está esperando em
   **Conversas enviadas**, na tela inicial.

Não precisa transferir arquivo entre aparelhos, nem copiar link: é o mesmo
servidor, e a lista mostra tudo que foi enviado de qualquer aparelho.

No computador dá também para **arrastar** o ZIP para a área de envio ou
**colar** com Ctrl+V, se o arquivo já estiver na sua máquina.

---

## Enviar direto do WhatsApp no iPhone

No Android, um aplicativo instalado pela tela de início pode aparecer no botão
Compartilhar. No iPhone isso não existe: a Apple só deixa aparecer ali um
aplicativo publicado na App Store.

A saída, sem loja e sem custo, é o app **Atalhos**, que já vem no iPhone. Um
atalho montado uma vez aparece no Compartilhar como se fosse um aplicativo. Aí o
uso fica assim:

```
WhatsApp → Exportar conversa (com mídia) → Compartilhar → Decifra Pro → pronto
```

Não precisa abrir o aplicativo, nem salvar em Arquivos, nem procurar o arquivo.
O iPhone avisa por notificação o que foi recebido, e o processamento começa
sozinho — sem passar pela tela de confirmação de custo, porque não há ninguém
olhando para confirmar. Quem segura o gasto continua sendo o `MAX_JOB_COST_USD`.

**Como montar:** abra o Decifra Pro, na tela inicial, no cartão *Enviar direto do
WhatsApp (iPhone)* → **Ver o passo a passo**. Ali estão a sua chave pessoal e a
sequência exata de ações, com os endereços já preenchidos. Leva uns cinco
minutos, uma vez só.

**Duas coisas que fazem o atalho parecer quebrado, e não estão quebradas:**

1. **O atalho não aparece entre os ícones de aplicativo** no topo da tela de
   compartilhar. A Apple só coloca ali aplicativo baixado da App Store. Ele fica
   na **lista de baixo**, junto de “Copiar” e “Salvar em Arquivos”, e pode ser
   fixado no topo por *Editar ações*.
2. **Mandar o arquivo direto para a função dá erro silencioso.** A Vercel recusa
   requisição acima de ~4,5 MB, e uma conversa com mídia passa longe disso. Por
   isso o atalho daqui pede um endereço antes e manda o arquivo **direto para o
   armazenamento** — o ZIP nunca passa pela função.

O cartão mostra **a última vez que o atalho falou com o servidor**. Se continuar
em “nunca” depois de você rodar o atalho, o problema é do lado do iPhone (chave
colada errada, ou a ação de envio mal configurada) e não do servidor.

**Sobre a chave:** ela vale como senha — quem a tiver pode mandar conversas para
o seu aplicativo. Ela é derivada do `APP_SESSION_SECRET` do servidor, não fica
guardada em lugar nenhum, e trocar esse segredo invalida a chave antiga (é assim
que se revoga). Sem `APP_SESSION_SECRET` definido, o cartão explica que falta
configurar isso em vez de entregar uma chave que mudaria sozinha.

**Por dentro**, o atalho faz três chamadas: pede um endereço de envio
(`/api/atalho/preparar`), manda o arquivo direto para o armazenamento e avisa que
terminou (`/api/atalho/concluir`). O arquivo nunca passa pela função da Vercel,
então o limite de tamanho de requisição não atrapalha.

---

## Publicar

Duas opções, conforme a tabela de [Dois jeitos de rodar](#dois-jeitos-de-rodar).

**Vercel + Supabase** — o caminho mais simples se você já usa esses dois
serviços: siga [o passo a passo acima](#publicar-na-vercel-com-supabase-passo-a-passo).
Vale lembrar do que fica de fora ali: do vídeo sai só a fala transcrita, sem
descrição da imagem, e áudio acima de 24 MB não é transcrito — porque a Vercel
não permite instalar o FFmpeg.

**Servidor próprio** — para ter tudo, inclusive vídeo. Note que **GitHub Pages
não serve**: ele publica só páginas paradas, e aqui é preciso receber arquivo
grande, converter mídia e rodar tarefa longa.

Roda em qualquer host que aceite um container Docker com volume:

**Railway / Render / Fly.io**

1. Aponte o serviço para este repositório (o `Dockerfile` está na raiz).
2. Monte um volume persistente em `/data`.
3. Configure as variáveis de ambiente do `.env.example`.
4. Publique. O HTTPS já vem pronto nesses provedores.

**VPS com Docker**

```bash
git clone <este-repositório> decifra-pro && cd decifra-pro
cp .env.example .env && nano .env
docker compose up -d --build
```

Coloque um proxy reverso na frente para o HTTPS (Caddy resolve certificado
sozinho):

```caddyfile
decifra.seudominio.com.br {
    reverse_proxy localhost:8000
    request_body {
        max_size 600MB
    }
}
```

Com Nginx, lembre de `client_max_body_size` maior que o `MAX_ZIP_MB` e de
`proxy_read_timeout` folgado para os jobs longos.

Aponte o domínio (registro A) para o IP do servidor antes de subir o proxy.

Em URL pública, use `APP_ACCESS_PASSWORD` para não deixar o app aberto.

---

## Apagar um atendimento

Na tela da conversa, **Apagar atendimento**. Isso remove de verdade o ZIP, as
mídias extraídas, as conversões, os frames e os resultados — do disco e do banco.

Independente disso, tudo é apagado automaticamente depois de
`JOB_RETENTION_HOURS` (padrão: 24 horas).

---

## Limites

Padrões, todos configuráveis no `.env`:

| Limite | Padrão |
| --- | --- |
| Tamanho do ZIP | 500 MB |
| Conteúdo descompactado | 2000 MB |
| Arquivos por ZIP | 5000 |
| Arquivo isolado | 500 MB |
| Páginas por PDF | 300 |
| Quadros por vídeo | 16 |
| Pedaço de áudio | 20 MB / 10 min |
| Retenção | 24 h |
| Teto de custo por atendimento | US$ 5 |

---

## Testes

```bash
cd backend && .venv/bin/pytest          # motor, processadores, API, pipeline
cd backend && .venv/bin/ruff check app  # lint
cd frontend && npm test                 # upload em partes, telas, PWA, tema
cd frontend && npm run lint             # typecheck
cd frontend && npm run build            # build de produção
```

As fixtures sintéticas ficam em `tests-fixtures/synthetic/` (mídia gerada
artificialmente, sem nenhum dado pessoal). Para gerar um ZIP de teste:

```bash
python3 tests-fixtures/synthetic/gerar_zip.py /tmp/conversa-teste.zip
```

---

## Solução de problemas

**“Não encontrei o arquivo de texto da conversa dentro do ZIP.”**
O ZIP não é uma exportação do WhatsApp, ou foi remontado sem o `.txt`. Refaça a
exportação pelo aplicativo.

**“Esta exportação foi feita sem mídia.”**
A exportação foi feita sem marcar *Incluir mídia*: o TXT tem marcadores de mídia
oculta e não há arquivos para ler. Refaça a exportação.

**Áudio ou vídeo falhando com erro de conversão**
FFmpeg ausente. Confira com `ffmpeg -version` e `ffprobe -version`. Na imagem
Docker os dois já vêm instalados; fora dela, instale pelo gerenciador de pacotes.

**Links de páginas que dependem de JavaScript voltam vazios**
Ligue o fallback de navegador: `ENABLE_PLAYWRIGHT=true` e construa a imagem com
`--build-arg INSTALL_PLAYWRIGHT=true` (a imagem fica bem maior). Fora do Docker:
`pip install playwright && playwright install chromium`.

**Link bloqueado com “endereço de rede interna bloqueado”**
Proteção contra SSRF: o leitor só acessa endereços públicos. Não é erro.

**Upload interrompido / parte faltando**
Reenvie o arquivo. As partes já recebidas são substituídas e o servidor confere
tamanho e checksum antes de aceitar o ZIP.

**O job ficou “processando” depois de o servidor reiniciar**
Ele é retomado sozinho no próximo boot. Se o volume `/data` não for persistente,
os atendimentos anteriores se perdem — monte o volume.

**Sem espaço em disco**
Cada atendimento guarda o ZIP e o conteúdo extraído. Apague atendimentos antigos
ou reduza `JOB_RETENTION_HOURS`.

---

## Privacidade

- As conversas são de quem enviou. Só ficam no servidor onde você publicou.
- Os arquivos são apagados de verdade quando você apaga o atendimento, e
  automaticamente depois da retenção configurada.
- Os logs **não** registram conteúdo de mensagem, transcrição nem chave de API.
- Mídias só são enviadas ao provedor de IA que você configurou, e apenas o
  necessário para o processamento escolhido.
- A chave de API existe apenas no servidor: ela nunca vai para o navegador.
- O service worker cacheia só o app shell — nada de ZIP, transcrição, PDF ou
  resposta de API com dados pessoais.
- Sem analytics de terceiros.

A identidade visual está em [`MARCA.md`](MARCA.md); a arquitetura, em
[`ARCHITECTURE.md`](ARCHITECTURE.md).
