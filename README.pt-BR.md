# DevPilot AI

[![CI](https://github.com/devpilot-ai/devpilot-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/devpilot-ai/devpilot-ai/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)

[English](README.md) | **Português**

DevPilot AI é uma API para análise automatizada de projetos de software. A aplicação utiliza agentes especializados para analisar código, testes e documentação, coordenando os resultados por meio de um orquestrador.

> **Status do projeto:** em desenvolvimento ativo. A API e a arquitetura principal estão disponíveis, mas o projeto ainda está evoluindo.

## Sumário

- [Visão geral](#visão-geral)
- [Arquitetura](#arquitetura)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Configuração](#configuração)
- [Execução](#execução)
- [API](#api)
- [Persistência e migrações](#persistência-e-migrações)
- [Testes](#testes)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Roadmap](#roadmap)
- [Contribuição](#contribuição)

## Visão geral

O DevPilot AI expõe uma API HTTP baseada em FastAPI para:

- consultar o status do agente orquestrador;
- executar uma análise de código;
- coordenar uma análise completa com vários agentes especializados;
- criar, listar e consultar análises armazenadas.

Os agentes retornam resultados estruturados, incluindo pontuação, problemas encontrados e um resumo da análise.

## Arquitetura

A aplicação é organizada em camadas:

- **API:** rotas HTTP e validação dos dados de entrada;
- **Orquestrador:** coordena a tarefa e encaminha o contexto aos agentes adequados;
- **Agentes especializados:** executam análises específicas;
- **Serviço de análise:** cria, lista e recupera os registros de análise;
- **Persistência:** armazena as análises e seus resultados.

Os agentes disponíveis no fluxo de análise completa são:

- `code_agent`: analisa o código-fonte;
- `test_agent`: analisa testes Python e sua estrutura;
- `docs_agent`: analisa a documentação;
- `report_agent`: consolida os resultados em um relatório.

O `orchestrator` coordena o fluxo e delega a execução aos agentes especializados.

## Requisitos

- Python 3.11 ou superior;
- `pip`;
- um ambiente virtual recomendado para a instalação das dependências.

## Instalação

Clone o repositório e entre no diretório do projeto:

```bash
git clone https://github.com/devpilot-ai/devpilot-ai.git
cd devpilot-ai
```

Crie e ative um ambiente virtual:

```bash
python -m venv .venv
source .venv/bin/activate
```

No Windows PowerShell, use:

```powershell
.venv\Scripts\Activate.ps1
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

Se o projeto estiver sendo desenvolvido localmente, instale também as dependências de desenvolvimento quando esse arquivo estiver disponível:

```bash
pip install -r requirements-dev.txt
```

## Configuração

A aplicação pode ser configurada por variáveis de ambiente. Defina `DATABASE_URL` para informar a URL do banco de dados utilizado pelo serviço de análises.

Exemplo para um banco SQLite local:

```bash
export DATABASE_URL="sqlite+aiosqlite:///./devpilot.db"
```

No Windows PowerShell:

```powershell
$env:DATABASE_URL = "sqlite+aiosqlite:///./devpilot.db"
```

Caso `DATABASE_URL` não seja definida, consulte a configuração padrão do projeto antes de iniciar a aplicação.

## Execução

Inicie o servidor de desenvolvimento com:

```bash
uvicorn app.main:app --reload
```

A API ficará disponível em `http://127.0.0.1:8000`.

A documentação interativa pode ser acessada em:

- Swagger UI: `http://127.0.0.1:8000/docs`;
- ReDoc: `http://127.0.0.1:8000/redoc`.

## API

### Status do orquestrador

```http
GET /agents/orchestrator
```

Exemplo:

```bash
curl http://127.0.0.1:8000/agents/orchestrator
```

Resposta:

```json
{
  "agent": "orchestrator",
  "responsibility": "Coordinate and route tasks to specialized agents.",
  "status": "ready"
}
```

### Análise de código

```http
POST /agents/code
```

Exemplo:

```bash
curl -X POST http://127.0.0.1:8000/agents/code \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "devpilot-ai",
    "source_code": "def hello():\n    return '\''hello'\''\n"
  }'
```

O corpo da requisição exige `project_name` e `source_code`.

### Análise orquestrada

```http
POST /agents/orchestrate
```

Exemplo:

```bash
curl -X POST http://127.0.0.1:8000/agents/orchestrate \
  -H "Content-Type: application/json" \
  -d '{
    "task": "full_analysis",
    "project_name": "devpilot-ai",
    "source_code": "def test_health():\n    assert True\n"
  }'
```

Para `full_analysis`, o orquestrador delega a tarefa aos agentes de código, testes, documentação e relatório. Se não houver um agente disponível para a tarefa solicitada, a API retorna `400`.

### Criar uma análise

```http
POST /analyses
```

Exemplo:

```bash
curl -X POST http://127.0.0.1:8000/analyses \
  -H "Content-Type: application/json" \
  -d '{
    "task": "code_analysis",
    "project_name": "devpilot-ai",
    "source_code": "def hello():\n    return '"'"'hello'"'"'\n"
  }'
```

A resposta bem-sucedida usa o status `201 Created` e contém o registro completo da análise, incluindo seu identificador, resultado e data de criação.

### Listar análises

```http
GET /analyses?limit=20
```

O parâmetro `limit` é opcional, tem valor padrão `20` e aceita valores de `1` a `100`. Os registros são retornados do mais recente para o mais antigo.

Exemplo:

```bash
curl "http://127.0.0.1:8000/analyses?limit=10"
```

### Consultar uma análise

```http
GET /analyses/{analysis_id}
```

`analysis_id` deve ser um UUID válido. A API retorna `404 Not Found` quando o identificador não existe e `422 Unprocessable Entity` quando o UUID está malformado.

Exemplo:

```bash
curl http://127.0.0.1:8000/analyses/11111111-1111-4111-8111-111111111111
```

## Persistência e migrações

As alterações do esquema do banco de dados devem ser controladas por migrações. Depois de configurar o banco de dados, aplique as migrações disponíveis com:

```bash
alembic upgrade head
```

Para criar uma nova migração após alterar os modelos:

```bash
alembic revision --autogenerate -m "descreva a alteração"
```

Revise sempre uma migração gerada automaticamente antes de aplicá-la em outro ambiente.

## Testes

Execute toda a suíte de testes com:

```bash
pytest
```

Para obter cobertura de uma execução, use:

```bash
pytest --cov=app
```

Os testes da API verificam os endpoints de agentes e análises, a validação dos dados de entrada, a serialização dos registros, a ordenação e os códigos de erro HTTP.

## Estrutura do projeto

```text
.
├── app/
│   ├── agents/       # Agentes especializados
│   ├── api/          # Rotas e dependências da API
│   ├── models/       # Modelos da aplicação e persistência
│   └── main.py       # Ponto de entrada da aplicação FastAPI
├── migrations/       # Migrações do banco de dados
├── tests/            # Testes automatizados
├── requirements.txt
└── README.md
```

## Roadmap

- ampliar as capacidades de análise dos agentes;
- aprimorar a consolidação dos relatórios;
- expandir a cobertura de testes;
- evoluir a persistência e o gerenciamento das análises;
- melhorar a documentação e a experiência de uso da API.

O roadmap pode mudar conforme o projeto evolui.

## Contribuição

Contribuições são bem-vindas. Antes de abrir um pull request:

1. crie uma branch para sua alteração;
2. mantenha o código e a documentação consistentes;
3. execute os testes com `pytest`;
4. descreva claramente a mudança proposta.

## Licença

Consulte o arquivo de licença do repositório para obter os termos aplicáveis.