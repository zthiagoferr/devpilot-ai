# DevPilot AI

[![CI](https://github.com/devpilot-ai/devpilot-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/devpilot-ai/devpilot-ai/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)

[English](README.md) | **Português**

DevPilot AI é uma aplicação para análise automatizada de projetos de software. A API utiliza agentes especializados para analisar código, testes e documentação, coordenando os resultados por meio de um orquestrador. O projeto também disponibiliza um dashboard web para iniciar e acompanhar análises.

> **Status do projeto:** em desenvolvimento ativo. A API, o dashboard e a arquitetura principal estão disponíveis, mas o projeto ainda está evoluindo.

## Sumário

- [Visão geral](#visão-geral)
- [Dashboard](#dashboard)
- [Arquitetura](#arquitetura)
- [Fluxos de trabalho](#fluxos-de-trabalho)
- [Runtime V5 de ferramentas e skills](#runtime-v5-de-ferramentas-e-skills)
- [MCP v2 e runtime V6](#mcp-v2-e-runtime-v6)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Configuração](#configuração)
- [Execução](#execução)
- [Segurança](#segurança)
- [Acessibilidade e responsividade](#acessibilidade-e-responsividade)
- [API](#api)
- [Persistência e migrações](#persistência-e-migrações)
- [Testes](#testes)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Informações das versões V1–V5](#informações-das-versões-v1v5)
- [Roadmap](#roadmap)
- [Contribuição](#contribuição)
- [Licença](#licença)

## Visão geral

O DevPilot AI expõe uma API HTTP baseada em FastAPI para:

- consultar o status do agente orquestrador;
- executar uma análise de código;
- coordenar uma análise completa com vários agentes especializados;
- criar, listar e consultar análises armazenadas.

Os agentes retornam resultados estruturados, incluindo pontuação, problemas encontrados e um resumo da análise. A aplicação está preparada para uso local e para integração com outros clientes HTTP.

## Dashboard

Depois de iniciar o servidor, acesse o dashboard em:

**http://127.0.0.1:8000/dashboard**

A interface apresenta um formulário para enviar o nome do projeto e o código-fonte à API. Ela usa recursos locais da aplicação e não deve expor variáveis de ambiente, credenciais ou valores de configuração no HTML enviado ao navegador.

## Arquitetura

A aplicação é organizada em camadas:

- **API:** rotas HTTP, validação dos dados de entrada e serialização das respostas;
- **Dashboard:** interface web servida pela aplicação para iniciar análises;
- **Orquestrador:** coordena a tarefa e encaminha o contexto aos agentes adequados;
- **Agentes especializados:** executam análises específicas;
- **Serviço de análise:** cria, lista e recupera os registros de análise;
- **Persistência:** armazena as análises e seus resultados;
- **Runtime de ferramentas e skills:** disponibiliza ferramentas permitidas, registra suas definições e executa as chamadas com limites explícitos;
- **Runtime MCP V6:** expõe ferramentas por servidores MCP e permite que clientes MCP as descubram e chamem por uma fronteira independente de transporte.

Os agentes disponíveis no fluxo de análise completa são:

- `code_agent`: analisa o código-fonte;
- `test_agent`: analisa testes Python e sua estrutura;
- `docs_agent`: analisa a documentação;
- `report_agent`: consolida os resultados em um relatório.

O `orchestrator` coordena o fluxo e delega a execução aos agentes especializados. A implementação também inclui a ferramenta `run_tests`, que executa a suíte de testes do projeto com `pytest` quando acionada pelo fluxo correspondente.

## Fluxos de trabalho

### Análise direta de código

O cliente envia `project_name` e `source_code` para `POST /agents/code`. O agente de código analisa o conteúdo e retorna uma pontuação, a lista de problemas e um resumo.

### Análise completa orquestrada

Para uma análise completa, o cliente envia uma tarefa `full_analysis` para `POST /agents/orchestrate`. O orquestrador encaminha o contexto aos agentes de código, testes, documentação e relatório, retornando o resultado consolidado.

### Análise persistida

O cliente pode enviar uma análise para `POST /analyses`. O serviço persiste a solicitação e o resultado, permite listar os registros com `GET /analyses` e recuperar um registro específico com `GET /analyses/{analysis_id}`.

### Execução pelo dashboard

O usuário acessa o dashboard, preenche o formulário e envia o código para a API. O dashboard é apenas uma interface de acesso aos endpoints disponíveis; a validação e o processamento permanecem no servidor.

## Runtime V5 de ferramentas e skills

A V5 introduz um runtime explícito para ferramentas e skills. O runtime separa a definição de uma capacidade, seu registro, sua descoberta e sua execução. Isso permite que agentes recebam somente as capacidades que foram deliberadamente disponibilizadas, sem transformar a aplicação em um executor genérico de comandos.

### Contratos

Uma ferramenta implementa o contrato `BaseTool`. Ela possui, no mínimo, um `name`, uma `description`, um `input_schema` e um método assíncrono `execute(**kwargs)`. O schema descreve a entrada aceita e o resultado da execução é estruturado, com um status de sucesso ou erro. As definições de ferramenta podem ser obtidas por metadados ou por `get_tool_definition()`.

Skills representam capacidades compostas que podem utilizar ferramentas registradas. Uma skill deve declarar sua identidade e suas dependências de forma explícita; a existência de uma skill não concede automaticamente acesso a todas as ferramentas ou a recursos do sistema.

Os contratos são limites de runtime, não uma promessa de que qualquer agente possa executar qualquer operação. Validação de entrada, autorização, isolamento e tratamento de erros continuam sendo responsabilidades da implementação e da implantação.

### Registries e descoberta

`ToolRegistry` mantém as ferramentas disponibilizadas ao runtime. Ferramentas podem ser registradas por meio do registro e consultadas pelo nome. `SkillRegistry` faz o mesmo para skills. A descoberta deve retornar somente definições registradas, incluindo nome, descrição e schema de entrada, para que o consumidor saiba o que pode solicitar antes de executar uma chamada.

O registro não aceita implicitamente um nome de executável, uma linha de comando ou entrada de shell. A descoberta também não significa descoberta dinâmica de módulos arbitrários: somente componentes integrados e registrados pela aplicação fazem parte do conjunto disponível.

### Executor e injeção de dependências

`ToolExecutor` recebe o registry e as dependências necessárias por injeção. A resolução de uma chamada ocorre pelo nome registrado, valida a entrada de acordo com o contrato e delega a execução à ferramenta correspondente. O executor não deve interpretar uma string como comando de shell nem criar ferramentas com base em dados fornecidos pelo usuário.

A injeção de dependências torna explícitos o registry, a raiz do projeto e os demais recursos usados por uma ferramenta. Em testes, essas dependências podem ser substituídas por implementações controladas. Em produção, a composição deve registrar apenas as ferramentas aprovadas para aquele contexto.

### Isolamento e ferramentas seguras disponíveis

A V5 oferece um conjunto restrito de ferramentas de projeto:

- `list_files`: lista arquivos regulares visíveis sob a raiz do projeto, usando caminhos relativos POSIX;
- `read_file`: lê um arquivo permitido dentro da raiz do projeto;
- `write_file`: grava conteúdo em um arquivo permitido dentro da raiz do projeto;
- `run_tests`: executa a suíte de testes do projeto com `python -m pytest -p no:cacheprovider`.

As ferramentas de arquivos resolvem os caminhos em relação à raiz injetada, rejeitam caminhos que escapem dessa raiz e não permitem acesso a arquivos protegidos, como `.env`, `.git`, `.venv`, `__pycache__` e `.pytest_cache`. `.env.example` pode ser tratado como arquivo normal. Links simbólicos que apontem para fora do projeto não devem ser usados para contornar esse limite.

`run_tests` aceita opcionalmente um caminho relativo de teste. O comando e seus argumentos executáveis são fixos: o chamador não fornece executável, flags, shell ou comandos adicionais. A execução ocorre na raiz do projeto, desativa a geração de bytecode e possui limite de 120 segundos. Saídas e códigos de retorno são devolvidos como resultado da ferramenta; erros não devem expor comandos, variáveis de ambiente, exceções internas ou detalhes desnecessários do sistema de arquivos.

Esse conjunto é intencionalmente limitado. A V5 não documenta execução arbitrária de shell, acesso irrestrito ao sistema de arquivos, instalação de pacotes, acesso à rede, leitura de segredos ou execução em contêiner como capacidades fornecidas pelo runtime.

## MCP v2 e runtime V6

A V6 adiciona suporte ao MCP v2 usando a implementação oficial de `MCPServer` e `Client`. O MCP fornece uma fronteira de descoberta e execução de ferramentas sem acoplar o domínio da aplicação a HTTP, stdio ou qualquer outro transporte específico. Nesta versão, a integração é determinística, segura e pode ser exercitada inteiramente dentro do processo.

### Arquitetura MCPServer/Client

`MCPServer` é o ponto de composição de um servidor MCP. Cada instância possui seu próprio registro de ferramentas e sua própria identidade. As ferramentas são adicionadas explicitamente com o decorador `@server.tool()`, e não por descoberta de módulos ou por nomes recebidos do usuário.

`Client` é o consumidor da interface MCP. Ele pode descobrir as ferramentas com `list_tools()` e chamar uma ferramenta registrada com `call_tool(name, arguments)`. O cliente não acessa diretamente funções internas: a chamada passa pela fronteira do servidor, que resolve o nome no registro daquela instância, valida os argumentos e devolve o resultado MCP.

O registro canônico é injetado no servidor MCP no momento da composição. Assim, o servidor é a única fonte de verdade para as ferramentas disponíveis naquele contexto; não existe um registro global implícito compartilhado entre servidores. Dois `MCPServer` independentes não compartilham ferramentas, e registrar uma ferramenta em um deles não altera a descoberta do outro.

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

A composição da aplicação deve criar o servidor, injetar o registry canônico e registrar somente as ferramentas aprovadas. O cliente recebe uma interface MCP, não acesso à raiz do projeto, ao ambiente do processo ou a objetos internos do servidor.

### Descoberta e resultados estruturados

A descoberta é estável e determinística. `list_tools()` retorna somente as ferramentas registradas naquele `MCPServer`, em ordem determinística (atualmente ordenada pelo nome), com nome, descrição e schema de entrada. Repetir a descoberta não deve produzir uma ordem diferente nem incluir ferramentas de outro servidor.

Os resultados de ferramentas devem ser valores estruturados e serializáveis em JSON. Por exemplo, uma ferramenta que soma dois números retorna `{"sum": 42}` como conteúdo JSON, em vez de exigir que o consumidor interprete texto ad hoc. O cliente pode inspecionar `result.is_error` e os itens de `result.content`; o conteúdo textual JSON pode ser decodificado normalmente.

Falhas de ferramentas também atravessam a fronteira como resultados MCP estruturados com indicação de erro. Mensagens são sanitizadas: detalhes de exceções internas, segredos, variáveis de ambiente, comandos e caminhos privados não são devolvidos ao cliente. Uma ferramenta desconhecida produz erro sem executar outra ferramenta e sem alterar o registry.

### Limites de segurança

MCP v2 não transforma o DevPilot em um executor genérico. O nome usado em `call_tool()` é apenas uma chave de resolução no registro canônico; nunca é interpretado como módulo, função, executável, comando shell ou caminho de arquivo. O servidor não oferece capacidades arbitrárias como `shell`, `execute_shell`, `run_command`, `exec` ou `subprocess`.

As fronteiras de segurança da V6 são:

- somente ferramentas explicitamente registradas podem ser descobertas ou chamadas;
- cada servidor mantém isolamento do seu registry;
- argumentos são validados pelo contrato da ferramenta;
- resultados precisam ser estruturados e serializáveis;
- erros são sanitizados antes de serem enviados ao cliente;
- credenciais, segredos e acesso de rede não são concedidos implicitamente;
- a API MCP não contorna o isolamento de arquivos e os limites das ferramentas V5;
- autorização, limites de recursos e isolamento do processo continuam sendo responsabilidades da composição e da implantação.

O MCP é uma fronteira de capacidade, não uma fronteira automática de privilégio. Caso uma implantação disponibilize ferramentas que acessam arquivos, processos, rede ou credenciais, esses acessos devem ser deliberados, limitados e auditados separadamente.

### Testes determinísticos em processo

A suíte V6 usa `Client(server)` para conectar o cliente diretamente ao `MCPServer`, sem depender de rede, portas, subprocessos ou um transporte externo. Isso torna os testes rápidos, reproduzíveis e determinísticos, além de verificar a mesma fronteira de descoberta e chamada usada pela integração MCP.

Os testes cobrem criação do servidor, isolamento entre registries, ordenação determinística da descoberta, chamadas bem-sucedidas, chamadas para ferramentas desconhecidas, serialização JSON, sanitização de erros e ausência de capacidades arbitrárias de shell. Um teste equivalente a uma chamada de cliente é:

```python
async with Client(server) as client:
    tools = await client.list_tools()
    result = await client.call_tool("echo", {"value": "in-process"})

assert not result.is_error
```

### Uso

Para adicionar uma ferramenta MCP, crie ou receba um `MCPServer` na composição da aplicação e use `@server.tool()` sobre uma função assíncrona com argumentos tipados e retorno JSON-serializável. Para consumir o servidor, abra um `Client` como gerenciador assíncrono, descubra as ferramentas antes de chamá-las e trate `is_error` sem expor conteúdo sensível ao usuário.

O código de domínio deve depender da interface do servidor e do cliente, e não de detalhes de transporte. A mesma fronteira pode ser adaptada posteriormente para um transporte suportado pelo MCP sem alterar os contratos das ferramentas, a descoberta, os resultados estruturados ou os limites de segurança.

### Fronteira independente de transporte da V6

A V6 define a fronteira em termos de `MCPServer`, `Client`, descoberta de ferramentas e chamadas com resultados estruturados. O transporte é uma preocupação posterior da adaptação. O teste em processo é deliberadamente a implementação mínima dessa fronteira: ele não prova segurança de uma implantação de rede, nem substitui controles de autenticação, autorização, TLS, isolamento de processo ou limites operacionais.

Em resumo, a V6 separa:

1. **composição:** registry canônico injetado e ferramentas aprovadas;
2. **protocolo:** descoberta e chamadas MCPServer/Client;
3. **resultado:** conteúdo JSON estruturado e erros sanitizados;
4. **transporte:** camada substituível, não presumida pelo domínio;
5. **implantação:** controles adicionais necessários para ambientes não locais.

## Requisitos

- Python 3.11 ou superior;
- `pip`;
- um ambiente virtual, recomendado para a instalação das dependências;
- um banco compatível com a configuração de `DATABASE_URL` para usar a persistência.

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

Aplique as migrações antes de usar os recursos de persistência:

```bash
alembic upgrade head
```

Inicie o servidor de desenvolvimento com:

```bash
uvicorn app.main:app --reload
```

A API e o dashboard ficarão disponíveis em `http://127.0.0.1:8000`. Acesse o dashboard em `http://127.0.0.1:8000/dashboard`.

A documentação interativa pode ser acessada em:

- Swagger UI: `http://127.0.0.1:8000/docs`;
- ReDoc: `http://127.0.0.1:8000/redoc`.

## Segurança

- Não coloque chaves, tokens, senhas ou URLs privadas diretamente no código, no dashboard ou em exemplos públicos.
- Mantenha os valores sensíveis em variáveis de ambiente e não os envie ao navegador.
- Valide as entradas no servidor. Os endpoints rejeitam campos obrigatórios ausentes ou inválidos.
- Use UUIDs válidos ao consultar análises; identificadores inexistentes retornam `404 Not Found` e UUIDs malformados retornam `422 Unprocessable Entity`.
- As ferramentas de arquivos ficam confinadas à raiz do projeto injetada e rejeitam caminhos fora dela, arquivos protegidos e links simbólicos que escapem do projeto.
- A ferramenta de execução de testes não é um executor de comandos arbitrários: o comando é fixo, o caminho opcional é relativo ao projeto e há um limite de 120 segundos.
- Registries e descoberta expõem somente ferramentas e skills explicitamente registradas. Não registre componentes com dados não confiáveis nem trate nomes descobertos como comandos executáveis.
- O runtime MCP V6 usa um registry canônico por servidor, mantém isolamento entre `MCPServer` e devolve resultados JSON estruturados com erros sanitizados.
- O runtime não deve receber credenciais, segredos ou acesso de rede como dependências de uma ferramenta sem uma decisão de segurança específica e uma implementação correspondente.
- Revise as migrações geradas automaticamente antes de aplicá-las em outros ambientes.
- Em produção, use HTTPS, controles de acesso e uma configuração de banco apropriada ao ambiente. Esses controles devem ser fornecidos pela implantação e não são presumidos pelo servidor de desenvolvimento.

## Acessibilidade e responsividade

O dashboard usa estrutura HTML semântica, incluindo título principal, formulário, campos de texto e botões, para oferecer uma base compatível com tecnologias assistivas. Os recursos de estilo são locais e a interface deve se adaptar a diferentes larguras de tela.

A acessibilidade depende também do conteúdo fornecido e do ambiente de implantação. Ao alterar a interface, preserve a associação entre rótulos e campos, o foco visível, a navegação por teclado, o contraste adequado e a leitura em telas menores.

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
    "source_code": "def hello():\n    return '\''hello'\''\n"
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

A suíte verifica os endpoints de agentes e análises, a validação dos dados de entrada, a serialização dos registros, a ordenação e os códigos de erro HTTP. Também verifica o dashboard, seu conteúdo semântico, a ausência de segredos no HTML e o uso de arquivos locais de CSS e JavaScript.

A cobertura V5 também verifica os contratos de ferramentas, os registries, a descoberta, o executor, a injeção de dependências, o isolamento da raiz do projeto e as fronteiras das ferramentas de arquivos e de testes.

A cobertura V6 verifica `MCPServer` e `Client`, o registry canônico injetado, o isolamento entre servidores, a descoberta ordenada, resultados JSON, erros sanitizados, chamadas em processo e a ausência de capacidades arbitrárias de shell. Esses testes não dependem de rede ou de um transporte externo.

A ferramenta de testes do projeto executa `python -m pytest` sem o provedor de cache do Pytest e impede que um caminho solicitado saia da raiz do projeto.

## Estrutura do projeto

```text
.
├── app/
│   ├── agents/       # Agentes especializados
│   ├── api/          # Rotas e dependências da API
│   ├── models/       # Modelos da aplicação e persistência
│   ├── tools/        # Contratos, registries e ferramentas seguras
│   ├── skills/       # Skills e suas dependências
│   └── main.py       # Ponto de entrada da aplicação FastAPI
├── migrations/       # Migrações do banco de dados
├── tests/            # Testes automatizados
├── requirements.txt
└── README.md
```

## Informações das versões V1–V5

As informações e referências históricas das versões V1, V2, V3, V4 e V5 são preservadas para manter o contexto da evolução do projeto. Esta documentação descreve o estado atual da V6; endpoints, fluxos ou componentes de versões anteriores não devem ser considerados parte da implementação atual sem confirmação no código.

- **V1:** versão inicial do projeto e da API de análise;
- **V2:** evolução da organização dos agentes e dos fluxos de análise;
- **V3:** consolidação do orquestrador e da persistência das análises;
- **V4:** versão com o dashboard, a API atual, os fluxos orquestrados, as migrações e os requisitos de segurança, acessibilidade e testes;
- **V5:** versão com contratos explícitos de ferramentas e skills, registries, descoberta controlada, executor com injeção de dependências, isolamento por raiz de projeto e o conjunto restrito de ferramentas seguras descrito acima.

## Roadmap

- ampliar as capacidades de análise dos agentes;
- aprimorar a consolidação dos relatórios;
- expandir a cobertura de testes;
- evoluir a persistência e o gerenciamento das análises;
- melhorar a documentação, a acessibilidade e a experiência de uso da API e do dashboard;
- ampliar a integração MCP mantendo o registry canônico, os resultados estruturados e a independência de transporte.

O roadmap pode mudar conforme o projeto evolui.

## Contribuição

Contribuições são bem-vindas. Antes de abrir um pull request:

1. crie uma branch para sua alteração;
2. mantenha o código e a documentação consistentes;
3. preserve os requisitos de segurança, acessibilidade e responsividade;
4. execute os testes com `pytest`;
5. descreva claramente a mudança proposta.

## Licença

Consulte o arquivo de licença do repositório para obter os termos aplicáveis.
