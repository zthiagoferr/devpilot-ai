# DevPilot AI — frontend

SPA em Angular 21 (standalone, zoneless, signals) + TailwindCSS 4, com tema escuro
preto/azul elétrico. Consome a API FastAPI do repositório.

## Requisitos

- Node.js 20.19+, 22.12+ ou 24+ (verificado com Node 26)
- API local em `http://localhost:8000`

## Desenvolvimento

```bash
npm ci
npm start          # http://localhost:4200
```

A API precisa liberar a origem do dev server em `FRONTEND_ORIGINS`
(`http://localhost:4200`).

## Configuração de runtime

`public/config.js` é carregado antes do bundle e define `window.DevPilotConfig`.
Em loopback, sem configuração, o cliente usa `http://localhost:8000`.

```bash
npm run config -- --api-base-url=https://api.example.com --base-path=/devpilot
```

Em produção sem `apiBaseUrl`, a UI degrada de forma explícita (`apiUnavailable`)
em vez de chamar a própria origem estática.

## Autenticação e histórico

O login usa o Firebase Authentication (SDK npm importado dinamicamente, em
chunk próprio). A configuração web pública vive em
`src/app/core/auth/firebase-config.ts` e pode ser sobrescrita em runtime:

```js
window.DevPilotConfig = {
  apiBaseUrl: 'https://api.example.com',
  firebase: { apiKey: '...', projectId: '...' },
};
```

Sem `apiKey`/`projectId` a autenticação degrada com uma mensagem explícita e os
fluxos de visitante (análise manual, repositório, detalhe público) continuam
funcionando. `GET /analyses` (histórico) é autenticado: visitantes veem o convite
para entrar e a requisição não é feita. O token é obtido em memória via
`user.getIdToken()` imediatamente antes de cada chamada (`AUTH_TOKEN_PROVIDER`).

## Scripts

| Comando              | Descrição                     |
| -------------------- | ----------------------------- |
| `npm start`          | Dev server em `:4200`         |
| `npm run build:prod` | Build de produção em `dist/`  |
| `npm run test:ci`    | Testes Vitest, execução única |
| `npm run config`     | Gera `public/config.js`       |

## Estrutura

```
src/app/
├── core/          # config de runtime, ApiClient, erros, auth, histórico, repositórios
├── shared/        # design system (button, field, card, modal, tabs, ...)
└── features/      # shell, overview, analysis, auth, history
```

Rotas usam `withHashLocation()` para funcionar em hospedagem estática. Links
antigos do painel (`#new-analysis`, `#analysis-detail`) são redirecionados.

A aba **Repositório GitHub** carrega apenas arquivos Python elegíveis via
`POST /repositories/load`, mostra o tamanho de cada arquivo e envia o caminho
(`file_path`), a URL e a branch junto com o código selecionado.

## Acessibilidade

Foco visível (outline `#60A5FA` + glow), alvos de 44px, skip link, drawer com
`inert`, live regions nos estados e `prefers-reduced-motion` respeitado.
`#2563EB` é usado apenas como preenchimento; texto e foco usam `#60A5FA`.
