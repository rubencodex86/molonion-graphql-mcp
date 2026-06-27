# MCP Moloni ON

Servidor [MCP](https://modelcontextprotocol.io) que expõe a API **GraphQL da
[Moloni ON](https://docs.molonion.pt/reference)** a clientes de IA como o
**Claude Code** e o **Claude Desktop**.

A API é grande (**497 queries**, **464 mutations**); este servidor expõe um
subconjunto **curado** de operações, adicionadas uma a uma. Cada operação GraphQL
vira uma **tool** dedicada, tipada e documentada.

> **Versão atual:** `0.32.0` — desenvolvimento inicial (ver [Versionamento](#versionamento)).

## Requisitos

- Python 3.12 (ver [.python-version](.python-version)); o projeto usa `pyenv` + `venv`, **não** `uv`.
- Uma conta Moloni ON com acesso à API e uma **API Key** gerada.

## Instalação

```bash
pyenv local 3.12.1
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuração

```bash
cp .env.example .env
```

Edita o `.env`:

```ini
MOLONION_API_URL=https://api.molonion.pt/v1
MOLONION_API_KEY=a-tua-api-key
# MOLONION_COMPANY_ID=   # opcional, empresa por omissão
```

> ⚠️ O `.env` contém segredos e está no `.gitignore` — nunca o commites.

### Autenticação

A API Moloni ON usa **Bearer token** no header `Authorization`. Este servidor usa
uma **API Key de serviço** (integração máquina-a-máquina, sem browser):

1. Na Moloni ON, vai a **Conta → API → separador "API Keys"** e gera uma key.
2. Cola-a no `.env` em `MOLONION_API_KEY`.
3. O servidor envia-a em cada chamada como `Authorization: Bearer <key>`.

A key é **permanente** (com expiração opcional) — não há renovação de token. Para
confirmar que está tudo bem, chama a tool `me` (devolve o utilizador e as empresas).

> **Nota sobre erros:** todas as operações devolvem `{ errors, data }`. Os erros de
> negócio vêm com **HTTP 200**, no array `errors` — o servidor já os deteta e devolve
> de forma legível.

## Testar (MCP Inspector)

Este projeto usa `pyenv` + `venv`, por isso **não** uses `mcp dev` (arranca com `uv`,
que não está instalado). Lança o Inspector apontando ao Python do venv:

```bash
npx @modelcontextprotocol/inspector .venv/bin/python server.py
```

Abre o link → **Connect** → **Tools** → **List Tools** e experimenta (começa pelo `me`).

## Usar no Claude Code

A partir do projeto onde queres usar o MCP:

```bash
claude mcp add molonion -- /CAMINHO/ABSOLUTO/.venv/bin/python /CAMINHO/ABSOLUTO/server.py
```

O Claude Code arranca o servidor sozinho em cada sessão. Verifica com `claude mcp list`
ou `/mcp`. Depois de alterares o `server.py`, reconecta (`/mcp` → reconnect).

## Tools disponíveis

| Tool | Descrição |
|------|-----------|
| `health` | Confirma que o servidor está vivo e mostra a config (sem expor a key). |
| `me` | Valida as credenciais; devolve `userId` e as empresas (`companyId`, `name`). |
| `list_companies` | Lista as empresas acessíveis ao utilizador (id, nome, NIF, contactos). |
| `get_company` | Detalhes de uma empresa pelo seu ID (identificação, fiscal, banca, contagens). |
| `get_company_logs` | Histórico de alterações (logs) às definições/dados de empresa. |
| `get_company_role` | Perfil de permissões (role) de uma empresa, com a lista de permissões. |
| `get_company_role_logs` | Histórico de alterações (logs) aos perfis de permissões de uma empresa. |
| `list_company_roles` | Lista os perfis de permissões (roles) configurados numa empresa. |
| `get_at_settings` | Definições de comunicação com a Autoridade Tributária (AT) de uma empresa. |
| `check_at_settings_errors` | Valida a configuração AT e indica erros a corrigir no envio automático. |
| `check_at_user` | Verifica se um utilizador AT existe para as credenciais do Portal das Finanças. |
| `get_banking_info` | Detalhes de um dado bancário (IBAN, SWIFT, banco) de uma empresa. |
| `get_banking_info_logs` | Histórico de alterações (logs) aos dados bancários de uma empresa. |
| `list_banking_infos` | Lista os dados bancários configurados de uma empresa (com paginação). |
| `get_bank_remittance` | Detalhes de uma remessa bancária (SEPA) pelo seu ID. |
| `get_bank_remittance_logs` | Histórico de alterações (logs) às remessas bancárias de uma empresa. |
| `list_bank_remittances` | Lista as remessas bancárias (SEPA) de uma empresa (com paginação). |
| `get_bill_of_lading` | Detalhes de uma guia de transporte (documento) pelo seu ID. |
| `get_bill_of_lading_pdf_token` | Token temporário para descarregar o PDF de uma guia de transporte. |
| `get_bills_of_lading_zip_token` | Token temporário para descarregar várias guias de transporte em ZIP. |
| `get_bills_of_lading_logs` | Histórico de alterações (logs) às guias de transporte de uma empresa. |
| `get_bills_of_lading_mail_recipients` | Destinatários e estado de entrega de um envio por email de guias de transporte. |
| `get_bills_of_lading_mails_history` | Histórico de emails enviados de uma guia de transporte. |
| `get_bills_of_lading_next_number` | Próximo número disponível para uma guia de transporte numa série. |
| `get_bills_of_lading_relatable` | Guias de transporte de uma entidade que podem ser relacionadas a outro documento. ⚠️ deprecated (usar `documentRelatable`). |
| `list_bills_of_lading` | Lista (paginada) as guias de transporte de uma empresa. |
| `get_bulk_customer` | Vista consolidada de vários clientes em simultâneo (campos comuns). |
| `get_bulk_product` | Vista consolidada de vários produtos em simultâneo (campos comuns). |
| `get_bulk_supplier` | Vista consolidada de vários fornecedores em simultâneo (campos comuns). |
| `list_company_subscriptions` | Lista as subscrições de uma empresa (plano, preço, vigência, estado de pagamento). |
| `get_company_user` | Perfil de um utilizador numa empresa (identificação, `roleId`, ligação utilizador↔empresa). |
| `get_company_user_logs` | Histórico de alterações (logs) aos utilizadores de uma empresa. |
| `list_company_users` | Lista os utilizadores de uma empresa (identificação + `roleId` de cada um). |

As restantes operações são adicionadas à medida que avançamos pelos links de
[docs.molonion.pt/reference](https://docs.molonion.pt/reference).

## Adicionar mais operações

Cada tool é uma função `async` decorada com `@mcp.tool()`. O padrão completo (como
mapear *inputs*/*objects* interligados, o envelope `{errors, data}`, nomes em inglês +
docstrings em português) está documentado no [CLAUDE.md](CLAUDE.md).

## Versionamento

Usa-se [Semantic Versioning](https://semver.org/lang/pt-BR/) — `MAJOR.MINOR.PATCH`:

- **MAJOR** — mudanças incompatíveis (breaking) na interface das tools.
- **MINOR** — novas tools/funcionalidades retrocompatíveis.
- **PATCH** — correções de bugs retrocompatíveis.

O projeto está em **`0.x`** (desenvolvimento inicial): a API ainda não é estável e
pode mudar a qualquer momento. Cada operação nova → bump **MINOR**.

## Stack

Python 3.12 · FastMCP (`mcp[cli]`) · httpx · python-dotenv · transport stdio.