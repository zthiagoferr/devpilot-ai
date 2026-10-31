# Deploy (Vercel + GitHub Pages + Neon + Firebase)

Guia objetivo da infraestrutura **vigente**: API FastAPI na **Vercel**, SPA
Angular no **GitHub Pages**, PostgreSQL gerenciado no **Neon** e autenticação
opcional no **Firebase**. Ele **não cria recursos automaticamente**: cada passo
é executado por você no painel do provedor.

> **Histórico.** O guia original deste projeto descrevia o Render como backend.
> Esse conteúdo foi movido para o [Apêndice A](#apêndice-a-render-histórico--não-usar)
> apenas como registro. **Não use o Apêndice A para novas publicações**; ele
> cita um start command com `alembic upgrade head`, prática proibida na Vercel.

## 0. Arquitetura e ordem de publicação

| Camada | Onde roda | Como publica |
| --- | --- | --- |
| API FastAPI | Vercel (Python) | integração Git da Vercel |
| Banco PostgreSQL | Neon | manual (projeto criado no painel) |
| SPA Angular | GitHub Pages | workflow `.github/workflows/pages.yml` |
| Autenticação (opcional) | Firebase Auth | Console do Firebase |

**Publique o backend primeiro.** A SPA precisa da URL pública da API para gerar
o `config.js`; se o Pages publicar antes, o site fica sem backend e o job
`build` falha de propósito na validação de `DEVPILOT_API_URL`.

Ordem recomendada:

1. Criar o projeto/banco no **Neon** (seção 1).
2. Fazer **backup/snapshot** do banco antes de qualquer migração.
3. Aplicar as migrações **manualmente** (seção 2).
4. Publicar a API na **Vercel** e configurar as variáveis (seção 3).
5. Validar `GET /health` e `GET /ready` na URL pública.
6. Definir a repository variable `DEVPILOT_API_URL` no GitHub (seção 4.1).
7. Publicar o frontend no Pages por push em `main` ou `workflow_dispatch` em
   `main` (seção 4.4).
8. Executar o checklist de validação pública (seção 6).

### Escopo e limites desta versão

- **Sem LLM paga.** A análise AST (`POST /analyses`) e o load de repositórios
  (`POST /repositories/load`) funcionam sem `LLM_API_KEY`. Sem chave, os
  *insights* ficam indisponíveis, mas o resultado real (`score`, `summary`,
  `issues`) continua sendo gerado.
- **Autenticação opcional.** Sem `FIREBASE_PROJECT_ID`/
  `FIREBASE_SERVICE_ACCOUNT_JSON` o backend sobe normalmente e o
  comportamento degradado é: `POST /analyses` continua público (análise
  anônima) e `GET /analyses` / `GET /analyses/{id}` respondem `401`. O
  histórico por usuário exige o Firebase configurado (seção 5).
- **Rate limit em memória.** O limite é por processo. Em ambiente serverless
  cada instância tem seu próprio contador; escalar horizontalmente com limite
  consistente exige um store externo (Redis, etc.), que está **fora de
  escopo**.
- **Migrações são manuais.** Nenhum build/start da Vercel executa Alembic.
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
4. Guarde a string apenas como variável de ambiente na Vercel. **Nunca** faça
   commit dela.
5. Para migrações, use a string **direta** (sem `-pooler`). O pooler pode
   rejeitar operações de DDL em sessões curtas.

## 2. Migrações manuais controladas

As migrações Alembic (`alembic/versions/0001`–`0003`) são **aplicadas por você**,
uma única vez, de uma máquina confiável. Elas não rodam no build nem no start da
Vercel e não rodam pelo GitHub Actions.

1. Configure o ambiente do comando:

   ```bash
   export ENVIRONMENT=production
   export DATABASE_URL='postgresql://<user>:<password>@<host-direto-sem-pooler>/<db>?sslmode=require'
   ```

   - `ENVIRONMENT=production` é **obrigatório** e ativa as guardas da aplicação
     e do Alembic: em produção, ambos recusam qualquer URL que não seja
     PostgreSQL, com a mensagem fixa
     `DATABASE_URL must be configured with a PostgreSQL URL in production.`
     A mensagem não contém URL, driver, host, usuário nem senha.
   - Use a URL **direta** do Neon (sem `-pooler`).
   - Nunca use `compose.yaml`/Docker para migrar produção: o Compose é apenas
     para execução local.

2. Faça backup/snapshot do banco (o Neon permite criar branches/restauração).

3. Aplique as migrações com **um comando único e a URL explícita**:

   ```bash
   ENVIRONMENT=production \
   DATABASE_URL='postgresql://<user>:<password>@<host-direto-sem-pooler>/<db>?sslmode=require' \
   .venv/bin/alembic upgrade head
   ```

   As revisões **0001–0003 não foram alteradas** nesta etapa:

   - **0001** cria o schema base de `analyses`;
   - **0002** adiciona `analyses.user_id` (sem backfill: linhas antigas ficam
     com `user_id NULL` e não aparecem em nenhum histórico);
   - **0003** cria a tabela aditiva `analysis_corrections`, sem alterar tabelas
     existentes.

4. Confira o estado:

   ```bash
   ENVIRONMENT=production DATABASE_URL='...' .venv/bin/alembic current
   ```

Se a guarda falhar, a URL está vazia, com espaços, inválida ou não é
PostgreSQL — corrija a variável e repita. Nenhum arquivo SQLite é criado.

## 3. Backend na Vercel

1. No painel da Vercel, **Add New → Project** e importe o repositório do
   GitHub.
2. Framework preset: **FastAPI** (runtime Python). O entrypoint da aplicação é
   `app/main.py`; se o preset não o encontrar automaticamente, aponte o
   entrypoint no dashboard do projeto. **Nenhum `vercel.json` é versionado
   nesta etapa** — a configuração fica no projeto da Vercel.
3. **Git integration**: cada push na *production branch* gera um novo
   deployment. Um CI vermelho no GitHub **não bloqueia** a Vercel, porque são
   pipelines independentes. A proteção é externa:
   - *Production branch* = `main` (Settings → Git);
   - habilitar **Deployment Protection** para previews, se disponível no plano;
   - **não** configurar `alembic upgrade head` no *Build Command* nem no
     *Start Command*;
   - revisar o deployment antes de promover, quando o plano permitir.
4. **Variáveis de ambiente** (Settings → Environment Variables):

   | Variável | Valor | Observação |
   | --- | --- | --- |
   | `ENVIRONMENT` | `production` | **obrigatória**: ativa as guardas de PostgreSQL no app e no Alembic |
   | `DATABASE_URL` | connection string do Neon | colada como está; use a direta para migrações |
   | `FRONTEND_ORIGINS` | `https://zthiagoferr.github.io` | origens exatas, sem caminho e sem `*` |
   | `GITHUB_TOKEN` | *(opcional)* | aumenta limites da API do GitHub |
   | `RATE_LIMIT_REQUESTS` | `10` | por IP / janela, por instância |
   | `RATE_LIMIT_WINDOW_SECONDS` | `60` | janela do rate limit |
   | `TRUST_PROXY_HEADERS` | `true` | **apenas** se o app não for exposto diretamente (ver nota) |
   | `GITHUB_LOAD_TOTAL_SECONDS` | `60` | orçamento por load de repositório |
   | `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY` | *(opcional)* | correção com IA; sem chave os insights ficam indisponíveis |
   | `LLM_TIMEOUT_SECONDS` | `90` | deve ficar abaixo do limite de execução da função |
   | `FIREBASE_PROJECT_ID` | *(opcional)* id do projeto Firebase | ex.: `devpilot-ai-1a2b3` |
   | `FIREBASE_SERVICE_ACCOUNT_JSON` | *(opcional)* **segredo** | JSON da service account em uma linha |
   | `LOG_LEVEL` | `INFO` | opcional |

   > `ENVIRONMENT=production` com `DATABASE_URL` ausente, vazia ou SQLite faz a
   > aplicação falhar de forma explícita. Isso é intencional: um deploy sem
   > PostgreSQL não deve subir "meio funcionando" em produção.

   > `TRUST_PROXY_HEADERS=true` **somente** se a condição abaixo for
   > verificável: o app **não** é exposto diretamente à internet e é alcançável
   > **apenas** pelo proxy da plataforma (Vercel/Cloudflare), que **anexa** o IP
   > observado ao `X-Forwarded-For`. Nesse caso o app usa o **último** item do
   > header (o hop anexado pelo proxy confiável), e os itens anteriores — que o
   > cliente pode forjar — são ignorados.
   >
   > Se existir **qualquer** rota direta ao app (porta pública, IP do container,
   > túnel etc.), mantenha `false` (default), pois sem um proxy na frente o
   > atacante forja livremente o último item e contorna o rate limit. Esse é o
   > trade-off: `true` só é seguro quando o proxy é inevitável e confiável.

5. Após o deploy, anote a URL pública (ex.: `https://devpilot-ai.vercel.app`).
   Valide `/health` e `/ready` antes de seguir para o frontend.

## 4. Frontend Angular (GitHub Pages)

O frontend publicado no Pages é a SPA Angular de `frontend/` (Angular 21 +
Tailwind 4), construída e validada pelo workflow
`.github/workflows/pages.yml`.

### 4.1. Variável da API

Em **Settings → Secrets and variables → Actions → Variables**, defina a
*repository variable*:

```text
DEVPILOT_API_URL = https://<seu-projeto>.vercel.app
```

Ela é pública (aparece no `config.js` enviado ao navegador). O `config.js` é
gerado no runner por `frontend/scripts/write-config.mjs` e contém apenas
`apiBaseUrl` e `basePath`; nenhum segredo do backend entra no artefato.

A variável é **obrigatória**: o job `build` falha antes de publicar se ela
estiver vazia ou contiver apenas espaços. O workflow emite o erro
`DEVPILOT_API_URL ausente` com a instrução de configuração.

### 4.2. Gate de publicação

O workflow tem três jobs encadeados:

1. **`verify`** — pytest, `compileall`, testes do Angular, `tsc --noEmit`
   (app e spec) e build de produção.
2. **`build`** — preflight de `DEVPILOT_API_URL`, geração do `config.js`,
   build com `--base-href`, validação do artefato, smoke test em subpath e
   upload do artefato com `actions/upload-pages-artifact`.
3. **`deploy`** — publica o artefato com `actions/deploy-pages`, somente em
   `refs/heads/main`.

Se `verify` ou `build` falhar, nada é publicado. O antigo gatilho
`preview-pages` foi removido: o Pages não publica previews.

### 4.3. Build e configuração local

```bash
cd frontend
npm ci
npm run build:prod        # gera frontend/dist/

# desenvolvimento com a API local em http://localhost:8000
npm start                 # ng serve em http://localhost:4200
```

Para apontar build/dev server para outra API, gere o runtime config antes:

```bash
npm run config -- --api-base-url=https://api.example.com --base-path=/devpilot-ai
npm run build:prod
```

O `public/config.js` é copiado para o artefato e carregado **antes** do bundle.
O workflow usa o `base_path` do `actions/configure-pages` no `--base-href` e no
`basePath` do runtime config (ex.: `/devpilot-ai`), monta o artefato em
`$RUNNER_TEMP/site` (nunca no `site/` do checkout) e testa o site servido em
subpath. A validação falha se faltar `index.html`, `config.js`, bundle CSS/JS,
se houver asset com URL absoluta ou se `config.js` não vier antes do bundle.

### 4.4. Publicação

- **Push em `main`**: executa `verify → build → deploy` automaticamente.
- **Actions → "Deploy DevPilot AI frontend to GitHub Pages" → Run workflow**
  (`workflow_dispatch`): em `main`, publica; em qualquer outra ref, apenas roda
  `verify`/`build` e **não** publica (o job `deploy` exige
  `github.ref == 'refs/heads/main'`).

O job `build` continua publicando o artefato com `actions/upload-pages-artifact`;
o `deploy` apenas o consome com `actions/deploy-pages`.

O dashboard legado em `web/` continua sendo servido pelo backend em
`/dashboard` como fallback até o cutover (F7); o Pages publica apenas a SPA
Angular.

## 5. Firebase Authentication (opcional)

Habilita histórico por usuário. **É opcional**: sem esta seção o backend
funciona sem autenticação (ver "Escopo e limites").

### 5.1. Projeto Firebase

1. Crie um projeto no [Firebase Console](https://console.firebase.google.com)
   (o plano **Spark/gratuito** é suficiente).
2. **Authentication → Sign-in method**: habilite **E-mail/senha**. Para o
   botão "Continuar com GitHub", habilite também **GitHub**.
3. **Authentication → Settings → Authorized domains**: adicione
   `zthiagoferr.github.io` e `localhost` (o domínio padrão
   `<projeto>.firebaseapp.com` já vem autorizado).
4. **OAuth do GitHub** (se usar GitHub): crie um OAuth App no GitHub com
   **Authorization callback URL**
   `https://<projeto>.firebaseapp.com/__/auth/handler` e cole *Client ID* e
   *Client secret* no provedor GitHub do Firebase.

### 5.2. Backend (Vercel)

| Variável | Valor | Observação |
| --- | --- | --- |
| `FIREBASE_PROJECT_ID` | id do projeto (ex.: `devpilot-ai-1a2b3`) | não é segredo |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | JSON da service account, **em uma linha** | **segredo** |

Como obter a service account: **Project settings → Service accounts → Generate
new private key**. Cole o conteúdo do arquivo JSON inteiro (uma linha) apenas
como variável de ambiente na Vercel — **nunca** no repositório.

O backend importa o `firebase-admin` de forma *lazy*: sem essas variáveis o
processo sobe normalmente, `/health` responde `200` e as rotas autenticadas
respondem `401` (fail-closed).

### 5.3. Frontend (config pública)

A configuração web pública padrão fica em
`frontend/src/app/core/auth/firebase-config.ts` (`FIREBASE_CONFIG`), não mais em
`web/dashboard.js` (painel legado). Preencha com os valores de **Project
settings → Your apps → Web app** (`apiKey`, `authDomain`, `projectId`,
`appId`). Esses valores são **públicos por natureza** (vão para o navegador); a
*API key* do Firebase Web não é um segredo. A *service account* do backend,
sim.

Em runtime, `window.DevPilotConfig.firebase` pode sobrepor ou complementar
esses valores sem rebuild. Inclua o objeto no `config.js` do artefato (o
arquivo gerado por `frontend/scripts/write-config.mjs` pode ser complementado
no deploy):

```js
window.DevPilotConfig = {
  apiBaseUrl: 'https://api.example.com',
  basePath: '/devpilot-ai',
  firebase: { apiKey: '...', projectId: '...' },
};
```

Mantenha os valores padrão versionados em `firebase-config.ts`; o override é
útil para variar o projeto Firebase por ambiente.

Enquanto `apiKey`/`projectId` estiverem vazios, a SPA degrada com elegância: as
análises (código colado e repositório) continuam funcionando para visitantes e a
área de conta explica que o acesso não está configurado. O SDK só é importado
quando houver configuração.

### 5.4. Ordem de deploy

1. Banco (Neon) e API (Vercel) conforme as seções 1–3. As migrações são
   aplicadas manualmente (seção 2) e cobrem **0001**, **0002** (adiciona
   `analyses.user_id`) e **0003** (tabela aditiva `analysis_corrections`).
2. Variáveis do Firebase na Vercel (5.2) e novo deployment.
3. Configuração pública do Firebase no frontend (5.3) + publicação do Pages
   (seção 4).
4. Domínios autorizados e provedores (5.1) antes de divulgar o link.

### 5.5. Checklist de autenticação

```sh
# Sem token: histórico protegido (401)
curl -s -o /dev/null -w "%{http_code}\n" "$API/analyses"        # 401

# Análise anônima continua pública (201) e o corpo NÃO expõe user_id
curl -s -X POST "$API/analyses" -H "Content-Type: application/json" \
  -d '{"task":"code_analysis","project_name":"anon","source_code":"def f():\n    return 1\n"}'
# 201 sem "user_id" na resposta

# Preflight precisa liberar o header Authorization
curl -s -i -X OPTIONS "$API/analyses" \
  -H "Origin: $FRONTEND" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: authorization,content-type" \
  | grep -i "access-control-allow-headers"    # deve conter authorization
```

No site publicado: entrar com e-mail/senha, executar uma análise, confirmar que
ela aparece no histórico **daquela conta** e que, após sair (ou em outra conta),
o mesmo ID responde `404`.

### 5.6. Provedores de login (Firebase Console)

Nenhuma credencial é versionada neste repositório: os passos abaixo são
executados por você no Console/provedores externos. O código já implementa os
seis métodos.

| Método | O que fazer no Console | Observação |
| --- | --- | --- |
| E-mail/senha | Authentication → Sign-in method → **Email/Password** → Enable | usado no cadastro, login, redefinição e confirmação |
| Anônimo | Authentication → Sign-in method → **Anonymous** → Enable | só é ativado pela ação explícita "Continuar como visitante"; nunca no boot |
| GitHub | OAuth App no GitHub → Client ID/secret no Console | callback abaixo |
| Google | Authentication → Sign-in method → **Google** → Enable | não exige app OAuth próprio; o Firebase usa o client gerenciado |
| Apple | Authentication → Sign-in method → **Apple** | exige Apple Developer Program pago |
| Microsoft | Authentication → Sign-in method → **Microsoft** | exige app registration no Entra ID |

1. **GitHub**: crie um OAuth App em GitHub → Settings → Developer settings →
   OAuth Apps. Em **Authorization callback URL** use exatamente
   `https://devpilot-ai-e78f0.firebaseapp.com/__/auth/handler`; copie *Client
   ID* e *Client secret* para o provedor GitHub do Firebase.
2. **Google**: habilitar no Console é suficiente; não é necessário criar um
   client OAuth no Google Cloud para este fluxo.
3. **Apple** (pago): no Apple Developer, crie um **Services ID** e configure a
   **Return URL** `https://devpilot-ai-e78f0.firebaseapp.com/__/auth/handler`;
   crie uma **Key** (`.p8`) e anote o **Key ID** e o **Team ID**. No Console,
   habilite Apple e preencha Services ID, Team ID, Key ID e a chave privada.
4. **Microsoft**: no Entra ID → App registrations, crie o app, adicione a
   **Redirect URI** do tipo **Web**
   `https://devpilot-ai-e78f0.firebaseapp.com/__/auth/handler`, use o tenant
   `common` e gere um **client secret**. No Console, cole o *Application
   (client) ID* e o secret.
5. **Domínios autorizados**: em Authentication → Settings → **Authorized
   domains**, adicione `localhost`, `127.0.0.1` e `zthiagoferr.github.io`. O
   domínio padrão `<projeto>.firebaseapp.com` já vem autorizado. Sem isso, o
   popup/redirect falha com `auth/unauthorized-domain`, e os links de ação
   (confirmação/redefinição) com `auth/unauthorized-continue-uri`.

### 5.7. Política de e-mail verificado

O backend **não exige** `email_verified=true` (`app/core/auth.py`,
`VerifiedUser.email_verified` é apenas informativo). Por design:

- análise anônima e de conta não verificada continua permitida;
- leitura do histórico exige token, e o resultado é sempre limitado ao `uid` do
  token — uma conta não verificada enxerga apenas as próprias análises;
- o banner "Confirme seu e-mail" e o botão "Já confirmei" na SPA são
  informativos: não bloqueiam análise nem histórico.

### 5.8. Allow-list de provedores no runtime do Pages

`window.DevPilotConfig.firebase.providers` limita quais botões aparecem, sem
rebuild. Ausente ou vazio = todos os provedores; a lista só filtra a UI (o
Console continua sendo a fonte de verdade sobre o que está habilitado):

```js
window.DevPilotConfig = {
  apiBaseUrl: 'https://api.example.com',
  basePath: '/devpilot-ai',
  firebase: {
    apiKey: '...',
    projectId: '...',
    providers: ['github', 'google', 'apple', 'microsoft'],
  },
};
```

## 6. Checklist de validação pública

Substitua `$API` pela URL da Vercel e `$FRONTEND` por
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
  # A resposta nunca inclui user_id (nem para análises autenticadas).
  ```

- **Histórico protegido**

  ```sh
  curl -s -o /dev/null -w "%{http_code}\n" "$API/analyses"   # 401 sem token
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

- **Frontend Angular no ar e sem segredos**
  - No site publicado, execute uma análise real e um load de repositório.
  - Confirme que o `config.js` do artefato contém apenas
    `apiBaseUrl`/`basePath`.
  - Busque segredos no artefato publicado (deve retornar vazio). Localmente,
    use o build em `frontend/dist/`; no runner, o diretório é
    `$RUNNER_TEMP/site`:

    ```sh
    grep -RIl -e "DATABASE_URL" -e "GITHUB_TOKEN" -e "LLM_API_KEY" \
      -e "FIREBASE_SERVICE_ACCOUNT_JSON" -e "private_key" frontend/dist/
    ```

## 7. Rollback

- **Frontend (GitHub Pages):** reexecute o último deployment bom em
  **Actions → Deploy DevPilot AI frontend to GitHub Pages → Re-run jobs** ou
  reverta o commit que quebrou o build em `main`. Como o `deploy` só roda
  depois de `verify`/`build`, um build ruim não chega ao ar.
- **Backend (Vercel):** use **Instant Rollback** no deployment anterior em
  Deployments → ⋯ → Instant Rollback. Variáveis de ambiente não são revertidas;
  revise-as se a falha for de configuração.
- **Banco (Neon):** prefira restaurar um branch/snapshot do Neon. `alembic
  downgrade` só deve ser usado se realmente necessário e **com aviso
  destrutivo**:
  - `0003 → 0002` remove a tabela `analysis_corrections`;
  - `0002 → 0001` remove a coluna `analyses.user_id`.
  Faça backup antes e confirme o alvo com `alembic current`.

## 8. Troubleshooting

### 8.1. API responde 503 e o navegador mostra erro de CORS

Sintoma típico: o dashboard exibe "Falha de conexão/CORS com a API" ou
"Resposta inesperada da API", mas a aplicação não registra a requisição.

Quando a borda da plataforma devolve um erro antes da função, a resposta não
tem os headers CORS da aplicação e o browser apresenta a falha como CORS.
Confirme pela linha de comando:

```sh
curl -i "$API/agents/orchestrator"
```

Sinais de que a falha é da borda/plataforma:

- status `503` (ou `504`) sem corpo JSON;
- corpo HTML com página de aviso do provedor;
- headers de CORS ausentes na resposta de erro.

Passos de verificação:

1. Abra o painel da Vercel e confira o status do deployment e os logs da
   função (build, cold start, timeout, erro de importação).
2. Confirme que `ENVIRONMENT` e `DATABASE_URL` estão definidas corretamente no
   ambiente de produção; a guarda recusa PostgreSQL ausente/SQLite.
3. Verifique `FRONTEND_ORIGINS`: precisa ser a origem exata
   (`https://zthiagoferr.github.io`), sem caminho e sem barra final.
4. Se o provedor estiver com conta suspensa/limite excedido, regularize no
   painel. A regularização é uma decisão do proprietário da conta; não altere
   plano ou cobrança sem autorização.

> O frontend não consegue distinguir sozinho "API fora do ar" de "CORS mal
> configurado" quando a borda devolve HTML. Por isso o painel de status mostra
> "Resposta inesperada da API" para corpos não-JSON e "Falha de conexão/CORS"
> para falhas de rede.

> Para diagnósticos do backend antigo no Render (incluindo suspensão de serviço
> free), consulte o Apêndice A — apenas como referência histórica.

### 8.2. Correção com IA demora e retorna 504

O backend abandona uma correção após `LLM_TIMEOUT_SECONDS` (padrão `90`) e
responde `504` com uma mensagem específica. Arquivos médios/grandes podem levar
45-100 s no provedor; para reduzir o tempo, use um arquivo menor ou tente
novamente. `502` indica resposta inválida do provedor e `422` indica correção
rejeitada pelas verificações de segurança — nenhum desses casos executa o código
retornado.

Em ambiente serverless, mantenha `LLM_TIMEOUT_SECONDS` abaixo do tempo máximo
de execução da função configurado na Vercel. Caso contrário, a plataforma
encerra a invocação antes de a API devolver o `504`.

---

## Apêndice A. Render (histórico — NÃO USAR)

> **Aviso:** este apêndice preserva o guia antigo baseado em Render. Ele é
> mantido apenas como registro histórico e **não** descreve a infraestrutura
> vigente. Em particular, o start command com `alembic upgrade head` **não deve
> ser usado** na Vercel; migrações são manuais (seção 2).

### A.1. Web Service (Docker)

1. No Render, escolha **New → Web Service** e aponte para o repositório.
2. Environment/Runtime: **Docker** (usa o `Dockerfile` do repositório).
3. Instância: comece com **1 instância** (o rate limit é em memória).
4. **Start Command** histórico (sobrescreve o `CMD` do Dockerfile):

   ```sh
   alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```

   Registro: o `alembic upgrade head` era idempotente e aplicava o schema antes
   de subir a API. Esse padrão foi substituído por migração manual controlada;
   não o reproduza em produção.
5. **Health Check Path**: `/health` (liveness; não toca o banco).
6. **Persistência**: não era necessária — os dados ficam no Neon e o serviço é
   stateless. Não configure disco/volume.
7. **Variáveis de ambiente** (equivalentes às da Vercel, seção 3):

   | Variável | Valor | Observação |
   | --- | --- | --- |
   | `DATABASE_URL` | connection string direta do Neon | colada como está |
   | `ENVIRONMENT` | `production` | exige PostgreSQL |
   | `FRONTEND_ORIGINS` | `https://zthiagoferr.github.io` | origens exatas, sem `*` |
   | `GITHUB_TOKEN` | *(opcional)* | aumenta limites da API do GitHub |
   | `RATE_LIMIT_REQUESTS` | `10` | por IP / janela |
   | `RATE_LIMIT_WINDOW_SECONDS` | `60` | janela do rate limit |
   | `TRUST_PROXY_HEADERS` | `true` | **apenas** se o app não for exposto diretamente |
   | `GITHUB_LOAD_TOTAL_SECONDS` | `60` | orçamento por load de repositório |
   | `FIREBASE_PROJECT_ID` | *(opcional)* id do projeto Firebase | ex.: `devpilot-ai-1a2b3` |
   | `FIREBASE_SERVICE_ACCOUNT_JSON` | *(opcional)* **segredo** | JSON da service account em uma linha |
   | `LOG_LEVEL` | `INFO` | opcional |

8. A URL pública tinha o formato `https://<serviço>.onrender.com`.

### A.2. Diagnóstico de suspensão no Render

Um serviço Render **suspenso** responde na borda, antes de chegar ao container.
A resposta é um HTML `503` sem os headers CORS da aplicação, então o browser
apresenta a falha como CORS. Confirme pela linha de comando:

```sh
curl -i "$API/agents/orchestrator"
```

Sinais de suspensão:

- status `503`;
- header `x-render-routing: suspend`;
- corpo HTML (não JSON), frequentemente com uma página de aviso do Render.

Passos de verificação (sem alterar cobrança automaticamente):

1. Abra o dashboard do Render e confira o estado do Web Service (suspenso,
   pausado ou sem instância ativa).
2. Verifique o uso do workspace: horas de instância free, banda e build minutes
   podem suspender serviços free até o próximo ciclo.
3. Confira se há alerta de billing/faturamento no workspace. A regularização é
   uma decisão do proprietário da conta; não altere o plano ou a cobrança sem
   autorização.
4. Após regularizar, aguarde o redeploy/serviço voltar a `Live` e repita o
   `curl -i`; a resposta deve ser JSON `200`.

### A.3. Notas de TLS e proxy (válidas em qualquer provedor)

- Sem `LLM_API_KEY`, os *insights* ficam indisponíveis; a análise AST (código,
  testes, docs, relatório) permanece funcional.
- O rate limit é por processo. Rodar múltiplos workers/instâncias exige um
  store compartilhado — fora do escopo deste primeiro deploy.
- O TLS do Neon é negociado via `sslmode=require` traduzido para asyncpg tanto
  na aplicação quanto no Alembic.
- `TRUST_PROXY_HEADERS=true` só é seguro quando o proxy é inevitável e
  confiável (ver a nota completa na seção 3).
