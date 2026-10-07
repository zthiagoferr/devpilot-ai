# DevPilot AI

[![CI](https://github.com/devpilot-ai/devpilot-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/devpilot-ai/devpilot-ai/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)

[English](README.md) | **Português**

DevPilot AI é uma aplicação para análise automatizada de projetos de software. A API baseada em FastAPI utiliza agentes especializados para analisar código, testes e documentação, coordenando os resultados por meio de um orquestrador. O projeto também disponibiliza um dashboard web para iniciar e acompanhar análises.

> **Status do projeto:** a arquitetura V1–V7 está implementada e coberta pela suíte de testes. O projeto continua evoluindo por meio do roadmap documentado abaixo.

## Sumário

- [Visão geral](#visão-geral)
- [Dashboard](#dashboard)
- [Arquitetura V1–V7](#arquitetura-v1v7)
- [Fluxos de trabalho](#fluxos-de-trabalho)
- [Runtime de ferramentas e skills](#runtime-de-ferramentas-e-skills)
- [MCP v2](#mcp-v2)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Configuração](#configuração)
- [Execução local](#execução-local)
- [Docker e Compose](#docker-e-compose)
- [Health e readiness](#health-e-readiness)
- [Segurança](#segurança)
- [API](#api)
- [Persistência e Alembic](#persistência-e-alembic)
- [CI](#ci)
- [Testes](#testes)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Roadmap concluído](#roadmap-concluído)
- [Contribuição](#contribuição)
- [Licença](#licença)

## Visão geral

O DevPilot AI expõe uma API HTTP para:

- consultar o status do agente orquestrador;
- executar uma análise de código;
- coordenar uma análise completa com vários agentes especializados;
- criar, listar e consultar análises persistidas;
- verificar a saúde e a prontidão da aplicação.

Os agentes retornam resultados estruturados, incluindo pontuação, problemas encontrados e resumo da análise. A aplicação pode ser executada localmente, com Docker Compose e PostgreSQL, ou integrada a outros clientes HTTP e clientes MCP.

## Dashboard

Depois de iniciar o servidor, acesse:

**http://127.0.0.1:8000/dashboard**

O dashboard apresenta um formulário para enviar o nome do projeto e o código-fonte à API. Ele usa recursos locais da aplicação e não deve expor variáveis de ambiente, credenciais ou valores de configuração no HTML enviado ao navegador.

A interface usa HTML semântico, mantém a associação entre rótulos e campos, permite navegação por teclado e adapta-se a diferentes larguras de tela. Acessibilidade e responsividade também dependem do conteúdo fornecido e do ambiente de implantação.

## Arquitetura V1–V7

A evolução do projeto é organizada nas seguintes versões:

- **V1 — API inicial:** aplicação FastAPI, contratos de requisição e resposta e análise direta de código por `code_agent`.
- **V2 — Agentes especializados:** inclusão de `test_agent` e `docs_agent`, com resultados estruturados para código, testes e documentação.
- **V3 — Orquestração:** inclusão de `orchestrator` e `report_agent` para delegar tarefas e consolidar uma análise completa.
- **V4 — Aplicação persistida:** dashboard, serviço de análises, armazenamento, endpoints `/analyses`, migrações Alembic e validação de entrada.
- **V5 — Tools e skills:** contratos `BaseTool`, `ToolRegistry`, `SkillRegistry`, `ToolExecutor`, injeção de dependências e ferramentas de projeto confinadas à raiz do projeto.
- **V6 — MCP v2:** integração em processo com `MCPServer` e `Client`, descoberta determinística, resultados JSON estruturados, sanitização de erros e registry isolado por servidor.
- **V7 — Operação e entrega:** execução reproduzível com Docker e Compose, PostgreSQL, endpoints de health/readiness, configuração por ambiente, CI e estratégia de testes para validar a aplicação completa.

A arquitetura atual é composta por:

- **API:** rotas HTTP, validação de entrada e serialização das respostas;
- **Dashboard:** interface web servida pela aplicação;
- **Orquestrador:** coordena tarefas e encaminha o contexto aos agentes adequados;
- **Agentes especializados:** `code_agent`, `test_agent`, `docs_agent` e `report_agent`;
- **Serviço de análise:** cria, lista e recupera registros de análise;
- **Persistência:** modelos e acesso ao banco de dados;
- **Tools e skills:** capacidades registradas e executadas com limites explícitos;
- **MCP:** fronteira independente de transporte para descoberta e chamada de ferramentas;
- **Operação:** health/readiness, Docker, Compose, PostgreSQL, migrações e CI.

## Fluxos de trabalho

### Análise direta de código

O cliente envia `project_name` e `source_code` para `POST /agents/code`. O `code_agent` analisa o conteúdo e retorna uma pontuação, a lista de problemas e um resumo.

### Análise completa orquestrada

O cliente envia uma tarefa `full_analysis` para `POST /agents/orchestrate`. O `orchestrator` encaminha o contexto a `code_agent`, `test_agent`, `docs_agent` e `report_agent`, retornando o resultado consolidado.

### Análise persistida

O cliente envia uma análise para `POST /analyses`. O serviço persiste a solicitação e o resultado. Os registros podem ser listados com `GET /analyses` e consultados individualmente com `GET /analyses/{analysis_id}`.

### Execução pelo dashboard

O usuário acessa o dashboard, preenche o formulário e envia o código para a API. O dashboard é somente uma interface dos endpoints disponíveis; validação, autorização e processamento permanecem no servidor.

## Runtime de ferramentas e skills

O runtime separa definição, registro, descoberta e execução de capacidades. Uma ferramenta implementa `BaseTool` e possui `name`, `description`, `input_schema` e `execute(**kwargs)`. O resultado é estruturado e indica sucesso ou erro.

`ToolRegistry` mantém as ferramentas disponibilizadas e `SkillRegistry` mantém skills compostas. `ToolExecutor` recebe registries e dependências por injeção, resolve somente nomes registrados e valida a entrada pelo contrato. Nenhuma string fornecida pelo usuário é interpretada como comando shell, módulo, função ou executável.

As ferramentas de projeto disponíveis são:

- `list_files`: lista arquivos regulares sob a raiz do projeto, usando caminhos relativos POSIX;
- `read_file`: lê um arquivo permitido dentro da raiz;
- `write_file`: grava conteúdo em um arquivo permitido dentro da raiz;
- `run_tests`: executa `python -m pytest -p no:cacheprovider` com caminho opcional relativo ao projeto.

Os caminhos são resolvidos em relação à raiz injetada. Caminhos fora dela e arquivos protegidos, como `.env`, `.git`, `.venv`, `__pycache__` e `.pytest_cache`, são rejeitados. `.env.example` pode ser tratado como arquivo normal. `run_tests` não aceita executável, flags, shell ou comandos adicionais, executa na raiz do projeto, desativa bytecode e tem limite de 120 segundos.

O runtime não fornece execução arbitrária de shell, acesso irrestrito ao sistema de arquivos, instalação de pacotes, acesso de rede, leitura de segredos ou execução em contêiner como capacidades implícitas.

## MCP v2

O MCP v2 usa `MCPServer` e `Client` como fronteira de descoberta e execução de ferramentas, sem acoplar o domínio a HTTP, stdio ou outro transporte específico.

As ferramentas são registradas explicitamente com `@server.tool()`. Cada `MCPServer` tem identidade e registry próprios; não há registry global implícito. `Client` descobre ferramentas com `list_tools()` e chama uma ferramenta registrada com `call_tool(name, arguments)`.

`list_tools()` retorna somente ferramentas do servidor em ordem determinística, com nome, descrição e schema de entrada. Os resultados são serializáveis em JSON e as falhas atravessam a fronteira como resultados MCP estruturados, com mensagens sanitizadas. Uma ferramenta desconhecida não executa outra ferramenta nem altera o registry.

Exemplo mínimo:

```python
from mcp.client import Client
from mcp.server import MCPServer

server = MCPServer("devpilot-v6")

@server.tool()
async def add(left: int, right: int) -> dict[str, int]:
    """Add two integers."""
    return {"sum": left + right}

async with Client(server) as client:
    tools = await client.list_tools()
    result = await client.call_tool("add", {"left": 20, "right": 22})
```

O MCP não é um executor genérico. O nome de `call_tool()` é somente uma chave de resolução no registry. Autorização, limites de recursos, autenticação, TLS e isolamento de processo continuam sendo responsabilidades da composição e da implantação.

## Requisitos

- Python 3.11 ou superior;
- `pip`;
- ambiente virtual para instalação local;
- Docker e Docker Compose para a execução conteinerizada;
- PostgreSQL para a configuração de produção ou Compose.

## Instalação

```bash
git clone https://github.com/devpilot-ai/devpilot-ai.git
cd devpilot-ai
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

No Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Quando disponível, instale também as dependências de desenvolvimento:

```bash
pip install -r requirements-dev.txt
```

## Configuração

A aplicação é configurada por variáveis de ambiente. `DATABASE_URL` define o banco usado pelo serviço de análises.

SQLite local:

```bash
export DATABASE_URL="sqlite+aiosqlite:///./devpilot.db"
```

PostgreSQL:

```bash
export DATABASE_URL="postgresql+asyncpg://devpilot:devpilot@localhost:5432/devpilot"
```

No Windows PowerShell:

```powershell
$env:DATABASE_URL = "sqlite+aiosqlite:///./devpilot.db"
```

Não coloque credenciais no código, no dashboard ou em arquivos públicos. Use os valores definidos pelo ambiente de execução.

## Execução local

Aplique as migrações antes de usar a persistência:

```bash
alembic upgrade head
```

Inicie o servidor:

```bash
uvicorn app.main:app --reload
```

A API e o dashboard ficarão disponíveis em `http://127.0.0.1:8000`. A documentação está em `/docs` e `/redoc`.

## Docker e Compose

Para iniciar a aplicação e o PostgreSQL com Docker Compose:

```bash
docker compose up --build
```

Para executar em segundo plano:

```bash
docker compose up --build -d
```

Para parar os serviços:

```bash
docker compose down
```

A configuração de Compose fornece a aplicação e o PostgreSQL, injeta `DATABASE_URL` no serviço da aplicação e usa a verificação de health para ordenar a inicialização. As migrações devem ser aplicadas pelo comando de inicialização definido para o ambiente ou explicitamente antes de usar os endpoints persistidos:

```bash
docker compose exec app alembic upgrade head
```

Os nomes exatos dos serviços devem ser conferidos no arquivo `docker-compose.yml` do checkout utilizado.

## Health e readiness

Use os endpoints operacionais para verificar a aplicação:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

`/health` indica que o processo da aplicação está ativo. `/ready` indica que a aplicação está pronta para atender o tráfego dependente de seus recursos configurados, incluindo a persistência. Uma resposta de health não substitui a verificação de readiness.

Esses endpoints também podem ser usados pelo Docker Compose e por orquestradores para liveness e readiness. Os controles de reinício, autenticação, rede e observabilidade pertencem à implantação.

## Segurança

- Não coloque chaves, tokens, senhas ou URLs privadas diretamente no código, no dashboard ou em exemplos públicos.
- Mantenha valores sensíveis em variáveis de ambiente e não os envie ao navegador.
- Valide entradas no servidor; campos ausentes ou inválidos são rejeitados.
- Use UUIDs válidos em `analysis_id`; identificadores inexistentes retornam `404 Not Found` e UUIDs malformados retornam `422 Unprocessable Entity`.
- Ferramentas de arquivos ficam confinadas à raiz injetada e rejeitam caminhos fora dela, arquivos protegidos e links simbólicos que escapem do projeto.
- `run_tests` usa comando fixo, caminho relativo opcional e limite de 120 segundos; não é um executor arbitrário.
- Registries expõem somente ferramentas e skills explicitamente registradas.
- Cada `MCPServer` mantém registry isolado; argumentos são validados e erros são sanitizados.
- Credenciais, segredos e acesso de rede não são concedidos implicitamente a ferramentas.
- Revise migrações autogeradas antes de aplicá-las em outros ambientes.
- Em produção, use HTTPS, controles de acesso, segredos gerenciados e uma configuração de PostgreSQL apropriada.

O MCP é uma fronteira de capacidade, não uma fronteira automática de privilégio. Qualquer ferramenta que acesse arquivos, processos, rede ou credenciais deve ser deliberadamente limitada e auditada.

## API

### Status do orquestrador

```http
GET /agents/orchestrator
```

### Health e readiness

```http
GET /health
GET /ready
```

### Análise de código

```http
POST /agents/code
```

Corpo:

```json
{
  "project_name": "devpilot-ai",
  "source_code": "def hello():\n    return 'hello'\n"
}
```

### Análise orquestrada

```http
POST /agents/orchestrate
```

Para `task` igual a `full_analysis`, o orquestrador delega a tarefa aos quatro agentes especializados. Uma tarefa sem agente disponível retorna `400`.

### Criar uma análise

```http
POST /analyses
```

A resposta bem-sucedida usa `201 Created` e contém o registro completo, incluindo identificador, resultado e data de criação.

### Listar análises

```http
GET /analyses?limit=20
```

`limit` é opcional, tem padrão `20` e aceita valores de `1` a `100`. Os registros são retornados do mais recente para o mais antigo.

### Consultar uma análise

```http
GET /analyses/{analysis_id}
```

`analysis_id` deve ser um UUID válido. Identificadores inexistentes retornam `404 Not Found`; UUIDs malformados retornam `422 Unprocessable Entity`.

## Persistência e Alembic

As alterações do schema são controladas por Alembic. Depois de configurar `DATABASE_URL`, aplique as migrações:

```bash
alembic upgrade head
```

Para criar uma migração após alterar os modelos:

```bash
alembic revision --autogenerate -m "descreva a alteração"
```

Sempre revise uma migração gerada automaticamente antes de aplicá-la em outro ambiente. PostgreSQL é o banco usado na execução com Docker Compose; SQLite pode ser usado para desenvolvimento local conforme a configuração suportada pelo projeto.

## CI

O workflow de CI está em `.github/workflows/ci.yml` e é executado pelo GitHub Actions. A verificação deve ser mantida verde antes de integrar alterações. Ela instala as dependências do projeto e executa a suíte automatizada conforme a configuração do repositório.

Alterações em código, migrações, ferramentas, MCP, Docker ou documentação devem manter a configuração de CI e os comandos reproduzíveis localmente.

## Testes

Execute a suíte completa com:

```bash
pytest
```

Para cobertura:

```bash
pytest --cov=app
```

Os testes verificam endpoints de agentes e análises, validação, serialização, ordenação, códigos HTTP, dashboard, conteúdo semântico, ausência de segredos no HTML e uso de arquivos locais de CSS e JavaScript.

A cobertura V5 verifica contratos de ferramentas, registries, descoberta, executor, injeção de dependências, isolamento da raiz e limites das ferramentas de arquivos e testes.

A cobertura V6 verifica `MCPServer` e `Client`, registry canônico, isolamento entre servidores, descoberta ordenada, resultados JSON, erros sanitizados, chamadas em processo e ausência de capacidades arbitrárias de shell. Esses testes não dependem de rede, portas, subprocessos ou transporte externo.

A cobertura V7 verifica configuração operacional, endpoints de health/readiness, integração com persistência, migrações e execução compatível com Docker/Compose. A ferramenta `run_tests` executa `python -m pytest -p no:cacheprovider`, impede caminhos fora da raiz e aplica o limite de 120 segundos.

## Estrutura do projeto

```text
.
├── app/
│   ├── agents/       # Agentes especializados
│   ├── api/          # Rotas e dependências da API
│   ├── models/       # Modelos da aplicação e persistência
│   ├── tools/        # Contratos, registries e ferramentas seguras
│   ├── skills/       # Skills e dependências
│   └── main.py       # Ponto de entrada da aplicação FastAPI
├── migrations/       # Migrações Alembic
├── tests/            # Testes automatizados
├── .github/          # Workflows de CI
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Roadmap concluído

As etapas abaixo estão concluídas e fazem parte da implementação atual:

- API FastAPI e análise direta por agentes;
- agentes de código, testes, documentação e relatório;
- orquestração de análise completa;
- dashboard web local, sem exposição de segredos;
- persistência de análises e migrações Alembic;
- runtime V5 de tools e skills com registries, injeção e limites de segurança;
- MCP v2 com `MCPServer`/`Client`, descoberta determinística e resultados estruturados;
- execução em Docker e Docker Compose com PostgreSQL;
- endpoints de health e readiness;
- suíte de testes automatizada e workflow de CI;
- documentação de segurança, acessibilidade, operação e estratégia de testes.

Próximas melhorias podem ampliar as capacidades de análise, os relatórios, a observabilidade, a experiência do dashboard e as adaptações de transporte MCP sem remover as fronteiras de segurança existentes.

## Contribuição

Contribuições são bem-vindas. Antes de abrir um pull request:

1. crie uma branch para sua alteração;
2. mantenha código, testes e documentação consistentes;
3. preserve os requisitos de segurança, acessibilidade e responsividade;
4. execute `pytest` e verifique o CI;
5. descreva claramente a mudança proposta.

## Licença

Consulte o arquivo de licença do repositório para obter os termos aplicáveis.
