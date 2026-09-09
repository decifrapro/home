# Decifra Pro — regras do projeto

## Versão

Toda alteração publicada **sobe o número da versão em um**.

- Fonte única: `backend/app/versao.py` (`VERSAO = "007"`). Nenhum outro arquivo
  guarda cópia do número.
- Aparece ao lado da logo no cabeçalho e em `GET /api/config` (campo `versao`).
- É assim que se confere, olhando a tela, se o que está no ar já contém o
  último ajuste. Esquecer de subir o número torna essa conferência mentirosa.

## Antes de publicar

```bash
cd backend && .venv/bin/python -m pytest -q && .venv/bin/python -m ruff check app tests
cd frontend && npx tsc --noEmit && npm test -- --run && npm run build
```

## Princípios que valem mais que conveniência

- O conteúdo original nunca é alterado, resumido ou traduzido.
- Falha nunca é escondida: aparece na tela, com o motivo.
- 100% de cobertura só é exibido quando é 100% de verdade.
