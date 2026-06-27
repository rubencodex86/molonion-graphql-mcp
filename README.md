# MCP Moloni ON

Servidor [MCP](https://modelcontextprotocol.io) que expõe a API **GraphQL da
[Moloni ON](https://docs.molonion.pt/reference)** a clientes de IA como o
**Claude Code** e o **Claude Desktop**.

A API é grande (**497 queries**, **464 mutations**); este servidor expõe um
subconjunto **curado** de operações, adicionadas uma a uma. Cada operação GraphQL
vira uma **tool** dedicada, tipada e documentada.

> **Versão atual:** `0.192.0` — desenvolvimento inicial (ver [Versionamento](#versionamento)).

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
| `get_country` | Detalhes de um país pelo seu ID (ISO 3166-1, nome, VIES, bandeira). |
| `list_countries` | Lista os países (tabela de referência: `countryId`, ISO 3166-1, nome, VIES). |
| `get_credit_note` | Detalhes de uma nota de crédito pelo seu ID (documento, entidade, reconciliação). |
| `get_credit_note_pdf_token` | Token temporário para descarregar o PDF de uma nota de crédito. |
| `get_credit_note_zip_token` | Token temporário para descarregar várias notas de crédito em ZIP. |
| `get_credit_note_logs` | Histórico de alterações (logs) às notas de crédito de uma empresa. |
| `get_credit_note_mail_recipients` | Destinatários e estado de entrega de um envio por email de notas de crédito. |
| `get_credit_note_mails_history` | Histórico de emails enviados de uma nota de crédito. |
| `get_credit_note_next_number` | Próximo número disponível para uma nota de crédito numa série. |
| `get_credit_note_relatable` | Notas de crédito de uma entidade relacionáveis a outro documento. ⚠️ deprecated (usar `documentRelatable`). |
| `list_credit_notes` | Lista (paginada) as notas de crédito de uma empresa. |
| `get_currency` | Detalhes de uma moeda pelo seu ID (ISO 4217, símbolo, casas decimais). |
| `list_currencies` | Lista as moedas (tabela de referência: `currencyId`, ISO 4217, símbolo, decimais). |
| `get_currency_denominations` | Lista as denominações (notas/moedas) de uma moeda (tipo, valor, imagem). |
| `get_currency_exchange` | Taxa de câmbio entre duas moedas pelo seu ID (par, taxa, moedas from/to). |
| `list_currency_exchanges` | Lista as taxas de câmbio configuradas (par, taxa, moedas from/to). |
| `get_customer` | Detalhes de um cliente pelo seu ID (identificação, financeiro, IDs associados). |
| `list_customers` | Lista (paginada) os clientes de uma empresa (identificação, contactos, saldo). |
| `get_custom_field` | Detalhes de um campo personalizado pelo seu ID (nome, tipo, obrigatório, opções). |
| `get_custom_field_logs` | Histórico de alterações (logs) aos campos personalizados de uma empresa. |
| `list_custom_fields` | Lista os campos personalizados configurados numa empresa. |
| `get_debit_note` | Detalhes de uma nota de débito pelo seu ID (documento, entidade, reconciliação, vencimento). |
| `get_debit_note_pdf_token` | Token temporário para descarregar o PDF de uma nota de débito. |
| `get_debit_note_zip_token` | Token temporário para descarregar várias notas de débito em ZIP. |
| `get_debit_note_logs` | Histórico de alterações (logs) às notas de débito de uma empresa. |
| `get_debit_note_mail_recipients` | Destinatários e estado de entrega de um envio por email de notas de débito. |
| `get_debit_note_mails_history` | Histórico de emails enviados de uma nota de débito. |
| `get_debit_note_next_number` | Próximo número disponível para uma nota de débito numa série. |
| `get_debit_note_relatable` | Notas de débito de uma entidade relacionáveis a outro documento. ⚠️ deprecated (usar `documentRelatable`). |
| `list_debit_notes` | Lista (paginada) as notas de débito de uma empresa. |
| `get_delivery_method` | Detalhes de um método de entrega pelo seu ID (nome, default, visível). |
| `get_delivery_method_logs` | Histórico de alterações (logs) aos métodos de entrega de uma empresa. |
| `list_delivery_methods` | Lista os métodos de entrega configurados numa empresa. |
| `get_delivery_note` | Detalhes de uma guia de remessa pelo seu ID (documento, entidade, reconciliação, vencimento, transporte). |
| `get_delivery_note_pdf_token` | Token temporário para descarregar o PDF de uma guia de remessa. |
| `get_delivery_note_zip_token` | Token temporário para descarregar várias guias de remessa em ZIP. |
| `get_delivery_note_logs` | Histórico de alterações (logs) às guias de remessa de uma empresa. |
| `get_delivery_note_mail_recipients` | Destinatários e estado de entrega de um envio por email de guias de remessa. |
| `get_delivery_note_mails_history` | Histórico de emails enviados de uma guia de remessa. |
| `get_delivery_note_next_number` | Próximo número disponível para uma guia de remessa numa série. |
| `get_delivery_note_relatable` | Guias de remessa de uma entidade relacionáveis a outro documento. ⚠️ deprecated (usar `documentRelatable`). |
| `list_delivery_notes` | Lista (paginada) as guias de remessa de uma empresa. |
| `get_document` | Documento genérico pelo seu ID (campos comuns a qualquer tipo + `__typename`). |
| `list_document_at_communication_statuses` | Estado da comunicação de documentos com a AT (diagnóstico de envios). |
| `get_document_events` | Eventos associados a um documento (lembretes, tarefas, recorrência). |
| `get_document_link` | Link público partilhável de documento pelo seu ID (expiração, ficheiro, token). |
| `get_document_mail_message_template` | Modelo de mensagem de email para documentos pelo seu ID (nome, conteúdo). |
| `get_document_mail_message_template_logs` | Histórico de alterações (logs) aos modelos de mensagem de email para documentos. |
| `list_document_mail_message_templates` | Lista os modelos de mensagem de email para documentos configurados numa empresa. |
| `get_document_next_number` | Próximo número de documento (genérico, por `apiCode`) numa série. |
| `get_document_print_model` | Modelo de impressão de documento pelo seu ID (template HTML, CSS, título). |
| `get_document_print_model_logs` | Histórico de alterações (logs) aos modelos de impressão de documento. |
| `list_document_print_models` | Lista os modelos de impressão de documento (sem template/css). |
| `get_document_relatable` | Documentos de uma entidade relacionáveis a outro documento (genérico, por `apiCode`). ✅ recomendado. |
| `list_documents` | Lista (paginada) os documentos de uma empresa, de qualquer tipo (+ `__typename`). |
| `get_document_set` | Detalhes de uma série de documentos pelo seu ID (nome, default, visível). |
| `validate_document_set_at_codes_available` | Valida se códigos AT de série estão disponíveis (`code`, `isAvailable`). |
| `validate_document_set_at_code` | Valida um código AT de série para um tipo de documento (booleano). |
| `get_document_set_at_status` | Estado da comunicação de uma série de documentos com a AT pelo seu ID. |
| `list_document_set_at_statuses` | Histórico de estados da comunicação de séries de documentos com a AT. |
| `get_document_set_at_status_logs` | Histórico de alterações (logs) aos estados AT de séries de documentos. |
| `get_document_set_logs` | Histórico de alterações (logs) às séries de documentos de uma empresa. |
| `list_document_sets` | Lista as séries de documentos configuradas numa empresa. |
| `list_document_sets_for_document` | Séries de numeração disponíveis para um tipo de documento. |
| `list_document_sets_for_documents` | Séries de numeração para vários tipos de documento de uma vez (agrupadas por tipo). |
| `get_documents_logs` | Histórico de alterações (logs) aos documentos de uma empresa (genérico). |
| `get_document_type` | Detalhes de um tipo de documento pelo seu ID (apiCode, SAF-T, regras). |
| `list_document_types` | Lista os tipos de documento (tabela de referência: apiCode, SAF-T, título). |
| `get_economic_activity_classification_code` | Detalhes de um código CAE pelo seu ID (código, descrição, default). |
| `get_economic_activity_classification_code_logs` | Histórico de alterações (logs) aos códigos CAE de uma empresa. |
| `list_economic_activity_classification_codes` | Lista os códigos CAE configurados numa empresa. |
| `get_estimate` | Detalhes de um orçamento pelo seu ID (documento, entidade, validade, transporte). |
| `get_estimate_pdf_token` | Token temporário para descarregar o PDF de um orçamento. |
| `get_estimate_zip_token` | Token temporário para descarregar vários orçamentos em ZIP. |
| `get_estimate_logs` | Histórico de alterações (logs) aos orçamentos de uma empresa. |
| `get_estimate_mail_recipients` | Destinatários e estado de entrega de um envio por email de orçamentos. |
| `get_estimate_mails_history` | Histórico de emails enviados de um orçamento. |
| `get_estimate_next_number` | Próximo número disponível para um orçamento numa série. |
| `get_estimate_relatable` | Orçamentos de uma entidade relacionáveis a outro documento. ⚠️ deprecated (usar `documentRelatable`). |
| `list_estimates` | Lista (paginada) os orçamentos de uma empresa. |
| `get_event` | Detalhes de um evento pelo seu ID (nome, data, documento, recorrência). |
| `get_event_logs` | Histórico de alterações (logs) aos eventos de uma empresa. |
| `list_events` | Lista os eventos de uma empresa (lembretes, tarefas, recorrência). |
| `list_events_by_date` | Lista os eventos de uma empresa numa data específica (agenda). |
| `list_events_month_by_date` | Lista os eventos de uma empresa no mês da data indicada (vista mensal). |
| `list_fiscal_zones_tax_settings` | Definições de impostos por zona fiscal (regras de faturação por zona). |
| `get_fiscal_zone_tax_settings` | Definições de impostos de uma zona fiscal específica (sem envelope). |
| `get_geographic_zone` | Detalhes de uma zona geográfica pelo seu ID (nome, abreviatura, notas). |
| `get_geographic_zone_logs` | Histórico de alterações (logs) às zonas geográficas de uma empresa. |
| `list_geographic_zones` | Lista as zonas geográficas configuradas numa empresa. |
| `get_at_inventory_file_token` | Token temporário para descarregar o ficheiro XML de inventário para a AT. |
| `get_company_by_slug` | Empresa pelo seu `slug` (em vez do ID) — identificação/contacto. |
| `get_customer_gdpr_file_token` | Token temporário para descarregar o ficheiro RGPD de um cliente. |
| `list_customer_related_documents` | Documentos associados a um cliente (número, data, total, reconciliação, estado). |
| `get_document_attachment_token` | Token temporário para descarregar o anexo de um documento. |
| `get_edi_xml_token` | Token temporário para descarregar o ficheiro XML de EDI de um documento. |
| `get_family` | Família da taxonomia de um canal/marketplace (id, título, canal). |
| `get_import_sheet_errors_token` | Token temporário para descarregar o ficheiro de erros de uma folha de importação. |
| `get_import_sheet_warnings_token` | Token temporário para descarregar o ficheiro de avisos de uma folha de importação. |
| `get_import_token` | Token temporário para descarregar o ficheiro importado de um trabalho de importação. |
| `get_pdf_token` | Token temporário para descarregar um ficheiro PDF (genérico). |
| `list_possible_documents` | Documentos elegíveis para uma remessa bancária (SEPA), por categoria. |
| `get_saft_importer_errors_file_token` | Token temporário para descarregar o ficheiro de erros de uma importação SAF-T. |
| `get_saft_importer_warnings_file_token` | Token temporário para descarregar o ficheiro de avisos de uma importação SAF-T. |
| `get_saft_import_token` | Token temporário para descarregar o ficheiro SAF-T importado. |
| `get_saft_xml_token` | Token temporário para descarregar o ficheiro XML SAF-T(PT) de uma empresa. |
| `list_salesperson_related_documents` | Documentos associados a um vendedor (com comissão). |
| `list_supplier_related_documents` | Documentos associados a um fornecedor (número, data, total, estado). |
| `get_xlsx_token` | Token temporário para descarregar um ficheiro XLSX (Excel). |
| `get_xml_token` | Token temporário para descarregar um ficheiro XML (genérico). |
| `get_hook` | Detalhes de um webhook pelo seu ID (nome, URL, gatilhos: modelo/operação). |
| `get_hook_logs` | Histórico de alterações (logs) aos webhooks de uma empresa. |
| `list_hook_model_operations` | Catálogo de gatilhos disponíveis para webhooks (modelo/operação). |
| `list_hooks` | Lista os webhooks configurados numa empresa (nome, URL, gatilhos). |
| `get_identification_template` | Detalhes de um template de identificação pelo seu ID (dados alternativos de documento). |
| `get_identification_template_logs` | Histórico de alterações (logs) aos templates de identificação. |
| `list_identification_templates` | Lista os templates de identificação configurados numa empresa. |
| `get_invoice` | Detalhes de uma fatura pelo seu ID (documento, entidade, reconciliação, vencimento, transporte). |
| `get_invoice_pdf_token` | Token temporário para descarregar o PDF de uma fatura. |
| `get_invoice_zip_token` | Token temporário para descarregar várias faturas em ZIP. |
| `get_invoice_logs` | Histórico de alterações (logs) às faturas de uma empresa. |
| `get_invoice_mail_recipients` | Destinatários e estado de entrega de um envio por email de faturas. |
| `get_invoice_mails_history` | Histórico de emails enviados de uma fatura. |
| `get_invoice_next_number` | Próximo número disponível para uma fatura numa série. |
| `get_invoice_relatable` | Faturas de uma entidade relacionáveis a outro documento. ⚠️ deprecated (usar `documentRelatable`). |
| `list_invoices` | Lista (paginada) as faturas de uma empresa. |
| `check_is_allowed` | Verifica se uma ação sobre um recurso é permitida (controlo de acesso + quotas). |
| `get_label_template` | Detalhes de um template de etiquetas pelo seu ID (nome, tamanho, default). |
| `get_label_template_logs` | Histórico de alterações (logs) aos templates de etiquetas. |
| `list_label_templates` | Lista os templates de etiquetas configurados numa empresa. |
| `get_language` | Detalhes de um idioma pelo seu ID (nome, ISO 3166, bandeira). |
| `list_languages` | Lista os idiomas (tabela de referência: `languageId`, nome, ISO 3166). |
| `list_products_stock_movements` | Produtos com dados de stock e indicação de movimentos. ⚠️ deprecated (usar `stockProducts`). |
| `list_products_stock_totals` | Totais de stock dos produtos (custo total, valor de venda). |
| `get_maturity_date` | Detalhes de uma data de vencimento pelo seu ID (nome, dias, desconto). |
| `get_maturity_date_logs` | Histórico de alterações (logs) às datas de vencimento de uma empresa. |
| `list_maturity_dates` | Lista as datas de vencimento configuradas numa empresa. |
| `get_invoice_receipt` | Detalhes de uma fatura-recibo pelo seu ID (documento, entidade, reconciliação, pagamento). |
| `get_invoice_receipt_pdf_token` | Token temporário para descarregar o PDF de uma fatura-recibo. |
| `get_invoice_receipt_zip_token` | Token temporário para descarregar várias faturas-recibo em ZIP. |
| `get_invoice_receipt_logs` | Histórico de alterações (logs) às faturas-recibo de uma empresa. |
| `get_invoice_receipt_mail_recipients` | Destinatários e estado de entrega de um envio por email de faturas-recibo. |
| `get_invoice_receipt_mails_history` | Histórico de emails enviados de uma fatura-recibo. |
| `get_invoice_receipt_next_number` | Próximo número disponível para uma fatura-recibo numa série. |
| `get_invoice_receipt_relatable` | Faturas-recibo de uma entidade relacionáveis a outro documento. ⚠️ deprecated (usar `documentRelatable`). |
| `list_invoice_receipts` | Lista (paginada) as faturas-recibo de uma empresa. |
| `list_customer_history` | Resumo de conta-corrente por cliente (documentos, débito/crédito, saldos). |
| `get_customer_history_customer` | Extrato (conta-corrente) de um cliente: documentos que movimentam a conta + saldo. |
| `list_customer_history_templates` | Modelos de definições do utilizador para o ecrã de conta-corrente de clientes. |
| `get_customer_logs` | Histórico de alterações (logs) aos clientes de uma empresa. |
| `get_customer_next_number` | Próximo número de cliente disponível numa empresa. |
| `get_customer_return_note` | Detalhes de uma nota de devolução de cliente (documento, entidade, reconciliação, transporte). |
| `get_customer_return_note_pdf_token` | Token temporário para descarregar o PDF de uma nota de devolução de cliente. |
| `get_customer_return_note_zip_token` | Token temporário para descarregar várias notas de devolução de cliente em ZIP. |
| `get_customer_return_note_logs` | Histórico de alterações (logs) às notas de devolução de cliente. |
| `get_customer_return_note_mail_recipients` | Destinatários e estado de entrega de um envio por email de notas de devolução de cliente. |
| `get_customer_return_note_mails_history` | Histórico de emails enviados de uma nota de devolução de cliente. |
| `get_customer_return_note_next_number` | Próximo número disponível para uma nota de devolução de cliente numa série. |
| `get_customer_return_note_relatable` | Notas de devolução de cliente de uma entidade relacionáveis a outro documento. ⚠️ deprecated (usar `documentRelatable`). |
| `list_customer_return_notes` | Lista (paginada) as notas de devolução de cliente de uma empresa. |

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