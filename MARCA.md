# DECIFRA PRO — Identidade visual

## Nome
**Decifra Pro**

Repositório sugerido: `decifra-pro`
Configuração: `APP_NAME=Decifra Pro` no `.env`, consumido por backend e frontend.
O nome nunca deve ser escrito direto no código.

---

## Conceito do ícone

Uma onda sonora que se transforma em uma linha de texto.

Traduz a dor central do produto: a informação está presa dentro do áudio, do PDF,
do print — e o Decifra Pro a transforma em texto legível.

Não usa balão de conversa nem verde, para não remeter ao WhatsApp (marca da Meta).

---

## Paleta

| Papel | Cor | Hex |
| --- | --- | --- |
| Principal | Roxo-uva | `#6B4EE6` |
| Decifrado | Âmbar | `#FFC94D` |
| Texto principal (claro) | Quase preto arroxeado | `#1A1523` |
| Texto secundário (claro) | Cinza-lilás | `#77728A` |
| Fundo da página (claro) | Branco-lilás | `#FAF9FC` |
| Superfície de cartão (claro) | Branco | `#FFFFFF` |
| Borda (claro) | Lilás claro | `#E8E4F2` |
| Fundo da página (escuro) | Quase preto | `#0B0F14` |
| Superfície de cartão (escuro) | Grafite | `#10151C` |
| Borda (escuro) | Grafite claro | `#2A3240` |
| Roxo no escuro | Lilás | `#A78BFA` |

### Regra de cor do produto
- **Roxo** = conteúdo ainda não processado.
- **Âmbar** = conteúdo já decifrado.
- **Vermelho padrão do sistema** = falha.

Essa regra vale na timeline, nos badges e na barra de cobertura. Ela existe para que
o usuário entenda o estado de cada item sem ler nada.

No modo escuro, o âmbar perde legibilidade contra o roxo — nesse modo use o lilás
`#C8B6FF` para "decifrado" e reserve o âmbar apenas para avisos.

---

## Modo padrão

**Claro por padrão**, escuro como opção do usuário.

Motivo: a tela principal é um paredão de texto longo (transcrições, PDFs inteiros,
descrições). Leitura prolongada cansa menos em fundo claro.

O modo escuro é obrigatório como alternativa, não como padrão.

---

## Tipografia

Fonte de sistema, sem serifa. Dois pesos apenas: 400 regular e 500 para títulos e
rótulos. Nada acima de 500.

Sempre em caixa de frase — nunca Caixa Alta Em Cada Palavra, nunca CAIXA ALTA.

---

## Arquivos do ícone

| Arquivo | Uso |
| --- | --- |
| `icon.svg` | Fonte mestre, 512×512, cantos arredondados |
| `icon-maskable.svg` | Fonte do maskable, sem cantos, conteúdo a 78% |
| `icon-192.png` | PWA |
| `icon-512.png` | PWA |
| `maskable-512.png` | PWA maskable (Android) |
| `apple-touch-icon.png` | 180×180, iOS, sem transparência e sem cantos |
| `favicon.ico` | 16 / 32 / 48 |

Colocar tudo em `frontend/public/`.

O script `gerar.py` acompanha os arquivos: alterando as cores no topo dele e rodando
`python3 gerar.py`, todos os derivados são regerados de uma vez.

---

## O que evitar

- Verde em qualquer tom, e a palavra "Whats" ou "Zap" no nome, no ícone ou na interface.
- Reaproveitar o verde-limão do Corretor Pro. São produtos diferentes.
- Sombras, gradientes e brilhos. O visual é chapado.
- Emoji na marca. Na timeline os símbolos de tipo de mídia são permitidos, porque ali
  são funcionais.
