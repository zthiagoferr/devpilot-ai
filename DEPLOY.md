# Deploy da primeira versão pública (Render + Neon)

Guia objetivo para publicar o backend FastAPI do DevPilot AI com um banco
PostgreSQL gerenciado (Neon) e o frontend estático no GitHub Pages. Ele **não
cria recursos automaticamente**: cada passo é executado por você no painel do
provedor.

## Escopo e limites desta versão

- **Sem LLM paga.** A análise AST (`POST /analyses`) e o load de repositórios
  (`POST /repositories/load`) funcionam sem `LLM_API_KEY`. Sem chave, os
  *insights* ficam indisponíveis, mas o resultado real (`score`, `summary`,
  `issues`) continua sendo gerado.
- **Rate limit em memória.** O limite é por processo (`1 worker`). Escalar
  horizontalmente exige um store externo (Redis, etc.), que está **fora de
  escopo**.
- **Sem provisionamento automático** e sem credenciais no repositório.

## 1. Neon (PostgreSQL gratuito)

1. Crie uma conta/projeto e um banco no [Neon](https://neon.tech).
2. Copie a **connection string direta** (host sem `-pooler`). Use a direta para
   migrações; o PgBouncer do pooler não é necessário nesta versão.
3. A string costuma vir assim (exemplo, com placeholders):

   ```text
   postgresql://<user>:<password>@ep-<id>.<region>.aws.neon.tech/<db>?sslmode=require&channel_binding=require
   ```

   O app traduz isso automaticamente: `postgresql://` vira
   `postgresql+asyncpg://`, o `sslmode=require` é convertido para o argumento
   `ssl` do asyncpg e `channel_binding` é descartado (o asyncpg negocia sozinho).
   Você pode colar a string **como estiver**.
4. Guarde a string apenas como variável de ambiente no Render. **Nunca** faça
   commit dela.

## 2. Render (Web Service, Docker)

1. No Render, escolha **New → Web Service** e aponte para o repositório.
2. Environment/Runtime: **Docker** (usa o `Dockerfile` do repositório).
3. Instância: comece com **1 instância** (o rate limit é em memória).
4. **Start Command** (sobrescreve o `CMD` do Dockerfile):

   ```sh
   alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```

   `alembic upgrade head` é idempotente e aplica o schema antes de subir a API.

5. **Health Check Path**: `/health` (liveness; não toca o banco).
6. **Persistência**: não é necessária — os dados ficam no Neon e o serviço é
   stateless. Não configure disco/volume.
7. **Variáveis de ambiente**:

   | Variável | Valor | Observação |
   | --- | --- | --- |
   | `DATABASE_URL` | connection string direta do Neon | colada como está |
   | `ENVIRONMENT` | `production` | exige PostgreSQL |
   | `FRONTEND_ORIGINS` | `https://zthiagoferr.github.io` | origens exatas, sem `*` |
   | `GITHUB_TOKEN` | *(opcional)* | aumenta limites da API do GitHub |
   | `RATE_LIMIT_REQUESTS` | `10` | por IP / janela |
   | `RATE_LIMIT_WINDOW_SECONDS` | `60` | janela do rate limit |
   | `TRUST_PROXY_HEADERS` | `true` | **apenas** se o app não for exposto diretamente (ver nota) |
   | `GITHUB_LOAD_TOTAL_SECONDS` | `60` | orçamento por load de repositório |
   | `LOG_LEVEL` | `INFO` | opcional |

   > `TRUST_PROXY_HEADERS=true` **somente** se a condição abaixo for
   > verificável: o app **não** é exposto diretamente à internet e é alcançável
   > **apenas** pelo proxy do provedor (Render/Cloudflare), que **anexa** o IP
   > observado ao `X-Forwarded-For`. Nesse caso o app usa o **último** item do
   > header (o hop anexado pelo proxy confiável), e os itens anteriores — que o
   > cliente pode forjar — são ignorados.
   >
   > Se existir **qualquer** rota direta ao app (porta pública, IP do container,
   > túnel etc.), mantenha `false` (default), pois sem um proxy na frente o
   > atacante forja livremente o último item e contorna o rate limit. Esse é o
   > trade-off: `true` só é seguro quando o proxy é inevitável e confiável.

8. Após o deploy, anote a URL pública (ex.: `https://devpilot-ai.onrender.com`).

## 3. GitHub Actions (frontend no Pages)

1. Em **Settings → Secrets and variables → Actions → Variables**, defina a
   *repository variable*:

   ```text
   DEVPILOT_API_URL = https://<seu-servico>.onrender.com
   ```

2. Reexecute o workflow existente **sem editá-lo**: **Actions → "Deploy DevPilot
   AI frontend to GitHub Pages" → Run workflow**
   (`workflow_dispatch`). Isso regenera o `site/config.js` com a URL da API.

## 4. Checklist de validação pública

Substitua `$API` pela URL do Render e `$FRONTEND` por
`https://zthiagoferr.github.io`.

- **Liveness**

  ```sh
  curl -s -o /dev/null -w "%{http_code}\n" "$API/health"   # 200
  ```

- **Readiness (banco real)**

  ```sh
  curl -s -w "\n%{http_code}\n" "$API/ready"               # 200 {"status":"ready",...}
  # Se o Neon estiver fora do ar: 503, sem vazar credenciais.
  ```

- **Preflight CORS (origem permitida)**

  ```sh
  curl -s -i -X OPTIONS "$API/analyses" \
    -H "Origin: $FRONTEND" \
    -H "Access-Control-Request-Method: POST" \
    -H "Access-Control-Request-Headers: content-type" \
    | grep -i "access-control-allow-origin"                 # = $FRONTEND
  ```

  Origem de terceiro (ex.: `https://evil.example`) **não** deve retornar
  `access-control-allow-origin`, e nunca `*`. Credenciais cross-origin estão
  desabilitadas.

- **Análise real (AST, sem LLM)**

  ```sh
  curl -s -X POST "$API/analyses" -H "Content-Type: application/json" \
    -d '{"task":"code_analysis","project_name":"demo","source_code":"def total(items):\n    return sum(items)\n"}'
  # 201 com result.score/summary/issues; sem texto de insights fabricado.
  ```

- **Load de repositório**

  ```sh
  curl -s -X POST "$API/repositories/load" -H "Content-Type: application/json" \
    -d '{"repository_url":"octocat/Hello-World"}'
  # 200 com "files": [...] (pode ser vazio com "message" se não houver .py).
  ```

- **Caminhos de erro**
  - `repository_url` inválido → `422`
  - repositório inexistente/privado → `404`
  - `source_code` acima de `MAX_SOURCE_CODE_BYTES` → `413`

- **Rate limit**
  - Repita `POST /analyses` acima de `RATE_LIMIT_REQUESTS` na janela →
    `429` com header `Retry-After`.

- **Frontend no ar e sem segredos**
  - No site publicado, execute uma análise real e um load de repositório.
  - Confirme que `site/config.js` contém apenas `apiBaseUrl`/`basePath`.
  - Busque segredos no artefato publicado (deve retornar vazio):

    ```sh
    grep -RIl -e "DATABASE_URL" -e "GITHUB_TOKEN" -e "LLM_API_KEY" site/
    ```

## 5. Notas finais

- Sem `LLM_API_KEY`, os *insights* ficam indisponíveis; a análise AST (código,
  testes, docs, relatório) permanece funcional.
- O rate limit é por processo/single worker. Rodar múltiplos workers/instâncias
  exige um store compartilhado — fora do escopo deste primeiro deploy.
- O TLS do Neon é negociado via `sslmode=require` traduzido para asyncpg tanto
  na aplicação quanto no Alembic.
