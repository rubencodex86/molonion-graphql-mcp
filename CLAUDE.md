# CLAUDE.md — Servidor MCP da Moloni ON

Guia para qualquer sessão do Claude Code que trabalhe neste projeto. Lê isto antes
de mexer no código.

## O que é

Servidor [MCP](https://modelcontextprotocol.io) que expõe a API **GraphQL da
Moloni ON** ([docs](https://docs.molonion.pt/reference)) a clientes de IA (Claude
Code / Desktop). Cada operação GraphQL relevante vira uma **tool curada**.

A API é grande: **497 queries, 464 mutations, 1027 objects, 684 inputs, 312 enums**.
Não a expomos toda — curamos operação a operação, à medida que o utilizador as pede.

## Stack

- **Python 3.12** (ver `.python-version`) com **`pyenv` + `venv`** — **NÃO** `uv`.
- [`FastMCP`](https://modelcontextprotocol.io) (pacote `mcp[cli]`) para o servidor.
- [`httpx`](https://www.python-httpx.org/) para o POST GraphQL (não é preciso lib GraphQL).
- `python-dotenv` para a config.
- Transport **stdio** (`mcp.run()`).

Porquê Python e não TypeScript: mantém consistência com o MCP irmão `officegest`, e
como escrevemos cada *selection set* à mão, perde-se a maior vantagem do TS (codegen
de tipos a partir do schema). GraphQL aqui é só um POST `{query, variables}`.

## Ficheiros

| Ficheiro | Papel |
|----------|-------|
| `server.py` | Servidor FastMCP. Uma função `@mcp.tool()` por operação. |
| `molonion_client.py` | Cliente httpx (`MolonionClient`), erros (`MolonionError`) e `unwrap()` do envelope. |
| `.env` | Segredos (no `.gitignore`). Copiar de `.env.example`. |
| `requirements.txt` | `mcp[cli]`, `httpx`, `python-dotenv`. |

## Autenticação

- Endpoint único: `POST https://api.molonion.pt/v1`.
- Headers: `Content-Type: application/json` + `Authorization: Bearer <API_KEY>`.
- Este MCP usa **uma API Key de serviço** (máquina-a-máquina): na Moloni ON, em
  **Conta → API → separador API Keys**. Vai no `.env` como `MOLONION_API_KEY`.
- A query `me` valida a key e devolve `userId` + `userCompanies { companyId name }`.
- **Nota:** a app do utilizador (futura) vai usar **credencial por utilizador**
  (OAuth ou key-por-user) para auditoria — isso é outro projeto, não este MCP.

## ⚠️ Convenção crítica: o envelope `{ errors, data }`

**Todas** as operações Moloni ON devolvem `{ errors { field msg }, data { ... } }`.
Os erros ao nível da operação vêm com **HTTP 200**, no array `errors` — não no status.

Por isso:
- O `MolonionClient.query()` trata HTTP e erros GraphQL de topo.
- O `unwrap(data, "<operation>")` trata o envelope da operação e devolve o `data` interno.
- Toda a tool deve incluir `errors { field msg }` no *selection set*.

## Padrão para adicionar uma tool (uma por operação)

O utilizador passa um link, ex. `https://docs.molonion.pt/reference/queries/billsOfLading`.
Passos:

1. **Lê o link** (e os tipos ligados: o *input* `...OptionsSingle`/`...OptionsMany` e os
   *objects* devolvidos). Decide:
   - que campos do *input* expor como **parâmetros da tool** (só os úteis);
   - que campos pedir no *selection set* (evita payloads gigantes; nunca esquecer `errors`).
2. **Escreve a query** como constante no topo da secção da tool.
3. **Escreve a tool**: função `async`, nome em **inglês** (`get_bills_of_lading`),
   docstring rica em **português** (é o que o modelo lê para decidir usar a tool).
4. **Desembrulha** com `unwrap(data, "<operation>")` e captura `MolonionError` com `_err(e)`.

Template:

```python
BILLS_OF_LADING = """
query ($options: BillsOfLadingOptionsSingle) {
  billsOfLading(options: $options) {
    errors { field msg }
    data { id number date entity { id name } }
  }
}
"""

@mcp.tool()
async def get_bills_of_lading(company_id: int, document_id: int) -> Any:
    """Obtém uma guia de transporte pelo seu ID. ..."""
    options = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(BILLS_OF_LADING, {"options": options})
        return unwrap(data, "billsOfLading")
    except MolonionError as e:
        return _err(e)
```

## Padrão para mutations (escrita)

As mutations (`/reference/mutations/...`) seguem o **mesmo** padrão (envelope
`{errors, data}`, `unwrap`, `_err`), com estas diferenças:

- **Nome em inglês com verbo**: `create_*`, `update_*`, `delete_*`, `apply_*`, etc.
- **Input maior**: a mutation leva um `input`/`data` de tipo `XxxInput`/`XxxApply`.
  Expõe como **parâmetros** os campos **obrigatórios** + os úteis; constrói o dict do
  input só com os parâmetros não-nulos (não envies chaves a `None`).
- **Avisa no docstring** quando a operação é **destrutiva/irreversível** (apagar,
  anular, comunicar à AT) ou **altera dados em massa** — começa a linha com `⚠️`.
- Algumas mutations são **assíncronas**: devolvem `progressiveTaskId` (tarefa em
  segundo plano) em vez do resultado final.

Template:

```python
APPLY_PRICE_CLASS_MUTATION = """
mutation ($companyId: Int!, $priceClassId: Int!, $percentage: Float!, $data: PriceClassApply!) {
  applyPriceClass(companyId: $companyId, priceClassId: $priceClassId, percentage: $percentage, data: $data) {
    errors { field msg }
    data { progressiveTaskId }
  }
}
"""

@mcp.tool()
async def apply_price_class(company_id: int, price_class_id: int, percentage: float,
                            product_ids: list[int] | None = None) -> Any:
    """⚠️ Aplica uma classe de preço (altera preços em massa). ..."""
    data: dict[str, Any] = {}
    if product_ids is not None:
        data["productIds"] = product_ids
    variables = {"companyId": company_id, "priceClassId": price_class_id,
                 "percentage": percentage, "data": data}
    try:
        result = await _client.query(APPLY_PRICE_CLASS_MUTATION, variables)
        return unwrap(result, "applyPriceClass")
    except MolonionError as e:
        return _err(e)
```

## Convenções

- **Nomes de tools em inglês**; **docstrings, README e CLAUDE.md em português**.
- Uma tool = uma operação GraphQL. Sem `run_graphql` genérico.
- Não fazer crawl autónomo dos docs — implementa só o link que o utilizador der.
- Manter `README.md` e a memória do Claude atualizados quando surgem descobertas.

## Versionamento (SemVer — semver.org)

`MAJOR.MINOR.PATCH`:
- **MAJOR** — mudanças incompatíveis (breaking) na interface das tools.
- **MINOR** — novas tools/funcionalidades retrocompatíveis (ex. expor nova operação).
- **PATCH** — correções retrocompatíveis.

Estamos em **`0.x`** (desenvolvimento inicial — a API das tools pode mudar a qualquer
momento). Adicionar uma operação nova → bump **MINOR** (`0.1.0` → `0.2.0`). Corrigir
uma tool → bump **PATCH**.

## Correr e testar

```bash
# Setup
pyenv local 3.12.1 && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # e preencher MOLONION_API_KEY

# Inspector (este projeto usa venv, NÃO `mcp dev` que precisa de uv)
npx @modelcontextprotocol/inspector .venv/bin/python server.py

# Usar no Claude Code
claude mcp add molonion -- /CAMINHO/ABSOLUTO/.venv/bin/python /CAMINHO/ABSOLUTO/server.py
```

Depois de alterar `server.py`, reconecta o servidor (`/mcp` → reconnect) para recarregar.