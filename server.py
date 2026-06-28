"""Servidor MCP da Moloni ON (transport stdio).

Arranca com:  python server.py

Expõe a API GraphQL da Moloni ON (https://docs.molonion.pt/reference) como tools
MCP. Cada operação GraphQL é uma tool curada, tipada e documentada. As tools são
adicionadas operação a operação — ver CLAUDE.md.
"""

from __future__ import annotations

from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from molonion_client import MolonionClient, MolonionError, unwrap

load_dotenv()

mcp = FastMCP("molonion")

# Cliente partilhado (lazy: só liga quando uma tool é chamada).
_client = MolonionClient()


def _err(e: MolonionError) -> dict[str, Any]:
    """Converte um erro num resultado que o modelo consegue ler."""
    return {
        "error": True,
        "status_code": e.status_code,
        "errors": e.errors,
        "detail": e.message,
    }


# ---------------------------------------------------------------------------
# Saúde / diagnóstico
# ---------------------------------------------------------------------------
@mcp.tool()
def health() -> dict[str, Any]:
    """Verifica que o servidor MCP está vivo e mostra a config (sem expor a key)."""
    return {
        "ok": True,
        "api_url": _client.url,
        "api_key_configured": bool(_client.api_key),
    }


# ---------------------------------------------------------------------------
# Autenticação / contexto
# ---------------------------------------------------------------------------
COMPANY_QUERY = """
query ($companyId: Int!) {
  company(companyId: $companyId) {
    errors { field msg }
    data {
      companyId
      name
      slug
      vat
      email
      address
      city
      zipCode
      phone
      fax
      website
      countryId
      isConfirmed
      visible
      createdAt
      capital
      commercialRegistryNumber
      commercialRegistryOffice
      decimalSeparator
      thousandsSeparator
      numDecimalPlacesDocs
      swift
      iban
      sepaId
      notes
      documentFooter
      emailSenderName
      emailSenderAddress
      emailSenderValidated
      documentsCnt
      customersCnt
      suppliersCnt
      productsCnt
    }
  }
}
"""


@mcp.tool()
async def get_company(company_id: int) -> Any:
    """Obtém os detalhes de uma empresa pelo seu ID: identificação (nome, NIF, morada,
    contactos), dados fiscais/de formato (separadores, casas decimais, registo
    comercial), dados bancários (`swift`/`iban`/`sepaId`), remetente de email e contagens
    de entidades (documentos, clientes, fornecedores, produtos). O objeto completo da
    empresa tem ~140 campos; este selection set expõe um subconjunto prático e omite os
    objetos ligados (país, subscrição, etc.).

    Args:
        company_id: ID da empresa (obtém-se via `me` ou `list_companies`).
    """
    try:
        data = await _client.query(COMPANY_QUERY, {"companyId": company_id})
        return unwrap(data, "company")
    except MolonionError as e:
        return _err(e)


COMPANIES_QUERY = """
query ($options: CompanyOptions) {
  companies(options: $options) {
    errors { field msg }
    data {
      companyId
      name
      slug
      vat
      email
      address
      city
      zipCode
      phone
      website
      isConfirmed
      visible
      countryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def list_companies(page: int | None = None, qty: int | None = None) -> Any:
    """Lista as empresas acessíveis ao utilizador autenticado, com os campos principais
    de cada uma (id, nome, NIF, contactos). Ao contrário da maioria das operações, não
    recebe `companyId`. Para apenas os pares `companyId`/`name` do utilizador, `me` é
    mais leve; usa esta para obter detalhes de cada empresa.

    Args:
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(COMPANIES_QUERY, variables)
        return unwrap(data, "companies")
    except MolonionError as e:
        return _err(e)


ME_QUERY = """
query {
  me {
    errors { field msg }
    data {
      userId
      userCompanies { companyId name }
    }
  }
}
"""


@mcp.tool()
async def me() -> Any:
    """Valida as credenciais e devolve o utilizador autenticado e as empresas a que
    tem acesso. Usa isto primeiro para confirmar que a API Key está bem configurada
    e para obter os `companyId` necessários noutras operações."""
    try:
        data = await _client.query(ME_QUERY)
        return unwrap(data, "me")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Autoridade Tributária (AT)
# ---------------------------------------------------------------------------
AT_SETTINGS_QUERY = """
query ($companyId: Int!) {
  ATSettings(companyId: $companyId) {
    errors { field msg }
    data {
      companyATId
      companyId
      automaticInvoice
      automaticTransport
      automaticDocSets
      automaticInvoiceChangedAt
      automaticTransportChangedAt
      automaticDocSetsChangedAt
      automaticInvoiceDelay
      userId
      passwordSet
      createdAt
      updatedAt
    }
  }
}
"""


CHECK_AT_USER_QUERY = """
query ($username: String!, $password: String!, $userId: String!) {
  checkATUser(username: $username, password: $password, userId: $userId) {
    errors { field msg }
    data {
      exists
      loginError
    }
  }
}
"""


@mcp.tool()
async def check_at_user(username: str, password: str, user_id: str) -> Any:
    """Verifica se um utilizador da Autoridade Tributária (AT) existe para as credenciais
    do Portal das Finanças fornecidas. Devolve `exists` (se as credenciais são válidas e
    o sub-utilizador existe) e `loginError` (eventuais erros de autenticação na AT). Ao
    contrário da maioria das operações, não recebe `companyId`.

    Nota: recebe a password do utilizador AT — usa apenas com credenciais autorizadas.

    Args:
        username: utilizador (NIF/sub-utilizador) do Portal das Finanças.
        password: password do utilizador AT.
        user_id: identificador do sub-utilizador AT a verificar.
    """
    variables = {"username": username, "password": password, "userId": user_id}
    try:
        data = await _client.query(CHECK_AT_USER_QUERY, variables)
        return unwrap(data, "checkATUser")
    except MolonionError as e:
        return _err(e)


CHECK_AT_SETTINGS_ERRORS_QUERY = """
query ($companyId: Int!, $forceRefresh: Boolean) {
  checkATSettingsErrors(companyId: $companyId, forceRefresh: $forceRefresh) {
    errors { field msg }
    data {
      automaticInvoiceErrors
      automaticTransportErrors
      automaticDocSetsErrors
      nextAllowedCheck
    }
  }
}
"""


@mcp.tool()
async def check_at_settings_errors(
    company_id: int, force_refresh: bool | None = None
) -> Any:
    """Valida a configuração de comunicação com a Autoridade Tributária (AT) de uma
    empresa e indica se há erros que exigem correção no envio automático de faturas
    (`automaticInvoiceErrors`), guias de transporte (`automaticTransportErrors`) e
    conjuntos de documentos (`automaticDocSetsErrors`). `nextAllowedCheck` indica quando
    é permitida nova verificação (a validação é limitada por frequência).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        force_refresh: opcional; força nova verificação em vez de usar o resultado em
            cache (sujeito a `nextAllowedCheck`).
    """
    variables: dict[str, Any] = {"companyId": company_id}
    if force_refresh is not None:
        variables["forceRefresh"] = force_refresh
    try:
        data = await _client.query(CHECK_AT_SETTINGS_ERRORS_QUERY, variables)
        return unwrap(data, "checkATSettingsErrors")
    except MolonionError as e:
        return _err(e)


@mcp.tool()
async def get_at_settings(company_id: int) -> Any:
    """Obtém as definições de comunicação com a Autoridade Tributária (AT) de uma
    empresa. Indica se o envio automático para a AT está ativo para faturas
    (`automaticInvoice`), guias de transporte (`automaticTransport`) e conjuntos de
    documentos (`automaticDocSets`), o atraso configurado no envio automático de
    faturas (`automaticInvoiceDelay`, em segundos), se já há password da AT definida
    (`passwordSet`) e o identificador AT da empresa (`companyATId`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
    """
    try:
        data = await _client.query(AT_SETTINGS_QUERY, {"companyId": company_id})
        return unwrap(data, "ATSettings")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Dados bancários
# ---------------------------------------------------------------------------
BANKING_INFO_QUERY = """
query ($companyId: Int!, $bankingInfoId: Int!) {
  bankingInfo(companyId: $companyId, bankingInfoId: $bankingInfoId) {
    errors { field msg }
    data {
      bankingInfoId
      name
      value
      associateWithCompany
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_banking_info(company_id: int, banking_info_id: int) -> Any:
    """Obtém os detalhes de um dado bancário de uma empresa (ex. IBAN, SWIFT, nome do
    banco). A estrutura é chave/valor: `name` identifica o tipo de dado e `value` o seu
    conteúdo. Indica também se está associado à empresa (`associateWithCompany`) e se
    pode ser apagado (`deletable`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        banking_info_id: ID do dado bancário a obter.
    """
    variables = {"companyId": company_id, "bankingInfoId": banking_info_id}
    try:
        data = await _client.query(BANKING_INFO_QUERY, variables)
        return unwrap(data, "bankingInfo")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Remessas bancárias (SEPA)
# ---------------------------------------------------------------------------
BANK_REMITTANCE_QUERY = """
query ($companyId: Int!, $bankRemittanceId: Int!) {
  bankRemittance(companyId: $companyId, bankRemittanceId: $bankRemittanceId) {
    errors { field msg }
    data {
      bankRemittanceId
      handled
      type
      name
      date
      notes
      totalValue
      file
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_bank_remittance(company_id: int, bank_remittance_id: int) -> Any:
    """Obtém os detalhes de uma remessa bancária (SEPA) pelo seu ID: tipo (`type`),
    estado de processamento (`handled`), nome, data, notas, valor total (`totalValue`)
    e ficheiro gerado (`file`). Os documentos associados e a empresa não são incluídos
    neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        bank_remittance_id: ID da remessa bancária a obter.
    """
    variables = {"companyId": company_id, "bankRemittanceId": bank_remittance_id}
    try:
        data = await _client.query(BANK_REMITTANCE_QUERY, variables)
        return unwrap(data, "bankRemittance")
    except MolonionError as e:
        return _err(e)


BANK_REMITTANCES_QUERY = """
query ($companyId: Int!, $options: BankRemittanceOptions) {
  bankRemittances(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      bankRemittanceId
      handled
      type
      name
      date
      notes
      totalValue
      file
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_bank_remittances(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as remessas bancárias (SEPA) de uma empresa, que agrupam vários documentos
    de pagamento para processamento em lote (débito direto ou transferência SEPA). Para
    obter uma única pelo seu ID usa `get_bank_remittance`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(BANK_REMITTANCES_QUERY, variables)
        return unwrap(data, "bankRemittances")
    except MolonionError as e:
        return _err(e)


BANKING_INFOS_QUERY = """
query ($companyId: Int!, $options: BankingInfoOptions) {
  bankingInfos(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      bankingInfoId
      name
      value
      associateWithCompany
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_banking_infos(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os dados bancários configurados de uma empresa (IBAN, SWIFT, banco),
    usados na informação de pagamento de documentos e em transações SEPA. Cada entrada
    é chave/valor (`name`/`value`). Para obter um único pelo seu ID usa `get_banking_info`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(BANKING_INFOS_QUERY, variables)
        return unwrap(data, "bankingInfos")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Logs (histórico de alterações) — tipos partilhados: LogOptions, Logs, LogRead
# ---------------------------------------------------------------------------
BANKING_INFO_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  bankingInfoLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_banking_info_logs(
    company_id: int,
    banking_info_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos dados bancários de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        banking_info_id: opcional; filtra os logs de um dado bancário específico
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if banking_info_id is not None:
        options["relatedId"] = banking_info_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(BANKING_INFO_LOGS_QUERY, variables)
        return unwrap(data, "bankingInfoLogs")
    except MolonionError as e:
        return _err(e)


BANK_REMITTANCE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  bankRemittanceLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_bank_remittance_logs(
    company_id: int,
    bank_remittance_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às remessas bancárias de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        bank_remittance_id: opcional; filtra os logs de uma remessa específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if bank_remittance_id is not None:
        options["relatedId"] = bank_remittance_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(BANK_REMITTANCE_LOGS_QUERY, variables)
        return unwrap(data, "bankRemittanceLogs")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Guias de transporte (documentos)
# ---------------------------------------------------------------------------
BILLS_OF_LADING_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  billsOfLading(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      totalDiscountValue
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      yourReference
      ourReference
      notes
      hash
      hashControl
      pdfExport
      deliveryMethodName
      deliveryVehicleName
      deliveryVehicleLicensePlate
      deliveryLoadDate
      deliveryLoadAddress
      deliveryLoadCity
      deliveryLoadZipCode
      deliveryUnloadAddress
      deliveryUnloadCity
      deliveryUnloadZipCode
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_bill_of_lading(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma guia de transporte pelo seu ID de documento: dados do
    documento (número, série, data, estado, totais), dados da entidade/cliente
    (`entityName`, `entityVat`, morada) e dados de transporte (método de entrega,
    veículo/matrícula, datas e moradas de carga/descarga). As linhas de produtos, os
    impostos e outros objetos ligados não são incluídos neste selection set — podem ser
    adicionados se necessário.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (guia de transporte) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(BILLS_OF_LADING_QUERY, variables)
        return unwrap(data, "billsOfLading")
    except MolonionError as e:
        return _err(e)


BILLS_OF_LADING_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  billsOfLadingGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_bill_of_lading_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma guia de
    transporte. Devolve `token`, `path` e `filename`, que se combinam para construir
    o URL de download do PDF. Nota: ao contrário de outras operações, não recebe
    `companyId` — apenas o `documentId`.

    Args:
        document_id: ID do documento (guia de transporte) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            BILLS_OF_LADING_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "billsOfLadingGetPDFToken")
    except MolonionError as e:
        return _err(e)


BILLS_OF_LADING_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  billsOfLadingGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_bills_of_lading_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar várias guias de transporte
    como um arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para
    construir o URL de download. O `full_path` identifica o ZIP a descarregar (caminho
    devolvido por uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(BILLS_OF_LADING_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "billsOfLadingGetZIPToken")
    except MolonionError as e:
        return _err(e)


BILLS_OF_LADING_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  billsOfLadingLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_bills_of_lading_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às guias de transporte de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma guia específica (corresponde a
            `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(BILLS_OF_LADING_LOGS_QUERY, variables)
        return unwrap(data, "billsOfLadingLogs")
    except MolonionError as e:
        return _err(e)


BILLS_OF_LADING_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  billsOfLadingMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_bills_of_lading_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de guias de transporte e o estado
    de entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil
    para confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os logs
    detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(BILLS_OF_LADING_MAIL_RECIPIENTS_QUERY, variables)
        return unwrap(data, "billsOfLadingMailRecipients")
    except MolonionError as e:
        return _err(e)


BILLS_OF_LADING_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  billsOfLadingMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_bills_of_lading_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de emails enviados de uma guia de transporte: para cada envio,
    o email, o conteúdo, a data (`createdAt`) e o `deliveryId`. Usa o `deliveryId` de
    um envio em `get_bills_of_lading_mail_recipients` para ver os destinatários e o
    estado de entrega desse envio.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (guia de transporte) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(BILLS_OF_LADING_MAILS_HISTORY_QUERY, variables)
        return unwrap(data, "billsOfLadingMailsHistory")
    except MolonionError as e:
        return _err(e)


BILLS_OF_LADING_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  billsOfLadingNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_bills_of_lading_next_number(company_id: int, document_set_id: int) -> Any:
    """Obtém o próximo número disponível para uma guia de transporte numa dada série
    de documentos. Devolve `number` (o próximo número) e `name` (o nome da série). Útil
    antes de criar uma nova guia, para saber o número que lhe será atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(BILLS_OF_LADING_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "billsOfLadingNextNumber")
    except MolonionError as e:
        return _err(e)


BILLS_OF_LADING_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: [BillsOfLadingOptions]) {
  billsOfLadingRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
    }
  }
}
"""


@mcp.tool()
async def get_bills_of_lading_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as guias de transporte de uma entidade que podem ser relacionadas/ligadas
    a outro documento (ex. faturar mercadoria transportada).

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente/fornecedor) cujas guias relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    opt: dict[str, Any] = {}
    if page is not None and qty is not None:
        opt["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if opt:
        variables["options"] = [opt]
    try:
        data = await _client.query(BILLS_OF_LADING_RELATABLE_QUERY, variables)
        return unwrap(data, "billsOfLadingRelatable")
    except MolonionError as e:
        return _err(e)


BILLS_OF_LADINGS_QUERY = """
query ($companyId: Int!, $options: BillsOfLadingOptions) {
  billsOfLadings(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_bills_of_lading(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as guias de transporte de uma empresa, com os campos principais
    de cada uma: número, data, série, entidade, valor total e estado. Para obter o
    detalhe completo de uma guia usa `get_bill_of_lading`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(BILLS_OF_LADINGS_QUERY, variables)
        return unwrap(data, "billsOfLadings")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------
BULK_CUSTOMER_QUERY = """
query ($companyId: Int!, $customerIds: [Int!]!) {
  bulkCustomer(companyId: $companyId, customerIds: $customerIds) {
    errors { field msg }
    data {
      customerIds
      customerCount
      bulkCustomer {
        visible
        number
        name
        address
        city
        zipCode
        email
        website
        phone
        fax
        contactName
        contactEmail
        contactPhone
        notes
        swift
        iban
        sepaId
        sepaDate
        discount
        creditLimit
        paymentDay
        notesOnDocs
        documentNotes
        exemptionReason
        documentSetId
      }
    }
  }
}
"""


@mcp.tool()
async def get_bulk_customer(company_id: int, customer_ids: list[int]) -> Any:
    """Obtém uma vista consolidada de vários clientes em simultâneo, como se fossem uma
    única entidade — útil para preencher dados comuns ao operar sobre vários clientes
    de uma vez. Devolve `customerIds`, `customerCount` e o objeto agregado
    `bulkCustomer` com os campos comuns (apenas os valores partilhados por todos surgem
    preenchidos). Os objetos ligados (vendedor, país, impostos, etc.) não são incluídos
    neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        customer_ids: lista de IDs de clientes a agregar.
    """
    variables = {"companyId": company_id, "customerIds": customer_ids}
    try:
        data = await _client.query(BULK_CUSTOMER_QUERY, variables)
        return unwrap(data, "bulkCustomer")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Produtos
# ---------------------------------------------------------------------------
BULK_PRODUCT_QUERY = """
query ($companyId: Int!, $productIds: [Int!]!) {
  bulkProduct(companyId: $companyId, productIds: $productIds) {
    errors { field msg }
    data {
      productIds
      productCount
      bulkProduct {
        type
        posFavorite
        name
        summary
        notes
        notesOnExport
        price
        priceWithTaxes
        hasStock
        minStock
        img
        exemptionReason
        costPrice
        totalCostPrice
        totalSale
      }
    }
  }
}
"""


@mcp.tool()
async def get_bulk_product(company_id: int, product_ids: list[int]) -> Any:
    """Obtém uma vista consolidada de vários produtos em simultâneo, como se fossem um
    único produto — útil para atualizações de preços em massa e operações em lote.
    Devolve `productIds`, `productCount` e o objeto agregado `bulkProduct` com os campos
    comuns (apenas os valores partilhados por todos surgem preenchidos). Os objetos
    ligados (categoria, armazém, impostos, fornecedores, etc.) não são incluídos neste
    selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        product_ids: lista de IDs de produtos a agregar.
    """
    variables = {"companyId": company_id, "productIds": product_ids}
    try:
        data = await _client.query(BULK_PRODUCT_QUERY, variables)
        return unwrap(data, "bulkProduct")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Fornecedores
# ---------------------------------------------------------------------------
BULK_SUPPLIER_QUERY = """
query ($companyId: Int!, $supplierIds: [Int!]!) {
  bulkSupplier(companyId: $companyId, supplierIds: $supplierIds) {
    errors { field msg }
    data {
      supplierIds
      supplierCount
      bulkSupplier {
        visible
        name
        address
        city
        zipCode
        email
        website
        phone
        fax
        contactName
        contactEmail
        contactPhone
        notes
        swift
        iban
        sepaId
        sepaDate
        discount
        creditLimit
        documentNotes
        notesOnDocs
        deletable
      }
    }
  }
}
"""


@mcp.tool()
async def get_bulk_supplier(company_id: int, supplier_ids: list[int]) -> Any:
    """Obtém uma vista consolidada de vários fornecedores em simultâneo, como se fossem
    uma única entidade — útil para operações em lote e relatórios. Devolve `supplierIds`,
    `supplierCount` e o objeto agregado `bulkSupplier` com os campos comuns (apenas os
    valores partilhados por todos surgem preenchidos). Os objetos ligados (país, método
    de pagamento, etc.) não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        supplier_ids: lista de IDs de fornecedores a agregar.
    """
    variables = {"companyId": company_id, "supplierIds": supplier_ids}
    try:
        data = await _client.query(BULK_SUPPLIER_QUERY, variables)
        return unwrap(data, "bulkSupplier")
    except MolonionError as e:
        return _err(e)


COMPANY_LOGS_QUERY = """
query ($companyId: Int, $options: LogOptions) {
  companyLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_company_logs(
    company_id: int | None = None,
    related_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às definições/dados de empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`). Ao contrário de outros `*Logs`,
    o `company_id` é opcional.

    Args:
        company_id: opcional; ID da empresa a filtrar (obtém-se via `me`).
        related_id: opcional; filtra os logs de um registo específico (`relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if related_id is not None:
        options["relatedId"] = related_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {}
    if company_id is not None:
        variables["companyId"] = company_id
    if options:
        variables["options"] = options
    try:
        data = await _client.query(COMPANY_LOGS_QUERY, variables)
        return unwrap(data, "companyLogs")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Perfis / permissões (roles)
# ---------------------------------------------------------------------------
COMPANY_ROLE_QUERY = """
query ($roleId: Int!, $companyId: Int!) {
  companyRole(roleId: $roleId, companyId: $companyId) {
    errors { field msg }
    data {
      roleId
      companyId
      code
      name
      description
      admin
      deletable
      createdAt
      updatedAt
      permissions {
        resource
        resourceName
        action
        actionName
        allow
        companyAdmin
        subscriptionExpiredAllowed
      }
    }
  }
}
"""


@mcp.tool()
async def get_company_role(company_id: int, role_id: int) -> Any:
    """Obtém um perfil de permissões (role) de uma empresa pelo seu ID: nome, código,
    descrição, se é administrador (`admin`) e a lista de permissões (`permissions`), cada
    uma com o recurso, a ação e se é permitida (`allow`). O perfil-pai e as dependências
    tipadas de cada permissão não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        role_id: ID do perfil (role) a obter.
    """
    variables = {"companyId": company_id, "roleId": role_id}
    try:
        data = await _client.query(COMPANY_ROLE_QUERY, variables)
        return unwrap(data, "companyRole")
    except MolonionError as e:
        return _err(e)


COMPANY_ROLE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  companyRoleLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_company_role_logs(
    company_id: int,
    role_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos perfis de permissões (roles) de uma
    empresa: criações, modificações e remoções. Cada entrada indica a operação
    (`operation`), os valores antigos/novos (`oldValues`/`newValues`), quem a fez
    (`userId`, `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        role_id: opcional; filtra os logs de um perfil específico (`relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if role_id is not None:
        options["relatedId"] = role_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(COMPANY_ROLE_LOGS_QUERY, variables)
        return unwrap(data, "companyRoleLogs")
    except MolonionError as e:
        return _err(e)


COMPANY_ROLES_QUERY = """
query ($companyId: Int!, $options: CompanyRoleOptions) {
  companyRoles(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      roleId
      code
      name
      description
      admin
      deletable
      createdAt
      updatedAt
    }
  }
}
"""


@mcp.tool()
async def list_company_roles(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os perfis de permissões (roles) configurados numa empresa, com os campos
    principais de cada um (código, nome, descrição, se é administrador). Para obter as
    permissões detalhadas de um perfil usa `get_company_role`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(COMPANY_ROLES_QUERY, variables)
        return unwrap(data, "companyRoles")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Subscrições
# ---------------------------------------------------------------------------
COMPANY_SUBSCRIPTIONS_QUERY = """
query ($companyId: Int!, $options: CompanySubscriptionOptions, $showExperimental: Boolean) {
  companySubscriptions(companyId: $companyId, options: $options, showExperimental: $showExperimental) {
    errors { field msg }
    data {
      subscriptionId
      paymentMode
      price
      discount
      upgradeDiscount
      associatedCompanyVat
      associatedCompanyNotes
      startDate
      endDate
      paid
      lastPaymentDate
      notes
      saleDocumentIssued
      temporaryPaymentMode
      temporaryPrice
      temporaryExpiracy
      paymentId
      documentId
      createdAt
      updatedAt
    }
  }
}
"""


@mcp.tool()
async def list_company_subscriptions(
    company_id: int,
    show_experimental: bool | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as subscrições de uma empresa na Moloni ON: para cada uma, o plano e
    modo de pagamento (`paymentMode`), preço e desconto (`price`/`discount`/
    `upgradeDiscount`), período de vigência (`startDate`/`endDate`), estado de
    pagamento (`paid`, `lastPaymentDate`), eventual alteração temporária de plano/preço
    (`temporaryPaymentMode`/`temporaryPrice`/`temporaryExpiracy`) e o documento de venda
    emitido (`documentId`, `saleDocumentIssued`). Os objetos ligados (plano, empresa,
    empresa associada, extras e documentos da subscrição) e o bloco verboso de lembretes
    de email (`mail1Sent`…`mail6Sent`) não são incluídos neste selection set — podem ser
    adicionados se necessário.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        show_experimental: opcional; inclui também funcionalidades/planos experimentais.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    if show_experimental is not None:
        variables["showExperimental"] = show_experimental
    try:
        data = await _client.query(COMPANY_SUBSCRIPTIONS_QUERY, variables)
        return unwrap(data, "companySubscriptions")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Utilizadores de empresa
# ---------------------------------------------------------------------------
COMPANY_USER_QUERY = """
query ($userId: Int!, $companyId: Int!) {
  companyUser(userId: $userId, companyId: $companyId) {
    errors { field msg }
    data {
      userCompanyId
      userId
      roleId
      companyId
      deletable
      createdAt
      updatedAt
      user {
        userId
        name
        email
        phone
        img
        createdAt
        updatedAt
      }
    }
  }
}
"""


@mcp.tool()
async def get_company_user(company_id: int, user_id: int) -> Any:
    """Obtém o perfil de um utilizador dentro de uma empresa: a ligação
    utilizador↔empresa (`userCompanyId`), o perfil de permissões atribuído (`roleId`)
    e os dados de identificação do utilizador (`user`: nome, email, telefone, avatar).
    Para as permissões detalhadas do perfil usa `get_company_role` com o `roleId`; o
    objeto `role` completo e o objeto `company` não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        user_id: ID do utilizador a obter dentro da empresa.
    """
    variables = {"companyId": company_id, "userId": user_id}
    try:
        data = await _client.query(COMPANY_USER_QUERY, variables)
        return unwrap(data, "companyUser")
    except MolonionError as e:
        return _err(e)


COMPANY_USER_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  companyUserLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_company_user_logs(
    company_id: int,
    user_company_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos utilizadores de uma empresa:
    criações, alterações de perfil/permissões e remoções. Cada entrada indica a operação
    (`operation`), os valores antigos/novos (`oldValues`/`newValues`), quem a fez
    (`userId`, `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        user_company_id: opcional; filtra os logs de uma ligação utilizador↔empresa
            específica (corresponde a `relatedId`, o `userCompanyId` de `get_company_user`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if user_company_id is not None:
        options["relatedId"] = user_company_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(COMPANY_USER_LOGS_QUERY, variables)
        return unwrap(data, "companyUserLogs")
    except MolonionError as e:
        return _err(e)


COMPANY_USERS_QUERY = """
query ($companyId: Int!, $options: CompanyUserOptions) {
  companyUsers(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      userCompanyId
      userId
      roleId
      companyId
      deletable
      createdAt
      updatedAt
      user {
        userId
        name
        email
        phone
        img
        createdAt
        updatedAt
      }
    }
  }
}
"""


@mcp.tool()
async def list_company_users(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os utilizadores de uma empresa, com a identificação de cada um (`user`:
    nome, email, telefone, avatar) e o perfil de permissões atribuído (`roleId`). Para
    o detalhe de um único utilizador usa `get_company_user`; para as permissões do
    perfil usa `get_company_role` com o `roleId`. Os objetos `role` e `company`
    completos não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(COMPANY_USERS_QUERY, variables)
        return unwrap(data, "companyUsers")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Países (tabela de referência global)
# ---------------------------------------------------------------------------
COUNTRIES_QUERY = """
query ($options: CountryOptions) {
  countries(options: $options) {
    errors { field msg }
    data {
      countryId
      iso3166_1
      title
      img
      viesCountry
      visible
      ordering
      languageId
      notes
      deletable
      createdAt
      updatedAt
    }
  }
}
"""


COUNTRY_QUERY = """
query ($countryId: Int!) {
  country(countryId: $countryId) {
    errors { field msg }
    data {
      countryId
      iso3166_1
      title
      img
      viesCountry
      visible
      ordering
      languageId
      notes
      deletable
      createdAt
      updatedAt
    }
  }
}
"""


@mcp.tool()
async def get_country(country_id: int) -> Any:
    """Obtém um país pelo seu ID — tabela de referência global usada em moradas e
    configuração fiscal. Devolve o código ISO 3166-1 (`iso3166_1`), o nome (`title`),
    se é país VIES/UE (`viesCountry`) e a bandeira (`img`). Ao contrário da maioria das
    operações, não recebe `companyId`. Os objetos ligados (idioma, regimes fiscais
    especiais, traduções) não são incluídos neste selection set. Para listar todos os
    países usa `list_countries`.

    Args:
        country_id: ID do país a obter (obtém-se via `list_countries`).
    """
    try:
        data = await _client.query(COUNTRY_QUERY, {"countryId": country_id})
        return unwrap(data, "country")
    except MolonionError as e:
        return _err(e)


@mcp.tool()
async def list_countries(page: int | None = None, qty: int | None = None) -> Any:
    """Lista os países disponíveis na Moloni ON — tabela de referência global usada em
    moradas, configuração fiscal e zonas fiscais. Para cada país: o `countryId` (usado
    noutras operações), o código ISO 3166-1 (`iso3166_1`), o nome (`title`), se é país
    VIES/UE (`viesCountry`) e a bandeira (`img`). Ao contrário da maioria das operações,
    não recebe `companyId`. Os objetos ligados (idioma, regimes fiscais especiais,
    traduções) não são incluídos neste selection set.

    Args:
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(COUNTRIES_QUERY, variables)
        return unwrap(data, "countries")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Notas de crédito (documentos)
# ---------------------------------------------------------------------------
CREDIT_NOTE_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  creditNote(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscountValue
      totalDiscountValue
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      yourReference
      ourReference
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_credit_note(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma nota de crédito pelo seu ID de documento: dados do
    documento (número, série, data, estado, totais), dados da entidade/cliente
    (`entityName`, `entityVat`, morada) e o estado de reconciliação com os documentos
    de origem (`reconciledValue`, `remainingReconciledValue`, `reconciliationPercentage`,
    `totalRelatedAppliedValue`). As linhas de produtos, os impostos, o cliente completo,
    os documentos relacionados e os dados AT não são incluídos neste selection set —
    podem ser adicionados se necessário.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (nota de crédito) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(CREDIT_NOTE_QUERY, variables)
        return unwrap(data, "creditNote")
    except MolonionError as e:
        return _err(e)


CREDIT_NOTE_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  creditNoteGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_credit_note_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma nota de crédito.
    Devolve `token`, `path` e `filename`, que se combinam para construir o URL de
    download do PDF. Nota: ao contrário de outras operações, não recebe `companyId` —
    apenas o `documentId`.

    Args:
        document_id: ID do documento (nota de crédito) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            CREDIT_NOTE_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "creditNoteGetPDFToken")
    except MolonionError as e:
        return _err(e)


CREDIT_NOTE_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  creditNoteGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_credit_note_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar várias notas de crédito como
    um arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para construir
    o URL de download. O `full_path` identifica o ZIP a descarregar (caminho devolvido
    por uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(CREDIT_NOTE_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "creditNoteGetZIPToken")
    except MolonionError as e:
        return _err(e)


CREDIT_NOTE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  creditNoteLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_credit_note_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às notas de crédito de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma nota de crédito específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(CREDIT_NOTE_LOGS_QUERY, variables)
        return unwrap(data, "creditNoteLogs")
    except MolonionError as e:
        return _err(e)


CREDIT_NOTE_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  creditNoteMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_credit_note_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de notas de crédito e o estado de
    entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para
    confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os logs
    detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_credit_note_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(CREDIT_NOTE_MAIL_RECIPIENTS_QUERY, variables)
        return unwrap(data, "creditNoteMailRecipients")
    except MolonionError as e:
        return _err(e)


CREDIT_NOTE_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  creditNoteMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_credit_note_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de emails enviados de uma nota de crédito: para cada envio,
    o email, o conteúdo, a data (`createdAt`) e o `deliveryId`. Usa o `deliveryId` de
    um envio em `get_credit_note_mail_recipients` para ver os destinatários e o estado
    de entrega desse envio.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (nota de crédito) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(CREDIT_NOTE_MAILS_HISTORY_QUERY, variables)
        return unwrap(data, "creditNoteMailsHistory")
    except MolonionError as e:
        return _err(e)


CREDIT_NOTE_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  creditNoteNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_credit_note_next_number(company_id: int, document_set_id: int) -> Any:
    """Obtém o próximo número disponível para uma nota de crédito numa dada série de
    documentos. Devolve `number` (o próximo número) e `name` (o nome da série). Útil
    antes de criar uma nova nota de crédito, para saber o número que lhe será atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(CREDIT_NOTE_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "creditNoteNextNumber")
    except MolonionError as e:
        return _err(e)


CREDIT_NOTE_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: CreditNoteOptions) {
  creditNoteRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_credit_note_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as notas de crédito de uma entidade que podem ser relacionadas/ligadas a
    outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente) cujas notas de crédito relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(CREDIT_NOTE_RELATABLE_QUERY, variables)
        return unwrap(data, "creditNoteRelatable")
    except MolonionError as e:
        return _err(e)


CREDIT_NOTES_QUERY = """
query ($companyId: Int!, $options: CreditNoteOptions) {
  creditNotes(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      reconciledValue
      remainingReconciledValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_credit_notes(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as notas de crédito de uma empresa, com os campos principais de
    cada uma: número, data, série, entidade, valor total e estado de reconciliação
    (`reconciledValue`, `remainingReconciledValue`). Para obter o detalhe completo de
    uma nota de crédito usa `get_credit_note`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(CREDIT_NOTES_QUERY, variables)
        return unwrap(data, "creditNotes")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Moedas (tabela de referência global)
# ---------------------------------------------------------------------------
CURRENCIES_QUERY = """
query ($options: CurrencyOptions) {
  currencies(options: $options) {
    errors { field msg }
    data {
      currencyId
      iso4217
      symbol
      symbolPosition
      numberDecimalPlaces
      largeCurrency
      description
      visible
      deletable
    }
  }
}
"""


CURRENCY_QUERY = """
query ($currencyId: Int!) {
  currency(currencyId: $currencyId) {
    errors { field msg }
    data {
      currencyId
      iso4217
      symbol
      symbolPosition
      numberDecimalPlaces
      largeCurrency
      description
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_currency(currency_id: int) -> Any:
    """Obtém uma moeda pelo seu ID — tabela de referência global usada em documentos e
    câmbios. Devolve o código ISO 4217 (`iso4217`), o símbolo e a sua posição
    (`symbol`/`symbolPosition`) e o número de casas decimais (`numberDecimalPlaces`). Ao
    contrário da maioria das operações, não recebe `companyId`. Os objetos ligados
    (traduções, denominações) não são incluídos neste selection set. Para listar todas
    as moedas usa `list_currencies`.

    Args:
        currency_id: ID da moeda a obter (obtém-se via `list_currencies`).
    """
    try:
        data = await _client.query(CURRENCY_QUERY, {"currencyId": currency_id})
        return unwrap(data, "currency")
    except MolonionError as e:
        return _err(e)


@mcp.tool()
async def list_currencies(page: int | None = None, qty: int | None = None) -> Any:
    """Lista as moedas disponíveis na Moloni ON — tabela de referência global usada em
    documentos e câmbios. Para cada moeda: o `currencyId` (usado noutras operações), o
    código ISO 4217 (`iso4217`), o símbolo e a sua posição (`symbol`/`symbolPosition`)
    e o número de casas decimais (`numberDecimalPlaces`). Ao contrário da maioria das
    operações, não recebe `companyId`. Os objetos ligados (traduções, denominações) não
    são incluídos neste selection set.

    Args:
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(CURRENCIES_QUERY, variables)
        return unwrap(data, "currencies")
    except MolonionError as e:
        return _err(e)


CURRENCY_DENOMINATIONS_QUERY = """
query ($currencyId: Int!) {
  currencyDenominations(currencyId: $currencyId) {
    errors { field msg }
    data {
      currencyDenominationId
      currencyId
      type
      value
      img
    }
  }
}
"""


@mcp.tool()
async def get_currency_denominations(currency_id: int) -> Any:
    """Lista as denominações (notas e moedas) de uma moeda — útil para contagem de caixa
    e fecho de POS. Para cada denominação: o tipo (`type`: nota/moeda), o valor facial
    (`value`) e a imagem (`img`). Ao contrário da maioria das operações, não recebe
    `companyId`.

    Args:
        currency_id: ID da moeda cujas denominações se pretendem (obtém-se via
            `list_currencies`).
    """
    try:
        data = await _client.query(
            CURRENCY_DENOMINATIONS_QUERY, {"currencyId": currency_id}
        )
        return unwrap(data, "currencyDenominations")
    except MolonionError as e:
        return _err(e)


CURRENCY_EXCHANGE_QUERY = """
query ($currencyExchangeId: Int!) {
  currencyExchange(currencyExchangeId: $currencyExchangeId) {
    errors { field msg }
    data {
      currencyExchangeId
      pair
      name
      exchange
      visible
      from { currencyId iso4217 symbol }
      to { currencyId iso4217 symbol }
    }
  }
}
"""


@mcp.tool()
async def get_currency_exchange(currency_exchange_id: int) -> Any:
    """Obtém uma taxa de câmbio entre duas moedas pelo seu ID. Devolve o par
    (`pair`, ex. "EUR/USD"), o nome, a taxa (`exchange`) e as moedas de origem (`from`)
    e destino (`to`), cada uma com o `currencyId`, código ISO 4217 e símbolo. Ao
    contrário da maioria das operações, não recebe `companyId`.

    Args:
        currency_exchange_id: ID da taxa de câmbio a obter.
    """
    try:
        data = await _client.query(
            CURRENCY_EXCHANGE_QUERY, {"currencyExchangeId": currency_exchange_id}
        )
        return unwrap(data, "currencyExchange")
    except MolonionError as e:
        return _err(e)


CURRENCY_EXCHANGES_QUERY = """
query ($options: CurrencyExchangeOptions) {
  currencyExchanges(options: $options) {
    errors { field msg }
    data {
      currencyExchangeId
      pair
      name
      exchange
      visible
      from { currencyId iso4217 symbol }
      to { currencyId iso4217 symbol }
    }
  }
}
"""


@mcp.tool()
async def list_currency_exchanges(
    page: int | None = None, qty: int | None = None
) -> Any:
    """Lista as taxas de câmbio configuradas na Moloni ON. Para cada uma: o par
    (`pair`, ex. "EUR/USD"), o nome, a taxa (`exchange`) e as moedas de origem (`from`)
    e destino (`to`) com o `currencyId`, código ISO 4217 e símbolo. Ao contrário da
    maioria das operações, não recebe `companyId`. Para obter uma única pelo seu ID usa
    `get_currency_exchange`.

    Args:
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(CURRENCY_EXCHANGES_QUERY, variables)
        return unwrap(data, "currencyExchanges")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------
CUSTOMER_QUERY = """
query ($companyId: Int!, $customerId: Int!) {
  customer(companyId: $companyId, customerId: $customerId) {
    errors { field msg }
    data {
      customerId
      number
      name
      vat
      address
      city
      zipCode
      email
      website
      phone
      fax
      contactName
      contactEmail
      contactPhone
      notes
      swift
      iban
      sepaId
      sepaDate
      discount
      creditLimit
      balance
      paymentDay
      notesOnDocs
      documentNotes
      exemptionReason
      isDefault
      visible
      deletable
      countryId
      languageId
      salespersonId
      geographicZoneId
      maturityDateId
      paymentMethodId
      deliveryMethodId
      documentSetId
      priceClassId
    }
  }
}
"""


@mcp.tool()
async def get_customer(company_id: int, customer_id: int) -> Any:
    """Obtém os detalhes de um cliente pelo seu ID: identificação (`name`, `vat`,
    `number`, morada, contactos), dados financeiros (`discount`, `creditLimit`,
    `balance`, `paymentDay`, dados SEPA/IBAN), notas e motivo de isenção, e os IDs das
    entidades associadas (`countryId`, `salespersonId`, `paymentMethodId`,
    `deliveryMethodId`, `documentSetId`, `priceClassId`, …) para encadear com outras
    operações. Os objetos ligados completos (país, vendedor, impostos, moradas
    alternativas, cópias, contagens de documentos) não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        customer_id: ID do cliente a obter.
    """
    variables = {"companyId": company_id, "customerId": customer_id}
    try:
        data = await _client.query(CUSTOMER_QUERY, variables)
        return unwrap(data, "customer")
    except MolonionError as e:
        return _err(e)


CUSTOMER_HISTORY_QUERY = """
query ($companyId: Int!, $options: CustomerHistoryOptions) {
  customerHistory(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      customerId
      docsCount
      customerDebit
      customerCredit
      customerDateBalance
      customerBalance
      customer { customerId number name vat }
    }
  }
}
"""


@mcp.tool()
async def list_customer_history(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o resumo de conta-corrente por cliente de uma empresa: para cada cliente,
    o número de documentos (`docsCount`), o débito e crédito acumulados
    (`customerDebit`/`customerCredit`) e os saldos (`customerDateBalance`,
    `customerBalance`). Inclui a identificação mínima do cliente (`customer`: número,
    nome, NIF). Útil para análise de saldos e cobranças.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(CUSTOMER_HISTORY_QUERY, variables)
        return unwrap(data, "customerHistory")
    except MolonionError as e:
        return _err(e)


# A conta-corrente de um cliente (customerHistoryCustomer) devolve uma LISTA da union
# `CustomerHistoryDocumentRead` (24 tipos de documento). Numa union só se podem
# selecionar campos via inline fragments; estes tipos de documento partilham um conjunto
# comum (documentId/number/date/documentSetName/totalValue/status). Listamos apenas os
# tipos do lado do cliente (os `Supplier*` são de compras e não aparecem aqui).
CUSTOMER_HISTORY_DOC_TYPES = [
    "InvoiceRead",
    "SimplifiedInvoiceRead",
    "InvoiceReceiptRead",
    "ReceiptRead",
    "CreditNoteRead",
    "DebitNoteRead",
    "SettlementNoteRead",
    "ProFormaInvoiceRead",
    "EstimateRead",
    "BillsOfLadingRead",
    "DeliveryNoteRead",
    "CustomerReturnNoteRead",
    "PaymentReturnRead",
    "MigratedInvoiceRead",
    "MigratedSimplifiedInvoiceRead",
    "MigratedCreditNoteRead",
    "MigratedReceiptRead",
    "MigratedInvoiceReceiptRead",
    "MigratedDebitNoteRead",
    "MigratedEstimateRead",
]
_DOC_FRAGMENT_FIELDS = "documentId number date documentSetName totalValue status"
_customer_history_fragments = "\n".join(
    f"      ... on {t} {{ {_DOC_FRAGMENT_FIELDS} }}"
    for t in CUSTOMER_HISTORY_DOC_TYPES
)

CUSTOMER_HISTORY_CUSTOMER_QUERY = """
query ($companyId: Int!, $customerId: Int!, $options: CustomerHistoryOptions) {
  customerHistoryCustomer(companyId: $companyId, customerId: $customerId, options: $options) {
    errors { field msg }
    accumulator
    data {
      __typename
__FRAGMENTS__
    }
  }
}
""".replace("__FRAGMENTS__", _customer_history_fragments)


@mcp.tool()
async def get_customer_history_customer(
    company_id: int,
    customer_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o extrato de conta-corrente de um cliente: a lista de documentos que
    movimentam a conta (faturas, recibos, notas de crédito/débito, etc.), cada um com o
    tipo (`__typename`), `documentId`, número, data, série e valor. Devolve também o
    `accumulator` (saldo acumulado). Cada documento é de um de vários tipos (a resposta é
    uma union); por isso o campo `__typename` identifica o tipo de cada linha.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        customer_id: ID do cliente cujo extrato se pretende.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "customerId": customer_id}
    if options:
        variables["options"] = options
    try:
        raw = await _client.query(CUSTOMER_HISTORY_CUSTOMER_QUERY, variables)
        documents = unwrap(raw, "customerHistoryCustomer")  # valida erros do envelope
        node = (raw or {}).get("customerHistoryCustomer") or {}
        return {"accumulator": node.get("accumulator"), "documents": documents}
    except MolonionError as e:
        return _err(e)


# NOTA: ao contrário da maioria das operações, esta devolve uma LISTA de envelopes
# (`[CustomerHistoryUserSettingsTemplates]!`), não um único envelope — por isso o
# `unwrap()` não se aplica; tratamos a lista à mão.
CUSTOMER_HISTORY_TEMPLATES_QUERY = """
query ($companyId: Int!) {
  customerHistoryUserSettingsTemplates(companyId: $companyId) {
    errors { field msg }
    data {
      userSettingsTemplateId
      formName
      name
    }
  }
}
"""


@mcp.tool()
async def list_customer_history_templates(company_id: int) -> Any:
    """Lista os modelos (templates) de definições do utilizador para o ecrã de
    conta-corrente de clientes — filtros/colunas guardados pelo utilizador para reutilizar.
    Cada modelo tem `userSettingsTemplateId`, `formName` (o formulário a que se aplica) e
    `name`. Os objetos ligados (utilizador, empresa e as definições guardadas) não são
    incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
    """
    try:
        raw = await _client.query(
            CUSTOMER_HISTORY_TEMPLATES_QUERY, {"companyId": company_id}
        )
        envelopes = (raw or {}).get("customerHistoryUserSettingsTemplates") or []
        errs = [
            e for env in envelopes if env for e in (env.get("errors") or [])
        ]
        if errs:
            raise MolonionError(
                "A operação 'customerHistoryUserSettingsTemplates' devolveu erros.",
                errors=errs,
            )
        return [t for env in envelopes if env for t in (env.get("data") or [])]
    except MolonionError as e:
        return _err(e)


CUSTOMER_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  customerLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_customer_logs(
    company_id: int,
    customer_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos clientes de uma empresa: criações,
    modificações e remoções. Cada entrada indica a operação (`operation`), os valores
    antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`, `email`)
    e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        customer_id: opcional; filtra os logs de um cliente específico (corresponde a
            `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if customer_id is not None:
        options["relatedId"] = customer_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(CUSTOMER_LOGS_QUERY, variables)
        return unwrap(data, "customerLogs")
    except MolonionError as e:
        return _err(e)


# NOTA: aqui o `data` do envelope é um escalar String (o próprio número), não um objeto.
CUSTOMER_NEXT_NUMBER_QUERY = """
query ($companyId: Int!) {
  customerNextNumber(companyId: $companyId) {
    errors { field msg }
    data
  }
}
"""


@mcp.tool()
async def get_customer_next_number(company_id: int) -> Any:
    """Obtém o próximo número de cliente disponível numa empresa (o `number` sequencial
    que será atribuído ao próximo cliente criado). Devolve o número como string. Útil
    antes de criar um novo cliente.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
    """
    try:
        data = await _client.query(CUSTOMER_NEXT_NUMBER_QUERY, {"companyId": company_id})
        return unwrap(data, "customerNextNumber")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Notas de devolução de cliente (documentos)
# ---------------------------------------------------------------------------
CUSTOMER_RETURN_NOTE_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  customerReturnNote(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscountValue
      totalDiscountValue
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      yourReference
      ourReference
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      deliveryMethodName
      deliveryVehicleName
      deliveryVehicleLicensePlate
      deliveryLoadDate
      deliveryLoadAddress
      deliveryLoadCity
      deliveryLoadZipCode
      deliveryUnloadAddress
      deliveryUnloadCity
      deliveryUnloadZipCode
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_customer_return_note(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma nota de devolução de cliente pelo seu ID de documento:
    dados do documento (número, série, data, estado, totais), dados da entidade/cliente
    (`entityName`, `entityVat`, morada), o estado de reconciliação (`reconciledValue`,
    `remainingReconciledValue`, `reconciliationPercentage`) e os dados de transporte
    (método de entrega, veículo/matrícula, datas e moradas de carga/descarga). As linhas
    de produtos, os impostos, o cliente completo, os documentos relacionados e os dados
    AT não são incluídos neste selection set — podem ser adicionados se necessário.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (nota de devolução) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(CUSTOMER_RETURN_NOTE_QUERY, variables)
        return unwrap(data, "customerReturnNote")
    except MolonionError as e:
        return _err(e)


CUSTOMER_RETURN_NOTE_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  customerReturnNoteGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_customer_return_note_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma nota de devolução
    de cliente. Devolve `token`, `path` e `filename`, que se combinam para construir o
    URL de download do PDF. Nota: ao contrário de outras operações, não recebe
    `companyId` — apenas o `documentId`.

    Args:
        document_id: ID do documento (nota de devolução) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            CUSTOMER_RETURN_NOTE_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "customerReturnNoteGetPDFToken")
    except MolonionError as e:
        return _err(e)


CUSTOMER_RETURN_NOTE_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  customerReturnNoteGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_customer_return_note_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar várias notas de devolução de
    cliente como um arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam
    para construir o URL de download. O `full_path` identifica o ZIP a descarregar
    (caminho devolvido por uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(CUSTOMER_RETURN_NOTE_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "customerReturnNoteGetZIPToken")
    except MolonionError as e:
        return _err(e)


CUSTOMER_RETURN_NOTE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  customerReturnNoteLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_customer_return_note_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às notas de devolução de cliente de uma
    empresa: criações, modificações e remoções. Cada entrada indica a operação
    (`operation`), os valores antigos/novos (`oldValues`/`newValues`), quem a fez
    (`userId`, `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma nota de devolução específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(CUSTOMER_RETURN_NOTE_LOGS_QUERY, variables)
        return unwrap(data, "customerReturnNoteLogs")
    except MolonionError as e:
        return _err(e)


CUSTOMER_RETURN_NOTE_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  customerReturnNoteMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_customer_return_note_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de notas de devolução de cliente e o
    estado de entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`).
    Útil para confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os
    logs detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_customer_return_note_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(CUSTOMER_RETURN_NOTE_MAIL_RECIPIENTS_QUERY, variables)
        return unwrap(data, "customerReturnNoteMailRecipients")
    except MolonionError as e:
        return _err(e)


CUSTOMER_RETURN_NOTE_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  customerReturnNoteMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_customer_return_note_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de emails enviados de uma nota de devolução de cliente: para
    cada envio, o email, o conteúdo, a data (`createdAt`) e o `deliveryId`. Usa o
    `deliveryId` de um envio em `get_customer_return_note_mail_recipients` para ver os
    destinatários e o estado de entrega desse envio.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (nota de devolução) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(CUSTOMER_RETURN_NOTE_MAILS_HISTORY_QUERY, variables)
        return unwrap(data, "customerReturnNoteMailsHistory")
    except MolonionError as e:
        return _err(e)


CUSTOMER_RETURN_NOTE_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  customerReturnNoteNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_customer_return_note_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para uma nota de devolução de cliente numa dada
    série de documentos. Devolve `number` (o próximo número) e `name` (o nome da série).
    Útil antes de criar uma nova nota de devolução, para saber o número que lhe será
    atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(CUSTOMER_RETURN_NOTE_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "customerReturnNoteNextNumber")
    except MolonionError as e:
        return _err(e)


CUSTOMER_RETURN_NOTE_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: CustomerReturnNoteOptions) {
  customerReturnNoteRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_customer_return_note_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as notas de devolução de cliente de uma entidade que podem ser
    relacionadas/ligadas a outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente) cujas notas de devolução relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(CUSTOMER_RETURN_NOTE_RELATABLE_QUERY, variables)
        return unwrap(data, "customerReturnNoteRelatable")
    except MolonionError as e:
        return _err(e)


CUSTOMER_RETURN_NOTES_QUERY = """
query ($companyId: Int!, $options: CustomerReturnNoteOptions) {
  customerReturnNotes(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      reconciledValue
      remainingReconciledValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_customer_return_notes(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as notas de devolução de cliente de uma empresa, com os campos
    principais de cada uma: número, data, série, entidade, valor total e estado de
    reconciliação (`reconciledValue`, `remainingReconciledValue`). Para obter o detalhe
    completo de uma nota de devolução usa `get_customer_return_note`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(CUSTOMER_RETURN_NOTES_QUERY, variables)
        return unwrap(data, "customerReturnNotes")
    except MolonionError as e:
        return _err(e)


# Clientes — listagem (complemento de get_customer)
CUSTOMERS_QUERY = """
query ($companyId: Int!, $options: CustomerOptions) {
  customers(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      customerId
      number
      name
      vat
      email
      phone
      address
      city
      zipCode
      balance
      creditLimit
      isDefault
      visible
      countryId
    }
  }
}
"""


@mcp.tool()
async def list_customers(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) os clientes de uma empresa, com os campos principais de cada um:
    número, nome, NIF, contactos, morada e saldo/limite de crédito (`balance`,
    `creditLimit`). Para obter o detalhe completo de um cliente usa `get_customer`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(CUSTOMERS_QUERY, variables)
        return unwrap(data, "customers")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Campos personalizados (custom fields)
# ---------------------------------------------------------------------------
CUSTOM_FIELD_QUERY = """
query ($companyId: Int!, $customFieldId: String!) {
  customField(companyId: $companyId, customFieldId: $customFieldId) {
    errors { field msg }
    data {
      customFieldId
      name
      type
      mandatory
      printOnDocuments
      companyId
      deletable
      options { optionId ordering value }
    }
  }
}
"""


@mcp.tool()
async def get_custom_field(company_id: int, custom_field_id: str) -> Any:
    """Obtém um campo personalizado (custom field) de uma empresa pelo seu ID: o nome
    (`name`), o tipo (`type`: texto, número, seleção, …), se é obrigatório (`mandatory`),
    se é impresso nos documentos (`printOnDocuments`) e, para campos de seleção, a lista
    de valores possíveis (`options`: `optionId`, `value`, `ordering`). Nota: o
    `custom_field_id` é uma **string**, não um inteiro. O objeto `company` ligado não é
    incluído neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        custom_field_id: ID (string) do campo personalizado a obter.
    """
    variables = {"companyId": company_id, "customFieldId": custom_field_id}
    try:
        data = await _client.query(CUSTOM_FIELD_QUERY, variables)
        return unwrap(data, "customField")
    except MolonionError as e:
        return _err(e)


CUSTOM_FIELD_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  customFieldLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_custom_field_logs(
    company_id: int,
    related_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos campos personalizados de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        related_id: opcional; filtra os logs de um campo personalizado específico
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if related_id is not None:
        options["relatedId"] = related_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(CUSTOM_FIELD_LOGS_QUERY, variables)
        return unwrap(data, "customFieldLogs")
    except MolonionError as e:
        return _err(e)


CUSTOM_FIELDS_QUERY = """
query ($companyId: Int!, $options: CustomFieldOptions) {
  customFields(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      customFieldId
      name
      type
      mandatory
      printOnDocuments
      companyId
      deletable
      options { optionId ordering value }
    }
  }
}
"""


@mcp.tool()
async def list_custom_fields(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os campos personalizados (custom fields) configurados numa empresa, cada um
    com o nome (`name`), tipo (`type`), se é obrigatório (`mandatory`), se é impresso nos
    documentos (`printOnDocuments`) e, para campos de seleção, os valores possíveis
    (`options`). Para obter um único pelo seu ID usa `get_custom_field`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(CUSTOM_FIELDS_QUERY, variables)
        return unwrap(data, "customFields")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Notas de débito (documentos)
# ---------------------------------------------------------------------------
DEBIT_NOTE_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  debitNote(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscountValue
      totalDiscountValue
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      expirationDate
      maturityDateDays
      maturityDateName
      yourReference
      ourReference
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_debit_note(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma nota de débito pelo seu ID de documento: dados do
    documento (número, série, data, estado, totais), dados da entidade/cliente
    (`entityName`, `entityVat`, morada), o estado de reconciliação (`reconciledValue`,
    `remainingReconciledValue`, `reconciliationPercentage`) e os dados de vencimento
    (`expirationDate`, `maturityDateDays`, `maturityDateName`). As linhas de produtos,
    os impostos, o cliente completo, os documentos relacionados e os dados AT não são
    incluídos neste selection set — podem ser adicionados se necessário.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (nota de débito) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(DEBIT_NOTE_QUERY, variables)
        return unwrap(data, "debitNote")
    except MolonionError as e:
        return _err(e)


DEBIT_NOTE_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  debitNoteGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_debit_note_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma nota de débito.
    Devolve `token`, `path` e `filename`, que se combinam para construir o URL de
    download do PDF. Nota: ao contrário de outras operações, não recebe `companyId` —
    apenas o `documentId`.

    Args:
        document_id: ID do documento (nota de débito) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            DEBIT_NOTE_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "debitNoteGetPDFToken")
    except MolonionError as e:
        return _err(e)


DEBIT_NOTE_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  debitNoteGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_debit_note_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar várias notas de débito como um
    arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para construir o
    URL de download. O `full_path` identifica o ZIP a descarregar (caminho devolvido por
    uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(DEBIT_NOTE_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "debitNoteGetZIPToken")
    except MolonionError as e:
        return _err(e)


DEBIT_NOTE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  debitNoteLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_debit_note_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às notas de débito de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma nota de débito específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DEBIT_NOTE_LOGS_QUERY, variables)
        return unwrap(data, "debitNoteLogs")
    except MolonionError as e:
        return _err(e)


DEBIT_NOTE_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  debitNoteMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_debit_note_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de notas de débito e o estado de
    entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para
    confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os logs
    detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_debit_note_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DEBIT_NOTE_MAIL_RECIPIENTS_QUERY, variables)
        return unwrap(data, "debitNoteMailRecipients")
    except MolonionError as e:
        return _err(e)


DEBIT_NOTE_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  debitNoteMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_debit_note_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de emails enviados de uma nota de débito: para cada envio, o
    email, o conteúdo, a data (`createdAt`) e o `deliveryId`. Usa o `deliveryId` de um
    envio em `get_debit_note_mail_recipients` para ver os destinatários e o estado de
    entrega desse envio.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (nota de débito) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DEBIT_NOTE_MAILS_HISTORY_QUERY, variables)
        return unwrap(data, "debitNoteMailsHistory")
    except MolonionError as e:
        return _err(e)


DEBIT_NOTE_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  debitNoteNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_debit_note_next_number(company_id: int, document_set_id: int) -> Any:
    """Obtém o próximo número disponível para uma nota de débito numa dada série de
    documentos. Devolve `number` (o próximo número) e `name` (o nome da série). Útil
    antes de criar uma nova nota de débito, para saber o número que lhe será atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(DEBIT_NOTE_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "debitNoteNextNumber")
    except MolonionError as e:
        return _err(e)


DEBIT_NOTE_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: DebitNoteOptions) {
  debitNoteRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_debit_note_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as notas de débito de uma entidade que podem ser relacionadas/ligadas a
    outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente) cujas notas de débito relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DEBIT_NOTE_RELATABLE_QUERY, variables)
        return unwrap(data, "debitNoteRelatable")
    except MolonionError as e:
        return _err(e)


DEBIT_NOTES_QUERY = """
query ($companyId: Int!, $options: DebitNoteOptions) {
  debitNotes(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      reconciledValue
      remainingReconciledValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_debit_notes(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as notas de débito de uma empresa, com os campos principais de
    cada uma: número, data, série, entidade, valor total e estado de reconciliação
    (`reconciledValue`, `remainingReconciledValue`). Para obter o detalhe completo de
    uma nota de débito usa `get_debit_note`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DEBIT_NOTES_QUERY, variables)
        return unwrap(data, "debitNotes")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Métodos de entrega
# ---------------------------------------------------------------------------
DELIVERY_METHOD_QUERY = """
query ($companyId: Int!, $deliveryMethodId: Int!) {
  deliveryMethod(companyId: $companyId, deliveryMethodId: $deliveryMethodId) {
    errors { field msg }
    data {
      deliveryMethodId
      name
      visible
      isDefault
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_delivery_method(company_id: int, delivery_method_id: int) -> Any:
    """Obtém um método de entrega de uma empresa pelo seu ID: nome (`name`), se está
    visível (`visible`), se é o método por omissão (`isDefault`) e se pode ser apagado
    (`deletable`). O objeto `company` ligado não é incluído neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_method_id: ID do método de entrega a obter.
    """
    variables = {"companyId": company_id, "deliveryMethodId": delivery_method_id}
    try:
        data = await _client.query(DELIVERY_METHOD_QUERY, variables)
        return unwrap(data, "deliveryMethod")
    except MolonionError as e:
        return _err(e)


DELIVERY_METHOD_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  deliveryMethodLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_delivery_method_logs(
    company_id: int,
    delivery_method_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos métodos de entrega de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_method_id: opcional; filtra os logs de um método de entrega específico
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if delivery_method_id is not None:
        options["relatedId"] = delivery_method_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DELIVERY_METHOD_LOGS_QUERY, variables)
        return unwrap(data, "deliveryMethodLogs")
    except MolonionError as e:
        return _err(e)


DELIVERY_METHODS_QUERY = """
query ($companyId: Int!, $options: DeliveryMethodOptions) {
  deliveryMethods(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      deliveryMethodId
      name
      visible
      isDefault
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_delivery_methods(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os métodos de entrega configurados numa empresa, cada um com o nome
    (`name`), se está visível (`visible`), se é o método por omissão (`isDefault`) e se
    pode ser apagado (`deletable`). Para obter um único pelo seu ID usa
    `get_delivery_method`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DELIVERY_METHODS_QUERY, variables)
        return unwrap(data, "deliveryMethods")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Guias de remessa (documentos)
# ---------------------------------------------------------------------------
DELIVERY_NOTE_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  deliveryNote(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscountValue
      totalDiscountValue
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      expirationDate
      maturityDateDays
      maturityDateName
      yourReference
      ourReference
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      deliveryMethodName
      deliveryVehicleName
      deliveryVehicleLicensePlate
      deliveryLoadDate
      deliveryLoadAddress
      deliveryLoadCity
      deliveryLoadZipCode
      deliveryUnloadAddress
      deliveryUnloadCity
      deliveryUnloadZipCode
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_delivery_note(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma guia de remessa pelo seu ID de documento: dados do
    documento (número, série, data, estado, totais), dados da entidade/cliente
    (`entityName`, `entityVat`, morada), o estado de reconciliação (`reconciledValue`,
    `remainingReconciledValue`, `reconciliationPercentage`), os dados de vencimento
    (`expirationDate`, `maturityDateDays`, `maturityDateName`) e os dados de transporte
    (método de entrega, veículo/matrícula, datas e moradas de carga/descarga). As linhas
    de produtos, os impostos, o cliente completo, os documentos relacionados e os dados
    AT não são incluídos neste selection set — podem ser adicionados se necessário.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (guia de remessa) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(DELIVERY_NOTE_QUERY, variables)
        return unwrap(data, "deliveryNote")
    except MolonionError as e:
        return _err(e)


DELIVERY_NOTE_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  deliveryNoteGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_delivery_note_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma guia de remessa.
    Devolve `token`, `path` e `filename`, que se combinam para construir o URL de
    download do PDF. Nota: ao contrário de outras operações, não recebe `companyId` —
    apenas o `documentId`.

    Args:
        document_id: ID do documento (guia de remessa) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            DELIVERY_NOTE_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "deliveryNoteGetPDFToken")
    except MolonionError as e:
        return _err(e)


DELIVERY_NOTE_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  deliveryNoteGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_delivery_note_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar várias guias de remessa como um
    arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para construir o
    URL de download. O `full_path` identifica o ZIP a descarregar (caminho devolvido por
    uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(DELIVERY_NOTE_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "deliveryNoteGetZIPToken")
    except MolonionError as e:
        return _err(e)


DELIVERY_NOTE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  deliveryNoteLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_delivery_note_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às guias de remessa de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma guia de remessa específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DELIVERY_NOTE_LOGS_QUERY, variables)
        return unwrap(data, "deliveryNoteLogs")
    except MolonionError as e:
        return _err(e)


DELIVERY_NOTE_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  deliveryNoteMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_delivery_note_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de guias de remessa e o estado de
    entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para
    confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os logs
    detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_delivery_note_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DELIVERY_NOTE_MAIL_RECIPIENTS_QUERY, variables)
        return unwrap(data, "deliveryNoteMailRecipients")
    except MolonionError as e:
        return _err(e)


DELIVERY_NOTE_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  deliveryNoteMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_delivery_note_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de emails enviados de uma guia de remessa: para cada envio, o
    email, o conteúdo, a data (`createdAt`) e o `deliveryId`. Usa o `deliveryId` de um
    envio em `get_delivery_note_mail_recipients` para ver os destinatários e o estado de
    entrega desse envio.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (guia de remessa) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DELIVERY_NOTE_MAILS_HISTORY_QUERY, variables)
        return unwrap(data, "deliveryNoteMailsHistory")
    except MolonionError as e:
        return _err(e)


DELIVERY_NOTE_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  deliveryNoteNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_delivery_note_next_number(company_id: int, document_set_id: int) -> Any:
    """Obtém o próximo número disponível para uma guia de remessa numa dada série de
    documentos. Devolve `number` (o próximo número) e `name` (o nome da série). Útil
    antes de criar uma nova guia de remessa, para saber o número que lhe será atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(DELIVERY_NOTE_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "deliveryNoteNextNumber")
    except MolonionError as e:
        return _err(e)


DELIVERY_NOTE_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: DeliveryNoteOptions) {
  deliveryNoteRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_delivery_note_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as guias de remessa de uma entidade que podem ser relacionadas/ligadas a
    outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente) cujas guias de remessa relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DELIVERY_NOTE_RELATABLE_QUERY, variables)
        return unwrap(data, "deliveryNoteRelatable")
    except MolonionError as e:
        return _err(e)


DELIVERY_NOTES_QUERY = """
query ($companyId: Int!, $options: DeliveryNoteOptions) {
  deliveryNotes(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_delivery_notes(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as guias de remessa de uma empresa, com os campos principais de
    cada uma: número, data, série, entidade, valor total e estado. Para obter o detalhe
    completo de uma guia de remessa usa `get_delivery_note`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DELIVERY_NOTES_QUERY, variables)
        return unwrap(data, "deliveryNotes")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Documentos (genérico — qualquer tipo de documento)
# ---------------------------------------------------------------------------
# `document` devolve a interface `DocumentRead` (campos comuns a todos os tipos de
# documento); `__typename` identifica o tipo concreto. Os campos específicos de cada
# tipo obtêm-se com a tool dedicada (get_invoice, get_credit_note, …).
DOCUMENT_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  document(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      __typename
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      yourReference
      ourReference
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_document(company_id: int, document_id: int) -> Any:
    """Obtém um documento genérico pelo seu ID, seja qual for o tipo (fatura, nota de
    crédito, guia, recibo, etc.). Devolve os campos comuns a todos os documentos
    (interface `DocumentRead`): número, série, data, estado, totais, reconciliação, dados
    da entidade e hash. O campo `__typename` identifica o tipo concreto do documento.
    Para os campos específicos de um tipo usa a tool dedicada (ex. `get_credit_note`,
    `get_delivery_note`). As linhas de produtos e os impostos não são incluídos.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(DOCUMENT_QUERY, variables)
        return unwrap(data, "document")
    except MolonionError as e:
        return _err(e)


# NOTA: o nome da operação é capitalizado (`DocumentATCommunicationStatuses`).
DOCUMENT_AT_COMMUNICATION_STATUSES_QUERY = """
query ($companyId: Int!, $communicationType: [DocumentATCommunicationTypeEnum]) {
  DocumentATCommunicationStatuses(companyId: $companyId, communicationType: $communicationType) {
    errors { field msg }
    data {
      documentATCommunicationStatusId
      logDate
      actionType
      atReturnStatus
      atReturnCode
      atReturnMsg
      documentATId
      isRetriable
      isMarkableAsSolved
      isFAQRequired
    }
  }
}
"""


@mcp.tool()
async def list_document_at_communication_statuses(
    company_id: int,
    communication_type: list[str] | None = None,
) -> Any:
    """Lista o estado da comunicação de documentos com a Autoridade Tributária (AT) de
    uma empresa: para cada entrada, a data (`logDate`), o tipo de ação (`actionType`),
    o estado devolvido pela AT (`atReturnStatus`, `atReturnCode`, `atReturnMsg`), o
    identificador AT do documento (`documentATId`) e se a comunicação é repetível
    (`isRetriable`), marcável como resolvida (`isMarkableAsSolved`) ou exige FAQ
    (`isFAQRequired`). Útil para diagnosticar falhas de envio para a AT.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        communication_type: opcional; lista de tipos de comunicação a filtrar (valores
            do enum `DocumentATCommunicationTypeEnum`).
    """
    variables: dict[str, Any] = {"companyId": company_id}
    if communication_type is not None:
        variables["communicationType"] = communication_type
    try:
        data = await _client.query(
            DOCUMENT_AT_COMMUNICATION_STATUSES_QUERY, variables
        )
        return unwrap(data, "DocumentATCommunicationStatuses")
    except MolonionError as e:
        return _err(e)


DOCUMENT_EVENTS_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  documentEvents(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      eventId
      name
      isDraft
      isHandled
      documentId
      eventDate
      repetition
      repetitionValue
      monthlyValue
      weeklySunday
      weeklyMonday
      weeklyTuesday
      weeklyWednesday
      weeklyThursday
      weeklyFriday
      weeklySaturday
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_document_events(company_id: int, document_id: int) -> Any:
    """Lista os eventos associados a um documento (ex. lembretes de pagamento, tarefas de
    seguimento). Para cada evento: o nome, a data (`eventDate`), se está tratado
    (`isHandled`) ou em rascunho (`isDraft`) e a recorrência (`repetition`,
    `repetitionValue`, `monthlyValue` e os dias da semana `weekly*`). As ações do evento
    (`eventActions`) não são incluídas neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento cujos eventos se pretendem.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(DOCUMENT_EVENTS_QUERY, variables)
        return unwrap(data, "documentEvents")
    except MolonionError as e:
        return _err(e)


DOCUMENT_LINK_QUERY = """
query ($documentLinkId: String!) {
  documentLink(documentLinkId: $documentLinkId) {
    errors { field msg }
    data {
      documentLinkId
      expiracy
      file
      filename
      token
    }
  }
}
"""


@mcp.tool()
async def get_document_link(document_link_id: str) -> Any:
    """Obtém um link público partilhável de documento pelo seu ID — um URL de acesso
    só-de-leitura ao(s) documento(s) sem autenticação. Devolve a data de expiração
    (`expiracy`), o ficheiro/nome (`file`/`filename`) e o `token`. Nota: ao contrário da
    maioria das operações, não recebe `companyId` — apenas o `documentLinkId` (string).
    Os documentos associados e os dados da empresa não são incluídos neste selection set.

    Args:
        document_link_id: ID (string) do link de documento a obter.
    """
    try:
        data = await _client.query(
            DOCUMENT_LINK_QUERY, {"documentLinkId": document_link_id}
        )
        return unwrap(data, "documentLink")
    except MolonionError as e:
        return _err(e)


DOCUMENT_MAIL_MESSAGE_TEMPLATE_QUERY = """
query ($companyId: Int!, $documentMailMessageTemplateId: Int!) {
  documentMailMessageTemplate(companyId: $companyId, documentMailMessageTemplateId: $documentMailMessageTemplateId) {
    errors { field msg }
    data {
      documentMailMessageTemplateId
      name
      content
    }
  }
}
"""


@mcp.tool()
async def get_document_mail_message_template(
    company_id: int, document_mail_message_template_id: int
) -> Any:
    """Obtém um modelo (template) de mensagem de email para documentos pelo seu ID: o
    nome (`name`) e o conteúdo (`content`) da mensagem. Usado ao enviar documentos por
    email para reaproveitar texto.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_mail_message_template_id: ID do modelo de mensagem a obter.
    """
    variables = {
        "companyId": company_id,
        "documentMailMessageTemplateId": document_mail_message_template_id,
    }
    try:
        data = await _client.query(DOCUMENT_MAIL_MESSAGE_TEMPLATE_QUERY, variables)
        return unwrap(data, "documentMailMessageTemplate")
    except MolonionError as e:
        return _err(e)


DOCUMENT_MAIL_MESSAGE_TEMPLATE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  documentMailMessageTemplateLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_document_mail_message_template_logs(
    company_id: int,
    template_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos modelos de mensagem de email para
    documentos de uma empresa: criações, modificações e remoções. Cada entrada indica a
    operação (`operation`), os valores antigos/novos (`oldValues`/`newValues`), quem a
    fez (`userId`, `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        template_id: opcional; filtra os logs de um modelo específico (corresponde a
            `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if template_id is not None:
        options["relatedId"] = template_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DOCUMENT_MAIL_MESSAGE_TEMPLATE_LOGS_QUERY, variables)
        return unwrap(data, "documentMailMessageTemplateLogs")
    except MolonionError as e:
        return _err(e)


DOCUMENT_MAIL_MESSAGE_TEMPLATES_QUERY = """
query ($companyId: Int!, $options: DocumentMailMessageTemplateOptions) {
  documentMailMessageTemplates(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentMailMessageTemplateId
      name
      content
    }
  }
}
"""


@mcp.tool()
async def list_document_mail_message_templates(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os modelos (templates) de mensagem de email para documentos configurados
    numa empresa, cada um com o nome (`name`) e o conteúdo (`content`). Para obter um
    único pelo seu ID usa `get_document_mail_message_template`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DOCUMENT_MAIL_MESSAGE_TEMPLATES_QUERY, variables)
        return unwrap(data, "documentMailMessageTemplates")
    except MolonionError as e:
        return _err(e)


DOCUMENT_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!, $apiCode: ApiCode!) {
  documentNextNumber(companyId: $companyId, documentSetId: $documentSetId, apiCode: $apiCode) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_document_next_number(
    company_id: int, document_set_id: int, api_code: str
) -> Any:
    """Obtém o próximo número disponível para um documento numa dada série, para
    qualquer tipo de documento (versão genérica). Devolve `number` (o próximo número) e
    `name` (o nome da série). Ao contrário das versões por tipo (ex.
    `get_credit_note_next_number`), aqui o tipo de documento é indicado pelo `api_code`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
        api_code: código do tipo de documento (valor do enum `ApiCode`, ex.
            "invoices", "creditNotes", "deliveryNotes").
    """
    variables = {
        "companyId": company_id,
        "documentSetId": document_set_id,
        "apiCode": api_code,
    }
    try:
        data = await _client.query(DOCUMENT_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "documentNextNumber")
    except MolonionError as e:
        return _err(e)


DOCUMENT_PRINT_MODEL_QUERY = """
query ($documentPrintModelId: Int!) {
  documentPrintModel(documentPrintModelId: $documentPrintModelId) {
    errors { field msg }
    data {
      documentPrintModelId
      title
      description
      template
      css
      img
      visible
    }
  }
}
"""


@mcp.tool()
async def get_document_print_model(document_print_model_id: int) -> Any:
    """Obtém um modelo de impressão de documento pelo seu ID: título, descrição, o
    `template` (HTML) e o `css` que definem o layout do documento imprimido, a imagem
    (`img`) e a visibilidade (`visible`). Nota: ao contrário da maioria das operações,
    não recebe `companyId`. As traduções não são incluídas neste selection set.

    Args:
        document_print_model_id: ID do modelo de impressão a obter.
    """
    try:
        data = await _client.query(
            DOCUMENT_PRINT_MODEL_QUERY, {"documentPrintModelId": document_print_model_id}
        )
        return unwrap(data, "documentPrintModel")
    except MolonionError as e:
        return _err(e)


DOCUMENT_PRINT_MODEL_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  documentPrintModelLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_document_print_model_logs(
    company_id: int,
    document_print_model_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos modelos de impressão de documento de
    uma empresa: criações, modificações e remoções. Cada entrada indica a operação
    (`operation`), os valores antigos/novos (`oldValues`/`newValues`), quem a fez
    (`userId`, `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_print_model_id: opcional; filtra os logs de um modelo de impressão
            específico (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_print_model_id is not None:
        options["relatedId"] = document_print_model_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DOCUMENT_PRINT_MODEL_LOGS_QUERY, variables)
        return unwrap(data, "documentPrintModelLogs")
    except MolonionError as e:
        return _err(e)


DOCUMENT_PRINT_MODELS_QUERY = """
query ($options: DocumentPrintModelOptions) {
  documentPrintModels(options: $options) {
    errors { field msg }
    data {
      documentPrintModelId
      title
      description
      img
      visible
    }
  }
}
"""


@mcp.tool()
async def list_document_print_models(
    page: int | None = None, qty: int | None = None
) -> Any:
    """Lista os modelos de impressão de documento disponíveis na Moloni ON, cada um com o
    título, a descrição, a imagem (`img`) e a visibilidade (`visible`). Ao contrário da
    maioria das operações, não recebe `companyId`. O `template` (HTML) e o `css` de cada
    modelo são omitidos nesta listagem (são pesados) — usa `get_document_print_model`
    para os obter.

    Args:
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DOCUMENT_PRINT_MODELS_QUERY, variables)
        return unwrap(data, "documentPrintModels")
    except MolonionError as e:
        return _err(e)


# `documentRelatable` é a alternativa RECOMENDADA aos vários `*Relatable` deprecated.
# Devolve a interface `DocumentRead` (campos comuns); o tipo a procurar indica-se no
# `apiCode`.
DOCUMENT_RELATABLE_QUERY = """
query ($companyId: Int!, $apiCode: ApiCode!, $entityId: Int!, $options: DocumentOptions) {
  documentRelatable(companyId: $companyId, apiCode: $apiCode, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      __typename
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_document_relatable(
    company_id: int,
    api_code: str,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os documentos de uma entidade que podem ser relacionados/ligados a outro
    documento. Versão genérica e **recomendada** (substitui os `*Relatable` deprecated):
    o tipo de documento a procurar indica-se no `api_code`. Cada documento traz os campos
    comuns (número, data, série, total, estado) e o `__typename` identifica o tipo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        api_code: código do tipo de documento a procurar (valor do enum `ApiCode`, ex.
            "invoices", "billsOfLading", "creditNotes").
        entity_id: ID da entidade (cliente/fornecedor) cujos documentos relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {
        "companyId": company_id,
        "apiCode": api_code,
        "entityId": entity_id,
    }
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DOCUMENT_RELATABLE_QUERY, variables)
        return unwrap(data, "documentRelatable")
    except MolonionError as e:
        return _err(e)


DOCUMENTS_QUERY = """
query ($companyId: Int!, $options: DocumentOptions) {
  documents(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      __typename
      documentId
      documentTypeId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_documents(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) os documentos de uma empresa, de qualquer tipo (faturas, notas
    de crédito, guias, recibos, etc.). Cada documento traz os campos comuns (número,
    data, série, entidade, total, estado) e o `__typename` identifica o tipo concreto.
    Para o detalhe completo de um documento usa `get_document` (ou a tool dedicada ao
    tipo).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DOCUMENTS_QUERY, variables)
        return unwrap(data, "documents")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Séries de documentos (document sets)
# ---------------------------------------------------------------------------
DOCUMENT_SET_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  documentSet(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      documentSetId
      name
      visible
      isDefault
      companyId
      economicActivityClassificationCodeId
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_document_set(company_id: int, document_set_id: int) -> Any:
    """Obtém uma série de documentos de uma empresa pelo seu ID: o nome (`name`), se está
    visível (`visible`), se é a série por omissão (`isDefault`), o código de atividade
    económica associado (`economicActivityClassificationCodeId`) e se pode ser apagada
    (`deletable`). Os objetos ligados (empresa, template de identificação, tipos de
    documento, bloqueios) não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos a obter.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(DOCUMENT_SET_QUERY, variables)
        return unwrap(data, "documentSet")
    except MolonionError as e:
        return _err(e)


# NOTA: esta operação devolve uma LISTA de envelopes (como
# `customerHistoryUserSettingsTemplates`) — o `unwrap()` não se aplica; tratamos à mão.
DOCUMENT_SET_AT_CODES_VALIDATION_QUERY = """
query ($companyId: Int!, $codes: [String!], $documentSetId: Int) {
  documentSetATCodesAvailableValidation(companyId: $companyId, codes: $codes, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      code
      isAvailable
    }
  }
}
"""


@mcp.tool()
async def validate_document_set_at_codes_available(
    company_id: int,
    codes: list[str] | None = None,
    document_set_id: int | None = None,
) -> Any:
    """Valida se códigos de série da Autoridade Tributária (AT) estão disponíveis para
    uma série de documentos. Para cada código, devolve `code` e `isAvailable` (se ainda
    está livre para usar). Útil antes de configurar/comunicar uma série à AT.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        codes: opcional; lista de códigos AT a validar.
        document_set_id: opcional; ID da série de documentos em contexto.
    """
    variables: dict[str, Any] = {"companyId": company_id}
    if codes is not None:
        variables["codes"] = codes
    if document_set_id is not None:
        variables["documentSetId"] = document_set_id
    try:
        raw = await _client.query(DOCUMENT_SET_AT_CODES_VALIDATION_QUERY, variables)
        envelopes = (raw or {}).get("documentSetATCodesAvailableValidation") or []
        errs = [
            e for env in envelopes if env for e in (env.get("errors") or [])
        ]
        if errs:
            raise MolonionError(
                "A operação 'documentSetATCodesAvailableValidation' devolveu erros.",
                errors=errs,
            )
        return [t for env in envelopes if env for t in (env.get("data") or [])]
    except MolonionError as e:
        return _err(e)


# NOTA: o `data` do envelope é um escalar Boolean (resultado da validação).
DOCUMENT_SET_AT_CODE_VALIDATION_QUERY = """
query ($companyId: Int!, $documentTypeId: Int!, $code: String!) {
  documentSetATCodeValidation(companyId: $companyId, documentTypeId: $documentTypeId, code: $code) {
    errors { field msg }
    data
  }
}
"""


@mcp.tool()
async def validate_document_set_at_code(
    company_id: int, document_type_id: int, code: str
) -> Any:
    """Valida um único código de série da Autoridade Tributária (AT) para um tipo de
    documento. Devolve um booleano (`true` se o código é válido/disponível para esse
    tipo de documento).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_type_id: ID do tipo de documento.
        code: código AT da série a validar.
    """
    variables = {
        "companyId": company_id,
        "documentTypeId": document_type_id,
        "code": code,
    }
    try:
        data = await _client.query(DOCUMENT_SET_AT_CODE_VALIDATION_QUERY, variables)
        return unwrap(data, "documentSetATCodeValidation")
    except MolonionError as e:
        return _err(e)


DOCUMENT_SET_AT_STATUS_QUERY = """
query ($companyId: Int!, $documentSetATStatusId: Int!) {
  documentSetATStatus(companyId: $companyId, documentSetATStatusId: $documentSetATStatusId) {
    errors { field msg }
    data {
      documentSetATStatusId
      logDate
      communicationStatus
      actionType
      resultCode
      resultMsg
      documentSetId
      documentTypeId
      isRetriable
    }
  }
}
"""


@mcp.tool()
async def get_document_set_at_status(
    company_id: int, document_set_at_status_id: int
) -> Any:
    """Obtém o estado da comunicação de uma série de documentos com a Autoridade
    Tributária (AT) pelo seu ID: a data (`logDate`), o estado (`communicationStatus`), o
    tipo de ação (`actionType`), o resultado devolvido pela AT (`resultCode`,
    `resultMsg`), a série e tipo de documento (`documentSetId`, `documentTypeId`) e se a
    comunicação é repetível (`isRetriable`). Os objetos `documentSet` e `documentType`
    completos não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_at_status_id: ID do estado AT da série a obter.
    """
    variables = {
        "companyId": company_id,
        "documentSetATStatusId": document_set_at_status_id,
    }
    try:
        data = await _client.query(DOCUMENT_SET_AT_STATUS_QUERY, variables)
        return unwrap(data, "documentSetATStatus")
    except MolonionError as e:
        return _err(e)


DOCUMENT_SET_AT_STATUSES_QUERY = """
query ($companyId: Int!, $options: DocumentSetATStatusOptions) {
  documentSetATStatuses(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentSetATStatusId
      logDate
      communicationStatus
      actionType
      resultCode
      resultMsg
      documentSetId
      documentTypeId
      isRetriable
    }
  }
}
"""


@mcp.tool()
async def list_document_set_at_statuses(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de estados da comunicação de séries de documentos com a
    Autoridade Tributária (AT) de uma empresa, cada um com a data (`logDate`), o estado
    (`communicationStatus`), o tipo de ação (`actionType`), o resultado (`resultCode`,
    `resultMsg`), a série/tipo (`documentSetId`, `documentTypeId`) e se é repetível
    (`isRetriable`). Para obter um único pelo seu ID usa `get_document_set_at_status`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DOCUMENT_SET_AT_STATUSES_QUERY, variables)
        return unwrap(data, "documentSetATStatuses")
    except MolonionError as e:
        return _err(e)


DOCUMENT_SET_AT_STATUS_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  documentSetATStatusLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_document_set_at_status_logs(
    company_id: int,
    related_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos estados da comunicação de séries de
    documentos com a Autoridade Tributária (AT) de uma empresa. Cada entrada indica a
    operação (`operation`), os valores antigos/novos (`oldValues`/`newValues`), quem a
    fez (`userId`, `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        related_id: opcional; filtra os logs de um estado AT de série específico
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if related_id is not None:
        options["relatedId"] = related_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DOCUMENT_SET_AT_STATUS_LOGS_QUERY, variables)
        return unwrap(data, "documentSetATStatusLogs")
    except MolonionError as e:
        return _err(e)


DOCUMENT_SET_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  documentSetLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_document_set_logs(
    company_id: int,
    document_set_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às séries de documentos de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: opcional; filtra os logs de uma série específica (corresponde a
            `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_set_id is not None:
        options["relatedId"] = document_set_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DOCUMENT_SET_LOGS_QUERY, variables)
        return unwrap(data, "documentSetLogs")
    except MolonionError as e:
        return _err(e)


DOCUMENT_SETS_QUERY = """
query ($companyId: Int!, $options: DocumentSetOptions) {
  documentSets(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentSetId
      name
      visible
      isDefault
      companyId
      economicActivityClassificationCodeId
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_document_sets(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as séries de documentos configuradas numa empresa, cada uma com o nome
    (`name`), se está visível (`visible`), se é a série por omissão (`isDefault`) e o
    código de atividade económica associado. Para obter uma única pelo seu ID usa
    `get_document_set`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DOCUMENT_SETS_QUERY, variables)
        return unwrap(data, "documentSets")
    except MolonionError as e:
        return _err(e)


# NOTA: devolve uma LISTA de envelopes (cada um com `data: [DocumentSetRead]`) — o
# `unwrap()` não se aplica; tratamos à mão.
DOCUMENT_SETS_FOR_DOCUMENT_QUERY = """
query ($companyId: Int!, $documentTypeId: Int!) {
  documentSetsForDocument(companyId: $companyId, documentTypeId: $documentTypeId) {
    errors { field msg }
    data {
      documentSetId
      name
      visible
      isDefault
      companyId
      economicActivityClassificationCodeId
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_document_sets_for_document(
    company_id: int, document_type_id: int
) -> Any:
    """Lista as séries de documentos (numeração) disponíveis para um dado tipo de
    documento numa empresa. Cada série traz o nome (`name`), se é a série por omissão
    (`isDefault`) e se está visível (`visible`). Útil para escolher a série ao criar um
    documento de um tipo específico.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_type_id: ID do tipo de documento.
    """
    variables = {"companyId": company_id, "documentTypeId": document_type_id}
    try:
        raw = await _client.query(DOCUMENT_SETS_FOR_DOCUMENT_QUERY, variables)
        envelopes = (raw or {}).get("documentSetsForDocument") or []
        errs = [
            e for env in envelopes if env for e in (env.get("errors") or [])
        ]
        if errs:
            raise MolonionError(
                "A operação 'documentSetsForDocument' devolveu erros.",
                errors=errs,
            )
        return [t for env in envelopes if env for t in (env.get("data") or [])]
    except MolonionError as e:
        return _err(e)


DOCUMENT_SETS_FOR_DOCUMENTS_QUERY = """
query ($companyId: Int!, $documentTypeIds: [Int!]) {
  documentSetsForDocuments(companyId: $companyId, documentTypeIds: $documentTypeIds) {
    errors { field msg }
    data {
      documentTypeId
      documentSets {
        documentSetId
        name
        visible
        isDefault
        companyId
        economicActivityClassificationCodeId
        deletable
      }
    }
  }
}
"""


@mcp.tool()
async def list_document_sets_for_documents(
    company_id: int, document_type_ids: list[int]
) -> Any:
    """Lista as séries de documentos (numeração) disponíveis para vários tipos de
    documento de uma só vez. Devolve, para cada tipo (`documentTypeId`), a lista de
    séries (`documentSets`) disponíveis (nome, default, visível). Versão em lote de
    `list_document_sets_for_document`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_type_ids: lista de IDs de tipos de documento.
    """
    variables = {"companyId": company_id, "documentTypeIds": document_type_ids}
    try:
        data = await _client.query(DOCUMENT_SETS_FOR_DOCUMENTS_QUERY, variables)
        return unwrap(data, "documentSetsForDocuments")
    except MolonionError as e:
        return _err(e)


DOCUMENTS_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  documentsLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_documents_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos documentos de uma empresa, de qualquer
    tipo (versão genérica). Cada entrada indica a operação (`operation`), os valores
    antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`, `email`)
    e quando (`operationTime`). Para um tipo específico há tools dedicadas (ex.
    `get_credit_note_logs`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de um documento específico (corresponde a
            `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DOCUMENTS_LOGS_QUERY, variables)
        return unwrap(data, "documentsLogs")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Tipos de documento (tabela de referência global)
# ---------------------------------------------------------------------------
DOCUMENT_TYPE_QUERY = """
query ($documentTypeId: Int!) {
  documentType(documentTypeId: $documentTypeId) {
    errors { field msg }
    data {
      documentTypeId
      apiCode
      apiCodePlural
      saftDocCode
      group
      entityType
      title
      titlePlural
      salesOperator
      costsOperator
      isSelfPaid
      generatesHash
      useInPos
      visible
      canHaveOutOfSeqDate
      reconcilesBalances
      unreconcilable
      minCopies
      balanceMultiplier
      billingMultiplier
      cashflowMultiplier
      stockMultiplier
      vatMultiplier
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_document_type(document_type_id: int) -> Any:
    """Obtém um tipo de documento pelo seu ID — tabela de referência global (faturas,
    recibos, guias, etc.). Devolve o `apiCode` (usado noutras operações como
    `get_document_next_number`/`get_document_relatable`), o código SAF-T (`saftDocCode`),
    o título, o grupo e tipo de entidade, e várias regras fiscais/de comportamento
    (operador de vendas/custos, gera hash, multiplicadores de saldo/faturação/stock/IVA,
    etc.). Ao contrário da maioria das operações, não recebe `companyId`. As traduções e
    as conversões possíveis (`canConvertTo`) não são incluídas neste selection set.

    Args:
        document_type_id: ID do tipo de documento a obter.
    """
    try:
        data = await _client.query(
            DOCUMENT_TYPE_QUERY, {"documentTypeId": document_type_id}
        )
        return unwrap(data, "documentType")
    except MolonionError as e:
        return _err(e)


DOCUMENT_TYPES_QUERY = """
query ($options: DocumentTypeOptions) {
  documentTypes(options: $options) {
    errors { field msg }
    data {
      documentTypeId
      apiCode
      apiCodePlural
      saftDocCode
      group
      entityType
      title
      titlePlural
      salesOperator
      costsOperator
      isSelfPaid
      generatesHash
      useInPos
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_document_types(page: int | None = None, qty: int | None = None) -> Any:
    """Lista os tipos de documento disponíveis na Moloni ON — tabela de referência global
    (faturas, recibos, guias, etc.). Para cada tipo: o `documentTypeId`, o `apiCode`
    (usado noutras operações), o código SAF-T (`saftDocCode`), o título e o grupo. Ao
    contrário da maioria das operações, não recebe `companyId`. Para o detalhe completo
    (regras fiscais, multiplicadores) de um tipo usa `get_document_type`.

    Args:
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(DOCUMENT_TYPES_QUERY, variables)
        return unwrap(data, "documentTypes")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Códigos de atividade económica (CAE)
# ---------------------------------------------------------------------------
ECONOMIC_ACTIVITY_CODE_QUERY = """
query ($companyId: Int!, $economicActivityClassificationCodeId: Int!) {
  economicActivityClassificationCode(companyId: $companyId, economicActivityClassificationCodeId: $economicActivityClassificationCodeId) {
    errors { field msg }
    data {
      economicActivityClassificationCodeId
      code
      title
      isDefault
      companyId
    }
  }
}
"""


@mcp.tool()
async def get_economic_activity_classification_code(
    company_id: int, economic_activity_classification_code_id: int
) -> Any:
    """Obtém um código de atividade económica (CAE) de uma empresa pelo seu ID: o código
    (`code`), a descrição (`title`) e se é o CAE por omissão (`isDefault`). O objeto
    `company` ligado não é incluído neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        economic_activity_classification_code_id: ID do código CAE a obter.
    """
    variables = {
        "companyId": company_id,
        "economicActivityClassificationCodeId": economic_activity_classification_code_id,
    }
    try:
        data = await _client.query(ECONOMIC_ACTIVITY_CODE_QUERY, variables)
        return unwrap(data, "economicActivityClassificationCode")
    except MolonionError as e:
        return _err(e)


ECONOMIC_ACTIVITY_CODE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  economicActivityClassificationCodeLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_economic_activity_classification_code_logs(
    company_id: int,
    code_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos códigos de atividade económica (CAE)
    de uma empresa: criações, modificações e remoções. Cada entrada indica a operação
    (`operation`), os valores antigos/novos (`oldValues`/`newValues`), quem a fez
    (`userId`, `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        code_id: opcional; filtra os logs de um código CAE específico (corresponde a
            `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if code_id is not None:
        options["relatedId"] = code_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(ECONOMIC_ACTIVITY_CODE_LOGS_QUERY, variables)
        return unwrap(data, "economicActivityClassificationCodeLogs")
    except MolonionError as e:
        return _err(e)


ECONOMIC_ACTIVITY_CODES_QUERY = """
query ($companyId: Int!, $options: EconomicActivityClassificationCodeOptions) {
  economicActivityClassificationCodes(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      economicActivityClassificationCodeId
      code
      title
      isDefault
      companyId
    }
  }
}
"""


@mcp.tool()
async def list_economic_activity_classification_codes(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os códigos de atividade económica (CAE) configurados numa empresa, cada um
    com o código (`code`), a descrição (`title`) e se é o CAE por omissão (`isDefault`).
    Para obter um único pelo seu ID usa `get_economic_activity_classification_code`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(ECONOMIC_ACTIVITY_CODES_QUERY, variables)
        return unwrap(data, "economicActivityClassificationCodes")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Orçamentos (documentos)
# ---------------------------------------------------------------------------
ESTIMATE_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  estimate(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscountValue
      totalDiscountValue
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      expirationDate
      maturityDateDays
      maturityDateName
      yourReference
      ourReference
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      deliveryMethodName
      deliveryVehicleName
      deliveryVehicleLicensePlate
      deliveryLoadDate
      deliveryLoadAddress
      deliveryLoadCity
      deliveryLoadZipCode
      deliveryUnloadAddress
      deliveryUnloadCity
      deliveryUnloadZipCode
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_estimate(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de um orçamento pelo seu ID de documento: dados do documento
    (número, série, data, estado, totais), dados da entidade/cliente (`entityName`,
    `entityVat`, morada), o estado de reconciliação, os dados de validade/vencimento
    (`expirationDate`, `maturityDateDays`, `maturityDateName`) e os dados de transporte
    (método de entrega, veículo/matrícula, carga/descarga). As linhas de produtos, os
    impostos, o cliente completo, os documentos relacionados e os dados AT não são
    incluídos neste selection set — podem ser adicionados se necessário.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (orçamento) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(ESTIMATE_QUERY, variables)
        return unwrap(data, "estimate")
    except MolonionError as e:
        return _err(e)


ESTIMATE_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  estimateGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_estimate_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de um orçamento. Devolve
    `token`, `path` e `filename`, que se combinam para construir o URL de download do
    PDF. Nota: ao contrário de outras operações, não recebe `companyId` — apenas o
    `documentId`.

    Args:
        document_id: ID do documento (orçamento) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            ESTIMATE_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "estimateGetPDFToken")
    except MolonionError as e:
        return _err(e)


ESTIMATE_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  estimateGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_estimate_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar vários orçamentos como um
    arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para construir o
    URL de download. O `full_path` identifica o ZIP a descarregar (caminho devolvido por
    uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(ESTIMATE_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "estimateGetZIPToken")
    except MolonionError as e:
        return _err(e)


ESTIMATE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  estimateLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_estimate_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos orçamentos de uma empresa: criações,
    modificações e remoções. Cada entrada indica a operação (`operation`), os valores
    antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`, `email`)
    e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de um orçamento específico (corresponde a
            `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(ESTIMATE_LOGS_QUERY, variables)
        return unwrap(data, "estimateLogs")
    except MolonionError as e:
        return _err(e)


ESTIMATE_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  estimateMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_estimate_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de orçamentos e o estado de entrega
    de cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para confirmar
    a quem foi enviado o documento e se a entrega teve sucesso. Os logs detalhados de
    cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_estimate_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(ESTIMATE_MAIL_RECIPIENTS_QUERY, variables)
        return unwrap(data, "estimateMailRecipients")
    except MolonionError as e:
        return _err(e)


ESTIMATE_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  estimateMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_estimate_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de emails enviados de um orçamento: para cada envio, o email, o
    conteúdo, a data (`createdAt`) e o `deliveryId`. Usa o `deliveryId` de um envio em
    `get_estimate_mail_recipients` para ver os destinatários e o estado de entrega desse
    envio.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (orçamento) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(ESTIMATE_MAILS_HISTORY_QUERY, variables)
        return unwrap(data, "estimateMailsHistory")
    except MolonionError as e:
        return _err(e)


ESTIMATE_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  estimateNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_estimate_next_number(company_id: int, document_set_id: int) -> Any:
    """Obtém o próximo número disponível para um orçamento numa dada série de documentos.
    Devolve `number` (o próximo número) e `name` (o nome da série). Útil antes de criar
    um novo orçamento, para saber o número que lhe será atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(ESTIMATE_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "estimateNextNumber")
    except MolonionError as e:
        return _err(e)


ESTIMATE_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: EstimateOptions) {
  estimateRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_estimate_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os orçamentos de uma entidade que podem ser relacionados/ligados a outro
    documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente) cujos orçamentos relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(ESTIMATE_RELATABLE_QUERY, variables)
        return unwrap(data, "estimateRelatable")
    except MolonionError as e:
        return _err(e)


ESTIMATES_QUERY = """
query ($companyId: Int!, $options: EstimateOptions) {
  estimates(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      expirationDate
      documentSetName
      entityName
      entityVat
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_estimates(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) os orçamentos de uma empresa, com os campos principais de cada
    um: número, data, validade (`expirationDate`), série, entidade, valor total e estado.
    Para obter o detalhe completo de um orçamento usa `get_estimate`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(ESTIMATES_QUERY, variables)
        return unwrap(data, "estimates")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------------------
EVENT_QUERY = """
query ($companyId: Int!, $eventId: String!) {
  event(companyId: $companyId, eventId: $eventId) {
    errors { field msg }
    data {
      eventId
      name
      isDraft
      isHandled
      documentId
      eventDate
      repetition
      repetitionValue
      monthlyValue
      weeklySunday
      weeklyMonday
      weeklyTuesday
      weeklyWednesday
      weeklyThursday
      weeklyFriday
      weeklySaturday
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_event(company_id: int, event_id: str) -> Any:
    """Obtém um evento pelo seu ID (ex. lembrete de pagamento, tarefa de seguimento): o
    nome, a data (`eventDate`), se está tratado (`isHandled`) ou em rascunho (`isDraft`),
    o documento associado (`documentId`) e a recorrência (`repetition`, `repetitionValue`,
    `monthlyValue` e os dias da semana `weekly*`). Nota: o `event_id` é uma **string**. As
    ações do evento (`eventActions`) não são incluídas neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        event_id: ID (string) do evento a obter.
    """
    variables = {"companyId": company_id, "eventId": event_id}
    try:
        data = await _client.query(EVENT_QUERY, variables)
        return unwrap(data, "event")
    except MolonionError as e:
        return _err(e)


EVENT_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  eventLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_event_logs(
    company_id: int,
    related_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos eventos de uma empresa: criações,
    modificações e remoções. Cada entrada indica a operação (`operation`), os valores
    antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`, `email`)
    e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        related_id: opcional; filtra os logs de um evento específico (corresponde a
            `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if related_id is not None:
        options["relatedId"] = related_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(EVENT_LOGS_QUERY, variables)
        return unwrap(data, "eventLogs")
    except MolonionError as e:
        return _err(e)


EVENTS_QUERY = """
query ($companyId: Int!, $options: EventOptions) {
  events(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      eventId
      name
      isDraft
      isHandled
      documentId
      eventDate
      repetition
      repetitionValue
      monthlyValue
      weeklySunday
      weeklyMonday
      weeklyTuesday
      weeklyWednesday
      weeklyThursday
      weeklyFriday
      weeklySaturday
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_events(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os eventos de uma empresa (lembretes, tarefas de seguimento, etc.), cada um
    com o nome, a data (`eventDate`), se está tratado (`isHandled`), o documento
    associado (`documentId`) e a recorrência (`repetition`, dias da semana `weekly*`).
    Para obter um único pelo seu ID usa `get_event`; para os de um documento específico
    usa `get_document_events`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(EVENTS_QUERY, variables)
        return unwrap(data, "events")
    except MolonionError as e:
        return _err(e)


EVENTS_BY_DATE_QUERY = """
query ($companyId: Int!, $date: DateTime, $options: EventOptions) {
  eventsByDate(companyId: $companyId, date: $date, options: $options) {
    errors { field msg }
    data {
      eventId
      name
      isDraft
      isHandled
      documentId
      eventDate
      repetition
      repetitionValue
      monthlyValue
      weeklySunday
      weeklyMonday
      weeklyTuesday
      weeklyWednesday
      weeklyThursday
      weeklyFriday
      weeklySaturday
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_events_by_date(
    company_id: int,
    date: str | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os eventos de uma empresa numa data específica (tendo em conta a
    recorrência) — útil para um calendário/agenda. Cada evento traz o nome, a data, se
    está tratado (`isHandled`), o documento associado e a recorrência.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        date: opcional; data (ISO 8601, ex. "2026-06-30") cujos eventos se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if date is not None:
        variables["date"] = date
    if options:
        variables["options"] = options
    try:
        data = await _client.query(EVENTS_BY_DATE_QUERY, variables)
        return unwrap(data, "eventsByDate")
    except MolonionError as e:
        return _err(e)


EVENTS_MONTH_BY_DATE_QUERY = """
query ($companyId: Int!, $date: DateTime) {
  eventsMonthByDate(companyId: $companyId, date: $date) {
    errors { field msg }
    data {
      eventId
      name
      isDraft
      isHandled
      documentId
      eventDate
      repetition
      repetitionValue
      monthlyValue
      weeklySunday
      weeklyMonday
      weeklyTuesday
      weeklyWednesday
      weeklyThursday
      weeklyFriday
      weeklySaturday
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_events_month_by_date(
    company_id: int, date: str | None = None
) -> Any:
    """Lista os eventos de uma empresa para o mês inteiro da data indicada (tendo em
    conta a recorrência) — útil para uma vista mensal de calendário. Cada evento traz o
    nome, a data, se está tratado (`isHandled`), o documento associado e a recorrência.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        date: opcional; data (ISO 8601, ex. "2026-06-15") cujo mês se pretende.
    """
    variables: dict[str, Any] = {"companyId": company_id}
    if date is not None:
        variables["date"] = date
    try:
        data = await _client.query(EVENTS_MONTH_BY_DATE_QUERY, variables)
        return unwrap(data, "eventsMonthByDate")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Zonas fiscais (definições de impostos)
# ---------------------------------------------------------------------------
FISCAL_ZONES_TAX_SETTINGS_QUERY = """
query ($options: FiscalZoneTaxSettingsOptions, $includeGeneric: Boolean) {
  fiscalZonesTaxSettings(options: $options, includeGeneric: $includeGeneric) {
    errors { field msg }
    data {
      fiscalZone
      hasFinancialDiscount
      requireCustomerAddress
      hasCommercialRegistryOffice
      hasCommercialRegistryNumber
      availabilityPhraseMandatory
      allowZeroValue
      allowVatZeroValue
      defaultMaxOldness
      additionalOutOfSeqDate
      nullifiedAllowOutOfSeqDate
      extraEditableDocuments
      forbiddenDocumentTypeIds
    }
  }
}
"""


@mcp.tool()
async def list_fiscal_zones_tax_settings(
    include_generic: bool | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as definições de impostos por zona fiscal da Moloni ON — regras que governam
    a faturação em cada zona (ex. PT, PT-AC, PT-MA, ES, …). Para cada zona (`fiscalZone`):
    se permite desconto financeiro (`hasFinancialDiscount`), se exige morada do cliente
    (`requireCustomerAddress`), se permite valor/IVA zero (`allowZeroValue`,
    `allowVatZeroValue`), a antiguidade máxima de datas (`defaultMaxOldness`) e os tipos
    de documento proibidos (`forbiddenDocumentTypeIds`). Ao contrário da maioria das
    operações, não recebe `companyId`. Os objetos ligados (tipos de financiamento, modos,
    flags, isenções, limites) não são incluídos neste selection set.

    Args:
        include_generic: opcional; inclui também as definições genéricas (não específicas
            de uma zona).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {}
    if options:
        variables["options"] = options
    if include_generic is not None:
        variables["includeGeneric"] = include_generic
    try:
        data = await _client.query(FISCAL_ZONES_TAX_SETTINGS_QUERY, variables)
        return unwrap(data, "fiscalZonesTaxSettings")
    except MolonionError as e:
        return _err(e)


# NOTA: ao contrário da maioria, esta query devolve o objeto DIRETAMENTE (sem envelope
# `{errors, data}`) — não se aplica `unwrap()`.
FISCAL_ZONE_TAX_SETTINGS_QUERY = """
query ($companyId: Int!, $fiscalZone: String!) {
  fiscalZoneTaxSettings(companyId: $companyId, fiscalZone: $fiscalZone) {
    fiscalZone
    hasFinancialDiscount
    requireCustomerAddress
    hasCommercialRegistryOffice
    hasCommercialRegistryNumber
    availabilityPhraseMandatory
    allowZeroValue
    allowVatZeroValue
    defaultMaxOldness
    additionalOutOfSeqDate
    nullifiedAllowOutOfSeqDate
    extraEditableDocuments
    forbiddenDocumentTypeIds
  }
}
"""


@mcp.tool()
async def get_fiscal_zone_tax_settings(company_id: int, fiscal_zone: str) -> Any:
    """Obtém as definições de impostos de uma zona fiscal específica (ex. "PT", "PT-AC",
    "ES") para uma empresa. Devolve as regras de faturação dessa zona: desconto
    financeiro, morada do cliente obrigatória, valor/IVA zero permitido, antiguidade
    máxima de datas e tipos de documento proibidos. Se a empresa não tiver definições
    próprias para a zona, são devolvidas as definições gerais. Os objetos ligados (tipos
    de financiamento, isenções, limites) não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        fiscal_zone: código da zona fiscal (ex. "PT", "PT-AC", "PT-MA", "ES").
    """
    variables = {"companyId": company_id, "fiscalZone": fiscal_zone}
    try:
        data = await _client.query(FISCAL_ZONE_TAX_SETTINGS_QUERY, variables)
        return (data or {}).get("fiscalZoneTaxSettings")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Zonas geográficas
# ---------------------------------------------------------------------------
GEOGRAPHIC_ZONE_QUERY = """
query ($companyId: Int!, $geographicZoneId: Int!) {
  geographicZone(companyId: $companyId, geographicZoneId: $geographicZoneId) {
    errors { field msg }
    data {
      geographicZoneId
      name
      abbreviation
      notes
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_geographic_zone(company_id: int, geographic_zone_id: int) -> Any:
    """Obtém uma zona geográfica de uma empresa pelo seu ID: o nome (`name`), a
    abreviatura (`abbreviation`), notas e a visibilidade. As zonas geográficas usam-se
    para segmentar clientes/documentos por região. O objeto `company` ligado não é
    incluído neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        geographic_zone_id: ID da zona geográfica a obter.
    """
    variables = {"companyId": company_id, "geographicZoneId": geographic_zone_id}
    try:
        data = await _client.query(GEOGRAPHIC_ZONE_QUERY, variables)
        return unwrap(data, "geographicZone")
    except MolonionError as e:
        return _err(e)


GEOGRAPHIC_ZONE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  geographicZoneLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_geographic_zone_logs(
    company_id: int,
    geographic_zone_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às zonas geográficas de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        geographic_zone_id: opcional; filtra os logs de uma zona geográfica específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if geographic_zone_id is not None:
        options["relatedId"] = geographic_zone_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(GEOGRAPHIC_ZONE_LOGS_QUERY, variables)
        return unwrap(data, "geographicZoneLogs")
    except MolonionError as e:
        return _err(e)


GEOGRAPHIC_ZONES_QUERY = """
query ($companyId: Int!, $options: GeographicZoneOptions) {
  geographicZones(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      geographicZoneId
      name
      abbreviation
      notes
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_geographic_zones(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as zonas geográficas configuradas numa empresa, cada uma com o nome
    (`name`), a abreviatura (`abbreviation`) e notas. Usadas para segmentar
    clientes/documentos por região. Para obter uma única pelo seu ID usa
    `get_geographic_zone`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(GEOGRAPHIC_ZONES_QUERY, variables)
        return unwrap(data, "geographicZones")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# AT / Inventário (tokens de ficheiro)
# ---------------------------------------------------------------------------
AT_INVENTORY_FILE_TOKEN_QUERY = """
query ($companyId: Int!, $path: String!) {
  getATInventoryFileToken(companyId: $companyId, path: $path) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_at_inventory_file_token(company_id: int, path: str) -> Any:
    """Gera um token temporário e seguro para descarregar o ficheiro de inventário para a
    Autoridade Tributária (AT) — o ficheiro XML de comunicação de inventário. Devolve
    `token`, `path` e `filename`, que se combinam para construir o URL de download. O
    `path` identifica o ficheiro a descarregar (caminho devolvido por uma operação de
    geração do inventário).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        path: caminho do ficheiro de inventário a descarregar.
    """
    variables = {"companyId": company_id, "path": path}
    try:
        data = await _client.query(AT_INVENTORY_FILE_TOKEN_QUERY, variables)
        return unwrap(data, "getATInventoryFileToken")
    except MolonionError as e:
        return _err(e)


# Empresa por slug — mesmo subconjunto curado de CompanyRead que `get_company`.
COMPANY_BY_SLUG_QUERY = """
query ($slug: String!) {
  getCompanyBySlug(slug: $slug) {
    errors { field msg }
    data {
      companyId
      name
      slug
      vat
      email
      address
      city
      zipCode
      phone
      fax
      website
      countryId
      isConfirmed
      visible
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_company_by_slug(slug: str) -> Any:
    """Obtém uma empresa pelo seu `slug` (identificador textual usado no URL), em vez do
    ID numérico. Devolve o subconjunto de identificação/contacto (nome, NIF, morada,
    contactos). Ao contrário de `get_company`, não recebe `companyId` — útil quando só se
    conhece o slug. Para o detalhe completo por ID usa `get_company`.

    Args:
        slug: identificador textual (slug) da empresa.
    """
    try:
        data = await _client.query(COMPANY_BY_SLUG_QUERY, {"slug": slug})
        return unwrap(data, "getCompanyBySlug")
    except MolonionError as e:
        return _err(e)


CUSTOMER_GDPR_FILE_TOKEN_QUERY = """
query ($companyId: Int!, $customerId: Int!) {
  getCustomerGdprFileToken(companyId: $companyId, customerId: $customerId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_customer_gdpr_file_token(company_id: int, customer_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o ficheiro de RGPD (GDPR)
    associado a um cliente. Devolve `token`, `path` e `filename`, que se combinam para
    construir o URL de download do ficheiro.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        customer_id: ID do cliente cujo ficheiro RGPD se pretende.
    """
    variables = {"companyId": company_id, "customerId": customer_id}
    try:
        data = await _client.query(CUSTOMER_GDPR_FILE_TOKEN_QUERY, variables)
        return unwrap(data, "getCustomerGdprFileToken")
    except MolonionError as e:
        return _err(e)


CUSTOMER_RELATED_DOCUMENTS_QUERY = """
query ($companyId: Int!, $customerId: Int!, $options: CustomerRelatedDocumentsOptions) {
  getCustomerRelatedDocuments(companyId: $companyId, customerId: $customerId, options: $options) {
    errors { field msg }
    data {
      documentId
      documentSetName
      number
      date
      year
      totalValue
      reconciledValue
      reconciliationPercentage
      status
      suspended
      nullified
      deletable
      pdfExport
    }
  }
}
"""


@mcp.tool()
async def list_customer_related_documents(
    company_id: int,
    customer_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os documentos associados a um cliente (faturas, recibos, etc.), com os
    campos principais de cada um: número, data, série, valor total, valor reconciliado e
    estado. Útil para ver o histórico documental de um cliente. Os objetos ligados (tipo
    de documento, vendedor, etc.) não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        customer_id: ID do cliente cujos documentos relacionados se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "customerId": customer_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(CUSTOMER_RELATED_DOCUMENTS_QUERY, variables)
        return unwrap(data, "getCustomerRelatedDocuments")
    except MolonionError as e:
        return _err(e)


DOCUMENT_ATTACHMENT_TOKEN_QUERY = """
query ($companyId: Int!, $apiCodePlural: String!, $documentId: Int!) {
  getDocumentAttachmentToken(companyId: $companyId, apiCodePlural: $apiCodePlural, documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_document_attachment_token(
    company_id: int, api_code_plural: str, document_id: int
) -> Any:
    """Gera um token temporário e seguro para descarregar o ficheiro de anexo de um
    documento. Devolve `token`, `path` e `filename`, que se combinam para construir o URL
    de download. O tipo de documento indica-se pelo `api_code_plural`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        api_code_plural: código (plural) do tipo de documento (ex. "invoices",
            "creditNotes"; obtém-se via `get_document_type`/`list_document_types`).
        document_id: ID do documento cujo anexo se pretende.
    """
    variables = {
        "companyId": company_id,
        "apiCodePlural": api_code_plural,
        "documentId": document_id,
    }
    try:
        data = await _client.query(DOCUMENT_ATTACHMENT_TOKEN_QUERY, variables)
        return unwrap(data, "getDocumentAttachmentToken")
    except MolonionError as e:
        return _err(e)


EDI_XML_TOKEN_QUERY = """
query ($companyId: Int!, $path: String!) {
  getEDIXMLToken(companyId: $companyId, path: $path) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_edi_xml_token(company_id: int, path: str) -> Any:
    """Gera um token temporário e seguro para descarregar um ficheiro XML de EDI
    (Electronic Data Interchange) de um documento. Devolve `token`, `path` e `filename`,
    que se combinam para construir o URL de download. O `path` identifica o ficheiro a
    descarregar.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        path: caminho do ficheiro XML de EDI a descarregar.
    """
    variables = {"companyId": company_id, "path": path}
    try:
        data = await _client.query(EDI_XML_TOKEN_QUERY, variables)
        return unwrap(data, "getEDIXMLToken")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Famílias (taxonomia de canais/marketplaces)
# ---------------------------------------------------------------------------
FAMILY_QUERY = """
query ($channel: String!, $defaultLanguageId: Int!, $itemId: String, $parentId: String, $companyId: Int) {
  getFamily(channel: $channel, defaultLanguageId: $defaultLanguageId, itemId: $itemId, parentId: $parentId, companyId: $companyId) {
    errors { field msg }
    data {
      id
      title
      channel
      channelTitle
    }
  }
}
"""


@mcp.tool()
async def get_family(
    channel: str,
    default_language_id: int,
    item_id: str | None = None,
    parent_id: str | None = None,
    company_id: int | None = None,
) -> Any:
    """Obtém uma família da taxonomia de um canal/marketplace (ex. categorias de produto
    de um canal de venda externo). Devolve o `id`, o título (`title`), o canal (`channel`)
    e o título do canal (`channelTitle`). Pode navegar a árvore via `parent_id`.

    Args:
        channel: identificador do canal/marketplace.
        default_language_id: ID do idioma para os títulos.
        item_id: opcional; ID da família a obter.
        parent_id: opcional; ID da família-pai (para listar os filhos).
        company_id: opcional; ID da empresa (obtém-se via `me`).
    """
    variables: dict[str, Any] = {
        "channel": channel,
        "defaultLanguageId": default_language_id,
    }
    if item_id is not None:
        variables["itemId"] = item_id
    if parent_id is not None:
        variables["parentId"] = parent_id
    if company_id is not None:
        variables["companyId"] = company_id
    try:
        data = await _client.query(FAMILY_QUERY, variables)
        return unwrap(data, "getFamily")
    except MolonionError as e:
        return _err(e)


IMPORT_SHEET_ERRORS_TOKEN_QUERY = """
query ($companyId: Int!, $sheetId: String!) {
  getImportSheetErrorsToken(companyId: $companyId, sheetId: $sheetId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_import_sheet_errors_token(company_id: int, sheet_id: str) -> Any:
    """Gera um token temporário e seguro para descarregar o ficheiro de erros de uma
    folha de importação (os erros detetados ao importar uma folha de cálculo). Devolve
    `token`, `path` e `filename`, que se combinam para construir o URL de download.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        sheet_id: ID (string) da folha de importação cujos erros se pretendem.
    """
    variables = {"companyId": company_id, "sheetId": sheet_id}
    try:
        data = await _client.query(IMPORT_SHEET_ERRORS_TOKEN_QUERY, variables)
        return unwrap(data, "getImportSheetErrorsToken")
    except MolonionError as e:
        return _err(e)


IMPORT_SHEET_WARNINGS_TOKEN_QUERY = """
query ($companyId: Int!, $sheetId: String!) {
  getImportSheetWarningsToken(companyId: $companyId, sheetId: $sheetId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_import_sheet_warnings_token(company_id: int, sheet_id: str) -> Any:
    """Gera um token temporário e seguro para descarregar o ficheiro de avisos de uma
    folha de importação (os avisos não-bloqueantes detetados ao importar uma folha de
    cálculo). Devolve `token`, `path` e `filename`, que se combinam para construir o URL
    de download.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        sheet_id: ID (string) da folha de importação cujos avisos se pretendem.
    """
    variables = {"companyId": company_id, "sheetId": sheet_id}
    try:
        data = await _client.query(IMPORT_SHEET_WARNINGS_TOKEN_QUERY, variables)
        return unwrap(data, "getImportSheetWarningsToken")
    except MolonionError as e:
        return _err(e)


IMPORT_TOKEN_QUERY = """
query ($companyId: Int!, $importJobId: String!) {
  getImportToken(companyId: $companyId, importJobId: $importJobId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_import_token(company_id: int, import_job_id: str) -> Any:
    """Gera um token temporário e seguro para descarregar o ficheiro importado de um
    trabalho de importação. Devolve `token`, `path` e `filename`, que se combinam para
    construir o URL de download.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        import_job_id: ID (string) do trabalho de importação.
    """
    variables = {"companyId": company_id, "importJobId": import_job_id}
    try:
        data = await _client.query(IMPORT_TOKEN_QUERY, variables)
        return unwrap(data, "getImportToken")
    except MolonionError as e:
        return _err(e)


GET_PDF_TOKEN_QUERY = """
query ($companyId: Int!, $request: String!, $fullPath: String!) {
  getPDFToken(companyId: $companyId, request: $request, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_pdf_token(company_id: int, request: str, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar um ficheiro PDF (versão
    genérica). Devolve `token`, `path` e `filename`, que se combinam para construir o URL
    de download. O `request` identifica o tipo de pedido e o `full_path` o ficheiro.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        request: identificador do pedido/tipo de PDF.
        full_path: caminho completo do ficheiro PDF a descarregar.
    """
    variables = {"companyId": company_id, "request": request, "fullPath": full_path}
    try:
        data = await _client.query(GET_PDF_TOKEN_QUERY, variables)
        return unwrap(data, "getPDFToken")
    except MolonionError as e:
        return _err(e)


POSSIBLE_DOCUMENTS_QUERY = """
query ($companyId: Int!, $type: Int!, $options: PossibleDocumentsOptions) {
  getPossibleDocuments(companyId: $companyId, type: $type, options: $options) {
    errors { field msg }
    data {
      __typename
      documentId
      documentTypeId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      reconciledValue
      remainingReconciledValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_possible_documents(
    company_id: int,
    remittance_type: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os documentos elegíveis para inclusão numa remessa bancária (SEPA),
    filtrados pela categoria da remessa (débito direto ou transferência a crédito). Cada
    documento traz os campos comuns (número, data, série, entidade, total, valor por
    reconciliar) e o `__typename` identifica o tipo. Útil ao montar uma remessa.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        remittance_type: categoria da remessa (inteiro; débito direto vs. transferência).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "type": remittance_type}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(POSSIBLE_DOCUMENTS_QUERY, variables)
        return unwrap(data, "getPossibleDocuments")
    except MolonionError as e:
        return _err(e)


SAFT_IMPORTER_ERRORS_FILE_TOKEN_QUERY = """
query ($companyId: Int!, $jobId: String!) {
  getSAFTImporterErrorsFileToken(companyId: $companyId, jobId: $jobId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_saft_importer_errors_file_token(company_id: int, job_id: str) -> Any:
    """Gera um token temporário e seguro para descarregar o ficheiro de erros de um
    trabalho de importação SAF-T (Standard Audit File for Tax). Devolve `token`, `path`
    e `filename`, que se combinam para construir o URL de download.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        job_id: ID (string) do trabalho de importação SAF-T.
    """
    variables = {"companyId": company_id, "jobId": job_id}
    try:
        data = await _client.query(SAFT_IMPORTER_ERRORS_FILE_TOKEN_QUERY, variables)
        return unwrap(data, "getSAFTImporterErrorsFileToken")
    except MolonionError as e:
        return _err(e)


SAFT_IMPORTER_WARNINGS_FILE_TOKEN_QUERY = """
query ($companyId: Int!, $jobId: String!) {
  getSAFTImporterWarningsFileToken(companyId: $companyId, jobId: $jobId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_saft_importer_warnings_file_token(company_id: int, job_id: str) -> Any:
    """Gera um token temporário e seguro para descarregar o ficheiro de avisos de um
    trabalho de importação SAF-T (Standard Audit File for Tax). Devolve `token`, `path`
    e `filename`, que se combinam para construir o URL de download.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        job_id: ID (string) do trabalho de importação SAF-T.
    """
    variables = {"companyId": company_id, "jobId": job_id}
    try:
        data = await _client.query(SAFT_IMPORTER_WARNINGS_FILE_TOKEN_QUERY, variables)
        return unwrap(data, "getSAFTImporterWarningsFileToken")
    except MolonionError as e:
        return _err(e)


SAFT_IMPORT_TOKEN_QUERY = """
query ($companyId: Int!, $jobId: String!) {
  getSaftImportToken(companyId: $companyId, jobId: $jobId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_saft_import_token(company_id: int, job_id: str) -> Any:
    """Gera um token temporário e seguro para descarregar o ficheiro SAF-T (Standard
    Audit File for Tax) previamente importado num trabalho de importação. Devolve
    `token`, `path` e `filename`, que se combinam para construir o URL de download.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        job_id: ID (string) do trabalho de importação SAF-T.
    """
    variables = {"companyId": company_id, "jobId": job_id}
    try:
        data = await _client.query(SAFT_IMPORT_TOKEN_QUERY, variables)
        return unwrap(data, "getSaftImportToken")
    except MolonionError as e:
        return _err(e)


SAFT_XML_TOKEN_QUERY = """
query ($companyId: Int!, $path: String!) {
  getSAFTXMLToken(companyId: $companyId, path: $path) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_saft_xml_token(company_id: int, path: str) -> Any:
    """Gera um token temporário e seguro para descarregar o ficheiro XML SAF-T(PT) de uma
    empresa (o ficheiro de auditoria fiscal para a AT). Devolve `token`, `path` e
    `filename`, que se combinam para construir o URL de download. O `path` identifica o
    ficheiro a descarregar (caminho devolvido por uma operação de geração do SAF-T).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        path: caminho do ficheiro SAF-T a descarregar.
    """
    variables = {"companyId": company_id, "path": path}
    try:
        data = await _client.query(SAFT_XML_TOKEN_QUERY, variables)
        return unwrap(data, "getSAFTXMLToken")
    except MolonionError as e:
        return _err(e)


SALESPERSON_RELATED_DOCUMENTS_QUERY = """
query ($companyId: Int!, $salespersonId: Int!, $options: SalespersonRelatedDocumentsOptions) {
  getSalespersonRelatedDocuments(companyId: $companyId, salespersonId: $salespersonId, options: $options) {
    errors { field msg }
    data {
      documentId
      documentSetName
      number
      date
      year
      totalValue
      grossValue
      totalDiscountValue
      salespersonCommission
      reconciledValue
      reconciliationPercentage
      status
      suspended
      nullified
      deletable
      pdfExport
      entityVat
      entityName
    }
  }
}
"""


@mcp.tool()
async def list_salesperson_related_documents(
    company_id: int,
    salesperson_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os documentos associados a um vendedor (salesperson), com os campos
    principais de cada um: número, data, série, valores (total, bruto, desconto) e, em
    particular, a comissão do vendedor (`salespersonCommission`). Útil para apurar
    comissões. Os objetos ligados (cliente, tipo de documento, etc.) não são incluídos
    neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        salesperson_id: ID do vendedor cujos documentos se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {
        "companyId": company_id,
        "salespersonId": salesperson_id,
    }
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SALESPERSON_RELATED_DOCUMENTS_QUERY, variables)
        return unwrap(data, "getSalespersonRelatedDocuments")
    except MolonionError as e:
        return _err(e)


SUPPLIER_RELATED_DOCUMENTS_QUERY = """
query ($companyId: Int!, $supplierId: Int!, $options: SupplierRelatedDocumentsOptions) {
  getSupplierRelatedDocuments(companyId: $companyId, supplierId: $supplierId, options: $options) {
    errors { field msg }
    data {
      documentId
      documentSetName
      number
      date
      year
      totalValue
      reconciledValue
      reconciliationPercentage
      status
      suspended
      nullified
      deletable
      pdfExport
      entityVat
      entityName
    }
  }
}
"""


@mcp.tool()
async def list_supplier_related_documents(
    company_id: int,
    supplier_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os documentos associados a um fornecedor (faturas de compra, etc.), com os
    campos principais de cada um: número, data, série, valor total, valor reconciliado e
    estado. Útil para ver o histórico documental de um fornecedor. Os objetos ligados
    (tipo de documento, etc.) não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        supplier_id: ID do fornecedor cujos documentos se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "supplierId": supplier_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SUPPLIER_RELATED_DOCUMENTS_QUERY, variables)
        return unwrap(data, "getSupplierRelatedDocuments")
    except MolonionError as e:
        return _err(e)


GET_XLSX_TOKEN_QUERY = """
query ($companyId: Int!, $request: String!, $fullPath: String!) {
  getXLSXToken(companyId: $companyId, request: $request, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_xlsx_token(company_id: int, request: str, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar um ficheiro XLSX (Excel).
    Devolve `token`, `path` e `filename`, que se combinam para construir o URL de
    download. O `request` identifica o tipo de pedido e o `full_path` o ficheiro.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        request: identificador do pedido/tipo de XLSX.
        full_path: caminho completo do ficheiro XLSX a descarregar.
    """
    variables = {"companyId": company_id, "request": request, "fullPath": full_path}
    try:
        data = await _client.query(GET_XLSX_TOKEN_QUERY, variables)
        return unwrap(data, "getXLSXToken")
    except MolonionError as e:
        return _err(e)


GET_XML_TOKEN_QUERY = """
query ($companyId: Int!, $request: String!, $fullPath: String!) {
  getXMLToken(companyId: $companyId, request: $request, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_xml_token(company_id: int, request: str, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar um ficheiro XML (versão
    genérica). Devolve `token`, `path` e `filename`, que se combinam para construir o URL
    de download. O `request` identifica o tipo de pedido e o `full_path` o ficheiro.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        request: identificador do pedido/tipo de XML.
        full_path: caminho completo do ficheiro XML a descarregar.
    """
    variables = {"companyId": company_id, "request": request, "fullPath": full_path}
    try:
        data = await _client.query(GET_XML_TOKEN_QUERY, variables)
        return unwrap(data, "getXMLToken")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Webhooks (hooks)
# ---------------------------------------------------------------------------
HOOK_QUERY = """
query ($companyId: Int!, $hookId: String!) {
  hook(companyId: $companyId, hookId: $hookId) {
    errors { field msg }
    data {
      hookId
      name
      url
      model
      operation
    }
  }
}
"""


@mcp.tool()
async def get_hook(company_id: int, hook_id: str) -> Any:
    """Obtém um webhook de uma empresa pelo seu ID: o nome (`name`), o URL de callback
    (`url`) e os gatilhos — o(s) modelo(s) (`model`, ex. documento, cliente) e a(s)
    operação(ões) (`operation`, ex. criação, alteração) que disparam o webhook. Nota: o
    `hook_id` é uma **string**.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        hook_id: ID (string) do webhook a obter.
    """
    variables = {"companyId": company_id, "hookId": hook_id}
    try:
        data = await _client.query(HOOK_QUERY, variables)
        return unwrap(data, "hook")
    except MolonionError as e:
        return _err(e)


HOOK_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  hookLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_hook_logs(
    company_id: int,
    related_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos webhooks de uma empresa: criações,
    modificações e remoções. Cada entrada indica a operação (`operation`), os valores
    antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`, `email`)
    e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        related_id: opcional; filtra os logs de um webhook específico (corresponde a
            `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if related_id is not None:
        options["relatedId"] = related_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(HOOK_LOGS_QUERY, variables)
        return unwrap(data, "hookLogs")
    except MolonionError as e:
        return _err(e)


HOOK_MODEL_OPERATIONS_QUERY = """
query {
  hookModelOperations {
    errors { field msg }
    data {
      model
      name
      operations { operation name }
    }
  }
}
"""


@mcp.tool()
async def list_hook_model_operations() -> Any:
    """Lista o catálogo de gatilhos disponíveis para webhooks: para cada modelo
    (`model`, ex. documento, cliente, produto) o nome legível (`name`) e as operações
    disponíveis (`operations`, ex. criação, alteração, remoção). Usa isto para saber que
    combinações `model`/`operation` podes configurar num webhook. Não recebe argumentos.
    """
    try:
        data = await _client.query(HOOK_MODEL_OPERATIONS_QUERY)
        return unwrap(data, "hookModelOperations")
    except MolonionError as e:
        return _err(e)


HOOKS_QUERY = """
query ($companyId: Int!, $options: HookOptions) {
  hooks(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      hookId
      name
      url
      model
      operation
    }
  }
}
"""


@mcp.tool()
async def list_hooks(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os webhooks configurados numa empresa, cada um com o nome (`name`), o URL de
    callback (`url`) e os gatilhos (`model`/`operation`). Para obter um único pelo seu ID
    usa `get_hook`; para o catálogo de gatilhos disponíveis usa
    `list_hook_model_operations`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(HOOKS_QUERY, variables)
        return unwrap(data, "hooks")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Templates de identificação
# ---------------------------------------------------------------------------
IDENTIFICATION_TEMPLATE_QUERY = """
query ($companyId: Int!, $identTemplateId: Int!) {
  identificationTemplate(companyId: $companyId, identTemplateId: $identTemplateId) {
    errors { field msg }
    data {
      identTemplateId
      templateName
      businessName
      email
      address
      city
      zipCode
      phone
      fax
      website
      obs
      documentFooter
      emailSenderName
      emailSenderAddress
      img
      documentCompanyShowVATPrefix
      visible
      countryId
    }
  }
}
"""


@mcp.tool()
async def get_identification_template(
    company_id: int, ident_template_id: int
) -> Any:
    """Obtém um template de identificação de uma empresa pelo seu ID. Os templates de
    identificação permitem usar dados de identificação alternativos (nome comercial,
    morada, contactos, rodapé, remetente de email, logótipo) num documento, em vez dos
    dados-base da empresa. Devolve `templateName`, os dados de identificação e o rodapé
    de documento. Os objetos ligados (empresa, país, dados bancários) não são incluídos
    neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        ident_template_id: ID do template de identificação a obter.
    """
    variables = {"companyId": company_id, "identTemplateId": ident_template_id}
    try:
        data = await _client.query(IDENTIFICATION_TEMPLATE_QUERY, variables)
        return unwrap(data, "identificationTemplate")
    except MolonionError as e:
        return _err(e)


IDENTIFICATION_TEMPLATE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  identificationTemplateLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_identification_template_logs(
    company_id: int,
    ident_template_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos templates de identificação de uma
    empresa: criações, modificações e remoções. Cada entrada indica a operação
    (`operation`), os valores antigos/novos (`oldValues`/`newValues`), quem a fez
    (`userId`, `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        ident_template_id: opcional; filtra os logs de um template específico (corresponde
            a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if ident_template_id is not None:
        options["relatedId"] = ident_template_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(IDENTIFICATION_TEMPLATE_LOGS_QUERY, variables)
        return unwrap(data, "identificationTemplateLogs")
    except MolonionError as e:
        return _err(e)


IDENTIFICATION_TEMPLATES_QUERY = """
query ($companyId: Int!, $options: IdentificationTemplateOptions) {
  identificationTemplates(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      identTemplateId
      templateName
      businessName
      email
      city
      phone
      website
      img
      visible
      countryId
    }
  }
}
"""


@mcp.tool()
async def list_identification_templates(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os templates de identificação configurados numa empresa, cada um com o nome
    (`templateName`), o nome comercial e os contactos principais. Permitem usar dados de
    identificação alternativos em documentos. Para o detalhe completo de um template usa
    `get_identification_template`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(IDENTIFICATION_TEMPLATES_QUERY, variables)
        return unwrap(data, "identificationTemplates")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Faturas (documentos)
# ---------------------------------------------------------------------------
INVOICE_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  invoice(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscountValue
      totalDiscountValue
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      expirationDate
      maturityDateDays
      maturityDateName
      salespersonCommission
      yourReference
      ourReference
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      deliveryMethodName
      deliveryVehicleName
      deliveryVehicleLicensePlate
      deliveryLoadDate
      deliveryLoadAddress
      deliveryLoadCity
      deliveryLoadZipCode
      deliveryUnloadAddress
      deliveryUnloadCity
      deliveryUnloadZipCode
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_invoice(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma fatura pelo seu ID de documento: dados do documento
    (número, série, data, estado, totais, descontos, impostos), dados da entidade/cliente
    (`entityName`, `entityVat`, morada), o estado de reconciliação (`reconciledValue`,
    `remainingReconciledValue`, `reconciliationPercentage`), os dados de vencimento
    (`expirationDate`, `maturityDateDays`, `maturityDateName`), a comissão do vendedor e
    os dados de transporte (método de entrega, veículo/matrícula, carga/descarga). As
    linhas de produtos, os impostos detalhados, o cliente completo, os documentos
    relacionados e os dados AT não são incluídos neste selection set — podem ser
    adicionados se necessário.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (fatura) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(INVOICE_QUERY, variables)
        return unwrap(data, "invoice")
    except MolonionError as e:
        return _err(e)


INVOICE_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  invoiceGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_invoice_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma fatura. Devolve
    `token`, `path` e `filename`, que se combinam para construir o URL de download do
    PDF. Nota: ao contrário de outras operações, não recebe `companyId` — apenas o
    `documentId`.

    Args:
        document_id: ID do documento (fatura) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            INVOICE_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "invoiceGetPDFToken")
    except MolonionError as e:
        return _err(e)


INVOICE_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  invoiceGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_invoice_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar várias faturas como um arquivo
    ZIP. Devolve `token`, `path` e `filename`, que se combinam para construir o URL de
    download. O `full_path` identifica o ZIP a descarregar (caminho devolvido por uma
    operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(INVOICE_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "invoiceGetZIPToken")
    except MolonionError as e:
        return _err(e)


INVOICE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  invoiceLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_invoice_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às faturas de uma empresa: criações,
    modificações e remoções. Cada entrada indica a operação (`operation`), os valores
    antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`, `email`)
    e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma fatura específica (corresponde a
            `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(INVOICE_LOGS_QUERY, variables)
        return unwrap(data, "invoiceLogs")
    except MolonionError as e:
        return _err(e)


INVOICE_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  invoiceMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_invoice_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de faturas e o estado de entrega de
    cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para confirmar a
    quem foi enviado o documento e se a entrega teve sucesso. Os logs detalhados de cada
    destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_invoice_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(INVOICE_MAIL_RECIPIENTS_QUERY, variables)
        return unwrap(data, "invoiceMailRecipients")
    except MolonionError as e:
        return _err(e)


INVOICE_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  invoiceMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_invoice_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de emails enviados de uma fatura: para cada envio, o email, o
    conteúdo, a data (`createdAt`) e o `deliveryId`. Usa o `deliveryId` de um envio em
    `get_invoice_mail_recipients` para ver os destinatários e o estado de entrega desse
    envio.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (fatura) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(INVOICE_MAILS_HISTORY_QUERY, variables)
        return unwrap(data, "invoiceMailsHistory")
    except MolonionError as e:
        return _err(e)


INVOICE_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  invoiceNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_invoice_next_number(company_id: int, document_set_id: int) -> Any:
    """Obtém o próximo número disponível para uma fatura numa dada série de documentos.
    Devolve `number` (o próximo número) e `name` (o nome da série). Útil antes de criar
    uma nova fatura, para saber o número que lhe será atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(INVOICE_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "invoiceNextNumber")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Faturas-recibo (documentos)
# ---------------------------------------------------------------------------
INVOICE_RECEIPT_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  invoiceReceipt(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscountValue
      totalDiscountValue
      financialDiscount
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      expirationDate
      maturityDateDays
      maturityDateName
      salespersonCommission
      yourReference
      ourReference
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      deliveryMethodName
      deliveryVehicleName
      deliveryVehicleLicensePlate
      deliveryLoadDate
      deliveryLoadAddress
      deliveryLoadCity
      deliveryLoadZipCode
      deliveryUnloadAddress
      deliveryUnloadCity
      deliveryUnloadZipCode
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_invoice_receipt(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma fatura-recibo pelo seu ID de documento. A fatura-recibo é
    uma fatura paga no ato (junta fatura + recibo). Devolve os dados do documento
    (número, série, data, estado, totais, descontos, impostos, `financialDiscount`), os
    dados da entidade/cliente, o estado de reconciliação, os dados de vencimento, a
    comissão do vendedor e os dados de transporte. As linhas de produtos, os impostos
    detalhados, os pagamentos (`payments`), o movimento de caixa, o cliente completo e os
    dados AT não são incluídos neste selection set — podem ser adicionados se necessário.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (fatura-recibo) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(INVOICE_RECEIPT_QUERY, variables)
        return unwrap(data, "invoiceReceipt")
    except MolonionError as e:
        return _err(e)


INVOICE_RECEIPT_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  invoiceReceiptGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_invoice_receipt_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma fatura-recibo.
    Devolve `token`, `path` e `filename`, que se combinam para construir o URL de
    download do PDF. Nota: ao contrário de outras operações, não recebe `companyId` —
    apenas o `documentId`.

    Args:
        document_id: ID do documento (fatura-recibo) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            INVOICE_RECEIPT_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "invoiceReceiptGetPDFToken")
    except MolonionError as e:
        return _err(e)


INVOICE_RECEIPT_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  invoiceReceiptGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_invoice_receipt_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar várias faturas-recibo como um
    arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para construir o
    URL de download. O `full_path` identifica o ZIP a descarregar (caminho devolvido por
    uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(INVOICE_RECEIPT_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "invoiceReceiptGetZIPToken")
    except MolonionError as e:
        return _err(e)


INVOICE_RECEIPT_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  invoiceReceiptLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_invoice_receipt_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às faturas-recibo de uma empresa: criações,
    modificações e remoções. Cada entrada indica a operação (`operation`), os valores
    antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`, `email`)
    e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma fatura-recibo específica (corresponde
            a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(INVOICE_RECEIPT_LOGS_QUERY, variables)
        return unwrap(data, "invoiceReceiptLogs")
    except MolonionError as e:
        return _err(e)


INVOICE_RECEIPT_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  invoiceReceiptMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_invoice_receipt_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de faturas-recibo e o estado de
    entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para
    confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os logs
    detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_invoice_receipt_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(INVOICE_RECEIPT_MAIL_RECIPIENTS_QUERY, variables)
        return unwrap(data, "invoiceReceiptMailRecipients")
    except MolonionError as e:
        return _err(e)


INVOICE_RECEIPT_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  invoiceReceiptMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_invoice_receipt_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de emails enviados de uma fatura-recibo: para cada envio, o
    email, o conteúdo, a data (`createdAt`) e o `deliveryId`. Usa o `deliveryId` de um
    envio em `get_invoice_receipt_mail_recipients` para ver os destinatários e o estado
    de entrega desse envio.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (fatura-recibo) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(INVOICE_RECEIPT_MAILS_HISTORY_QUERY, variables)
        return unwrap(data, "invoiceReceiptMailsHistory")
    except MolonionError as e:
        return _err(e)


INVOICE_RECEIPT_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  invoiceReceiptNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_invoice_receipt_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para uma fatura-recibo numa dada série de
    documentos. Devolve `number` (o próximo número) e `name` (o nome da série). Útil
    antes de criar uma nova fatura-recibo, para saber o número que lhe será atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(INVOICE_RECEIPT_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "invoiceReceiptNextNumber")
    except MolonionError as e:
        return _err(e)


INVOICE_RECEIPT_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: InvoiceReceiptOptions) {
  invoiceReceiptRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_invoice_receipt_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as faturas-recibo de uma entidade que podem ser relacionadas/ligadas a outro
    documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente) cujas faturas-recibo relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(INVOICE_RECEIPT_RELATABLE_QUERY, variables)
        return unwrap(data, "invoiceReceiptRelatable")
    except MolonionError as e:
        return _err(e)


INVOICE_RECEIPTS_QUERY = """
query ($companyId: Int!, $options: InvoiceReceiptOptions) {
  invoiceReceipts(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_invoice_receipts(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as faturas-recibo de uma empresa, com os campos principais de
    cada uma: número, data, série, entidade, valor total e estado. Para obter o detalhe
    completo de uma fatura-recibo usa `get_invoice_receipt`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(INVOICE_RECEIPTS_QUERY, variables)
        return unwrap(data, "invoiceReceipts")
    except MolonionError as e:
        return _err(e)


INVOICE_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: InvoiceOptions) {
  invoiceRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_invoice_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as faturas de uma entidade que podem ser relacionadas/ligadas a outro
    documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente) cujas faturas relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(INVOICE_RELATABLE_QUERY, variables)
        return unwrap(data, "invoiceRelatable")
    except MolonionError as e:
        return _err(e)


INVOICES_QUERY = """
query ($companyId: Int!, $options: InvoiceOptions) {
  invoices(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      reconciledValue
      remainingReconciledValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_invoices(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as faturas de uma empresa, com os campos principais de cada uma:
    número, data, série, entidade, valor total e estado de reconciliação
    (`reconciledValue`, `remainingReconciledValue`). Para obter o detalhe completo de uma
    fatura usa `get_invoice`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(INVOICES_QUERY, variables)
        return unwrap(data, "invoices")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Autorização (controlo de acesso / limites de recursos)
# ---------------------------------------------------------------------------
IS_ALLOWED_QUERY = """
query ($companyId: Int!, $resource: String!, $action: String) {
  isAllowed(companyId: $companyId, resource: $resource, action: $action) {
    errors { field msg }
    data {
      allowed
      actualLimit
      usedResources
      remainingResources
      totalSupplements
      supplementsToUse
      supplementsUsed
      totalRollover
      rolloversToUse
      rolloversUsed
    }
  }
}
"""


@mcp.tool()
async def check_is_allowed(
    company_id: int, resource: str, action: str | None = None
) -> Any:
    """Verifica se uma ação sobre um recurso é permitida numa empresa (controlo de
    acesso e limites do plano). Devolve `allowed` (se é permitido) e os contadores de
    uso do recurso: limite atual (`actualLimit`), usados (`usedResources`), restantes
    (`remainingResources`) e os suplementos/rollovers (`totalSupplements`,
    `remainingResources`, `totalRollover`, etc.). Útil para saber se ainda há quota antes
    de criar um documento/entidade.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        resource: identificador do recurso (ex. tipo de documento/entidade).
        action: opcional; ação a verificar (ex. criação).
    """
    variables: dict[str, Any] = {"companyId": company_id, "resource": resource}
    if action is not None:
        variables["action"] = action
    try:
        data = await _client.query(IS_ALLOWED_QUERY, variables)
        return unwrap(data, "isAllowed")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Templates de etiquetas
# ---------------------------------------------------------------------------
LABEL_TEMPLATE_QUERY = """
query ($companyId: Int!, $labelTemplateId: String!) {
  labelTemplate(companyId: $companyId, labelTemplateId: $labelTemplateId) {
    errors { field msg }
    data {
      labelTemplateId
      name
      isDefault
      collate
      size
      obs
      companyId
    }
  }
}
"""


@mcp.tool()
async def get_label_template(company_id: int, label_template_id: str) -> Any:
    """Obtém um template de etiquetas de uma empresa pelo seu ID: o nome (`name`), se é o
    template por omissão (`isDefault`), se agrupa (`collate`), o tamanho (`size`) e notas.
    Usado para gerar etiquetas de produto/expedição. Nota: o `label_template_id` é uma
    **string**. Os campos de layout da etiqueta (`fields`) e o objeto `company` não são
    incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        label_template_id: ID (string) do template de etiquetas a obter.
    """
    variables = {"companyId": company_id, "labelTemplateId": label_template_id}
    try:
        data = await _client.query(LABEL_TEMPLATE_QUERY, variables)
        return unwrap(data, "labelTemplate")
    except MolonionError as e:
        return _err(e)


LABEL_TEMPLATE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  labelTemplateLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_label_template_logs(
    company_id: int,
    related_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos templates de etiquetas de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        related_id: opcional; filtra os logs de um template específico (corresponde a
            `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if related_id is not None:
        options["relatedId"] = related_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(LABEL_TEMPLATE_LOGS_QUERY, variables)
        return unwrap(data, "labelTemplateLogs")
    except MolonionError as e:
        return _err(e)


LABEL_TEMPLATES_QUERY = """
query ($companyId: Int!, $options: LabelTemplateOptions) {
  labelTemplates(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      labelTemplateId
      name
      isDefault
      collate
      size
      obs
      companyId
    }
  }
}
"""


@mcp.tool()
async def list_label_templates(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os templates de etiquetas configurados numa empresa, cada um com o nome
    (`name`), se é o template por omissão (`isDefault`) e o tamanho (`size`). Para obter
    um único pelo seu ID usa `get_label_template`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(LABEL_TEMPLATES_QUERY, variables)
        return unwrap(data, "labelTemplates")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Idiomas (tabela de referência global)
# ---------------------------------------------------------------------------
LANGUAGE_QUERY = """
query ($languageId: Int!) {
  language(languageId: $languageId) {
    errors { field msg }
    data {
      languageId
      name
      iso3166
      flag
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_language(language_id: int) -> Any:
    """Obtém um idioma pelo seu ID — tabela de referência global usada em traduções,
    clientes e documentos. Devolve o nome (`name`), o código ISO 3166 (`iso3166`) e a
    bandeira (`flag`). Ao contrário da maioria das operações, não recebe `companyId`.

    Args:
        language_id: ID do idioma a obter.
    """
    try:
        data = await _client.query(LANGUAGE_QUERY, {"languageId": language_id})
        return unwrap(data, "language")
    except MolonionError as e:
        return _err(e)


LANGUAGES_QUERY = """
query ($options: LanguageOptions) {
  languages(options: $options) {
    errors { field msg }
    data {
      languageId
      name
      iso3166
      flag
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_languages(page: int | None = None, qty: int | None = None) -> Any:
    """Lista os idiomas disponíveis na Moloni ON — tabela de referência global usada em
    traduções, clientes e documentos. Para cada idioma: o `languageId` (usado noutras
    operações), o nome (`name`), o código ISO 3166 (`iso3166`) e a bandeira (`flag`). Ao
    contrário da maioria das operações, não recebe `companyId`.

    Args:
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(LANGUAGES_QUERY, variables)
        return unwrap(data, "languages")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Movimentos de stock
# ---------------------------------------------------------------------------
LIST_PRODUCTS_STOCK_MOVEMENTS_QUERY = """
query ($companyId: Int!, $options: ListStockMovementOptions) {
  listProductsStockMovements(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      productId
      reference
      name
      type
      stock
      hasStock
      minStock
      hasStockMovements
      price
      priceWithTaxes
      costPrice
      measurementUnitId
      warehouseId
      productCategoryId
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_products_stock_movements(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os produtos com os respetivos dados de stock e indicação de movimentos
    (`hasStockMovements`), com os campos principais de cada produto: referência, nome,
    tipo, stock atual e mínimo, preços e preço de custo.

    DEPRECATED na API Moloni ON — preferir `stockProducts`. Mantida por cobertura; usa a
    alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(LIST_PRODUCTS_STOCK_MOVEMENTS_QUERY, variables)
        return unwrap(data, "listProductsStockMovements")
    except MolonionError as e:
        return _err(e)


LIST_PRODUCTS_STOCK_TOTALS_QUERY = """
query ($companyId: Int!, $options: ListStockTotalsOptions) {
  listProductsStockTotals(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      totalCosts
      totalSales
      usingLowestSupplierCost
    }
  }
}
"""


@mcp.tool()
async def list_products_stock_totals(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém os totais de stock dos produtos de uma empresa: o custo total em stock
    (`totalCosts`), o valor total de venda (`totalSales`) e se está a usar o custo do
    fornecedor mais baixo (`usingLowestSupplierCost`). Útil para valorização de
    inventário.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(LIST_PRODUCTS_STOCK_TOTALS_QUERY, variables)
        return unwrap(data, "listProductsStockTotals")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Datas de vencimento (condições de pagamento)
# ---------------------------------------------------------------------------
MATURITY_DATE_QUERY = """
query ($companyId: Int!, $maturityDateId: Int!) {
  maturityDate(companyId: $companyId, maturityDateId: $maturityDateId) {
    errors { field msg }
    data {
      maturityDateId
      name
      days
      discount
      isDefault
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_maturity_date(company_id: int, maturity_date_id: int) -> Any:
    """Obtém uma data de vencimento (condição de pagamento) de uma empresa pelo seu ID:
    o nome (`name`), os dias de prazo (`days`), o desconto associado (`discount`) e se é
    a condição por omissão (`isDefault`). Usada nos documentos para calcular a data-limite
    de pagamento. O objeto `company` ligado não é incluído neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        maturity_date_id: ID da data de vencimento a obter.
    """
    variables = {"companyId": company_id, "maturityDateId": maturity_date_id}
    try:
        data = await _client.query(MATURITY_DATE_QUERY, variables)
        return unwrap(data, "maturityDate")
    except MolonionError as e:
        return _err(e)


MATURITY_DATE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  maturityDateLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_maturity_date_logs(
    company_id: int,
    maturity_date_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às datas de vencimento de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        maturity_date_id: opcional; filtra os logs de uma data de vencimento específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if maturity_date_id is not None:
        options["relatedId"] = maturity_date_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MATURITY_DATE_LOGS_QUERY, variables)
        return unwrap(data, "maturityDateLogs")
    except MolonionError as e:
        return _err(e)


MATURITY_DATES_QUERY = """
query ($companyId: Int!, $options: MaturityDateOptions) {
  maturityDates(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      maturityDateId
      name
      days
      discount
      isDefault
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_maturity_dates(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as datas de vencimento (condições de pagamento) configuradas numa empresa,
    cada uma com o nome (`name`), os dias de prazo (`days`), o desconto (`discount`) e se
    é a condição por omissão (`isDefault`). Para obter uma única pelo seu ID usa
    `get_maturity_date`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MATURITY_DATES_QUERY, variables)
        return unwrap(data, "maturityDates")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Atividade do utilizador
# ---------------------------------------------------------------------------
ME_ACTIVITY_QUERY = """
query ($options: MeActivityOptions) {
  meActivity(options: $options) {
    errors { field msg }
    data {
      apiClient { apiClientId name }
    }
  }
}
"""


@mcp.tool()
async def list_my_activity(page: int | None = None, qty: int | None = None) -> Any:
    """Lista a atividade recente do utilizador autenticado — os clientes de API
    (`apiClient`: `apiClientId`, `name`) através dos quais houve sessão/atividade. Ao
    contrário da maioria das operações, não recebe `companyId` (é a nível do utilizador).

    Args:
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(ME_ACTIVITY_QUERY, variables)
        return unwrap(data, "meActivity")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Unidades de medida
# ---------------------------------------------------------------------------
MEASUREMENT_UNIT_QUERY = """
query ($companyId: Int!, $measurementUnitId: Int!) {
  measurementUnit(companyId: $companyId, measurementUnitId: $measurementUnitId) {
    errors { field msg }
    data {
      measurementUnitId
      name
      abbreviation
      measurementUnitUNECERId
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_measurement_unit(company_id: int, measurement_unit_id: int) -> Any:
    """Obtém uma unidade de medida de uma empresa pelo seu ID: o nome (`name`), a
    abreviatura (`abbreviation`) e o código UN/ECE associado (`measurementUnitUNECERId`,
    usado na comunicação à AT). Os objetos ligados (empresa, detalhe UN/ECE) não são
    incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        measurement_unit_id: ID da unidade de medida a obter.
    """
    variables = {
        "companyId": company_id,
        "measurementUnitId": measurement_unit_id,
    }
    try:
        data = await _client.query(MEASUREMENT_UNIT_QUERY, variables)
        return unwrap(data, "measurementUnit")
    except MolonionError as e:
        return _err(e)


# NOTA: tabela de referência global de unidades (sem `companyId`); o argumento é
# `unitDefaultId` e o tipo devolvido é MeasurementUnitDefaultRead.
MEASUREMENT_UNIT_DEFAULT_QUERY = """
query ($unitDefaultId: Int!) {
  measurementUnitDefault(unitDefaultId: $unitDefaultId) {
    errors { field msg }
    data {
      unitDefaultId
      description
      abbreviation
      visible
    }
  }
}
"""


@mcp.tool()
async def get_measurement_unit_default(unit_default_id: int) -> Any:
    """Obtém uma unidade de medida da tabela de referência global (unidades por omissão
    da Moloni ON) pelo seu ID: a descrição (`description`) e a abreviatura
    (`abbreviation`). Ao contrário de `get_measurement_unit` (unidades da empresa), esta
    é a tabela global e não recebe `companyId`. As traduções não são incluídas neste
    selection set.

    Args:
        unit_default_id: ID da unidade de medida (global) a obter.
    """
    try:
        data = await _client.query(
            MEASUREMENT_UNIT_DEFAULT_QUERY, {"unitDefaultId": unit_default_id}
        )
        return unwrap(data, "measurementUnitDefault")
    except MolonionError as e:
        return _err(e)


MEASUREMENT_UNIT_DEFAULTS_QUERY = """
query ($options: MeasurementUnitDefaultOptions) {
  measurementUnitDefaults(options: $options) {
    errors { field msg }
    data {
      unitDefaultId
      description
      abbreviation
      visible
    }
  }
}
"""


@mcp.tool()
async def list_measurement_unit_defaults(
    page: int | None = None, qty: int | None = None
) -> Any:
    """Lista as unidades de medida da tabela de referência global (unidades por omissão
    da Moloni ON), cada uma com a descrição (`description`) e a abreviatura
    (`abbreviation`). Ao contrário de `list_measurement_units` (unidades da empresa), esta
    é a tabela global e não recebe `companyId`.

    Args:
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MEASUREMENT_UNIT_DEFAULTS_QUERY, variables)
        return unwrap(data, "measurementUnitDefaults")
    except MolonionError as e:
        return _err(e)


MEASUREMENT_UNIT_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  measurementUnitLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_measurement_unit_logs(
    company_id: int,
    measurement_unit_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às unidades de medida de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        measurement_unit_id: opcional; filtra os logs de uma unidade específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if measurement_unit_id is not None:
        options["relatedId"] = measurement_unit_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MEASUREMENT_UNIT_LOGS_QUERY, variables)
        return unwrap(data, "measurementUnitLogs")
    except MolonionError as e:
        return _err(e)


MEASUREMENT_UNITS_QUERY = """
query ($companyId: Int!, $options: MeasurementUnitOptions) {
  measurementUnits(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      measurementUnitId
      name
      abbreviation
      measurementUnitUNECERId
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_measurement_units(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as unidades de medida configuradas numa empresa, cada uma com o nome
    (`name`), a abreviatura (`abbreviation`) e o código UN/ECE (`measurementUnitUNECERId`).
    Para obter uma única pelo seu ID usa `get_measurement_unit`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MEASUREMENT_UNITS_QUERY, variables)
        return unwrap(data, "measurementUnits")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Sessão (login)
# ---------------------------------------------------------------------------
# NOTA: devolve um escalar Boolean diretamente (sem envelope `{errors, data}`).
ME_LOGGED_IN_QUERY = """
query {
  meLoggedIn
}
"""


@mcp.tool()
async def check_logged_in() -> Any:
    """Verifica se o utilizador (a API Key) está autenticado. Devolve um booleano (`true`
    se a sessão/credencial é válida). Forma leve de confirmar a autenticação; para o
    utilizador e empresas usa `me`. Não recebe argumentos.
    """
    try:
        data = await _client.query(ME_LOGGED_IN_QUERY)
        return {"loggedIn": (data or {}).get("meLoggedIn")}
    except MolonionError as e:
        return _err(e)


# NOTA: devolve um escalar Boolean diretamente (sem envelope `{errors, data}`).
ME_PASSWORD_CHECK_QUERY = """
query ($password: String!) {
  mePasswordCheck(password: $password)
}
"""


@mcp.tool()
async def check_my_password(password: str) -> Any:
    """Verifica se a password fornecida corresponde à do utilizador autenticado. Devolve
    um booleano (`true` se a password está correta). Usado para confirmar a identidade
    antes de operações sensíveis.

    Nota: recebe a password do utilizador — usa apenas com credenciais autorizadas.

    Args:
        password: password do utilizador autenticado a verificar.
    """
    try:
        data = await _client.query(ME_PASSWORD_CHECK_QUERY, {"password": password})
        return {"valid": (data or {}).get("mePasswordCheck")}
    except MolonionError as e:
        return _err(e)


ME_TWO_FACTOR_METHODS_QUERY = """
query {
  meTwoFactorMethods {
    errors { field msg }
    data {
      method
      default
      createdAt
    }
  }
}
"""


@mcp.tool()
async def list_my_two_factor_methods() -> Any:
    """Lista os métodos de autenticação de dois fatores (2FA) configurados pelo
    utilizador autenticado: o método (`method`, ex. app/SMS/email), se é o método por
    omissão (`default`) e quando foi configurado (`createdAt`). Não recebe argumentos.
    """
    try:
        data = await _client.query(ME_TWO_FACTOR_METHODS_QUERY)
        return unwrap(data, "meTwoFactorMethods")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Documentos migrados (histórico importado)
# ---------------------------------------------------------------------------
MIGRATED_CREDIT_NOTE_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  migratedCreditNote(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscountValue
      totalDiscountValue
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      notes
      notesRelatedDocs
      pdfExport
      file
      fileOriginal
      downloads
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_migrated_credit_note(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma nota de crédito migrada (documento histórico importado de
    outro sistema) pelo seu ID de documento: dados do documento, totais, reconciliação,
    dados da entidade e o ficheiro arquivado (`file`/`fileOriginal`). As linhas de
    produtos, os impostos, o cliente e os documentos relacionados não são incluídos neste
    selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (nota de crédito migrada) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(MIGRATED_CREDIT_NOTE_QUERY, variables)
        return unwrap(data, "migratedCreditNote")
    except MolonionError as e:
        return _err(e)


MIGRATED_CREDIT_NOTE_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  migratedCreditNoteGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_migrated_credit_note_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma nota de crédito
    migrada. Devolve `token`, `path` e `filename`, que se combinam para construir o URL
    de download do PDF. Nota: ao contrário de outras operações, não recebe `companyId` —
    apenas o `documentId`.

    Args:
        document_id: ID do documento (nota de crédito migrada) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            MIGRATED_CREDIT_NOTE_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "migratedCreditNoteGetPDFToken")
    except MolonionError as e:
        return _err(e)


MIGRATED_CREDIT_NOTE_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  migratedCreditNoteGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_migrated_credit_note_zip_token(
    company_id: int, full_path: str
) -> Any:
    """Gera um token temporário e seguro para descarregar várias notas de crédito
    migradas como um arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam
    para construir o URL de download. O `full_path` identifica o ZIP a descarregar
    (caminho devolvido por uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(MIGRATED_CREDIT_NOTE_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "migratedCreditNoteGetZIPToken")
    except MolonionError as e:
        return _err(e)


MIGRATED_CREDIT_NOTE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  migratedCreditNoteLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_migrated_credit_note_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às notas de crédito migradas de uma
    empresa: criações, modificações e remoções. Cada entrada indica a operação
    (`operation`), os valores antigos/novos (`oldValues`/`newValues`), quem a fez
    (`userId`, `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma nota de crédito migrada específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_CREDIT_NOTE_LOGS_QUERY, variables)
        return unwrap(data, "migratedCreditNoteLogs")
    except MolonionError as e:
        return _err(e)


MIGRATED_CREDIT_NOTE_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  migratedCreditNoteMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_migrated_credit_note_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de notas de crédito migradas e o
    estado de entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`).
    Útil para confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os
    logs detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_migrated_credit_note_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            MIGRATED_CREDIT_NOTE_MAIL_RECIPIENTS_QUERY, variables
        )
        return unwrap(data, "migratedCreditNoteMailRecipients")
    except MolonionError as e:
        return _err(e)


MIGRATED_CREDIT_NOTE_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  migratedCreditNoteMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_migrated_credit_note_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de emails enviados de uma nota de crédito migrada: para cada
    envio, o email, o conteúdo, a data (`createdAt`) e o `deliveryId`. Usa o `deliveryId`
    de um envio em `get_migrated_credit_note_mail_recipients` para ver os destinatários e
    o estado de entrega desse envio.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (nota de crédito migrada) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            MIGRATED_CREDIT_NOTE_MAILS_HISTORY_QUERY, variables
        )
        return unwrap(data, "migratedCreditNoteMailsHistory")
    except MolonionError as e:
        return _err(e)


MIGRATED_CREDIT_NOTE_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  migratedCreditNoteNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_migrated_credit_note_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para uma nota de crédito migrada numa dada série
    de documentos. Devolve `number` (o próximo número) e `name` (o nome da série).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(MIGRATED_CREDIT_NOTE_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "migratedCreditNoteNextNumber")
    except MolonionError as e:
        return _err(e)


MIGRATED_CREDIT_NOTE_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: MigratedCreditNoteOptions) {
  migratedCreditNoteRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_migrated_credit_note_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as notas de crédito migradas de uma entidade que podem ser
    relacionadas/ligadas a outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente) cujas notas de crédito migradas relacionáveis
            se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_CREDIT_NOTE_RELATABLE_QUERY, variables)
        return unwrap(data, "migratedCreditNoteRelatable")
    except MolonionError as e:
        return _err(e)


MIGRATED_CREDIT_NOTES_QUERY = """
query ($companyId: Int!, $options: MigratedCreditNoteOptions) {
  migratedCreditNotes(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_migrated_credit_notes(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as notas de crédito migradas de uma empresa (documentos
    históricos importados), com os campos principais de cada uma: número, data, série,
    entidade, valor total e estado. Para obter o detalhe completo usa
    `get_migrated_credit_note`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_CREDIT_NOTES_QUERY, variables)
        return unwrap(data, "migratedCreditNotes")
    except MolonionError as e:
        return _err(e)


MIGRATED_DEBIT_NOTE_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  migratedDebitNote(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscountValue
      totalDiscountValue
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      expirationDate
      maturityDateDays
      maturityDateName
      salespersonCommission
      notes
      notesRelatedDocs
      pdfExport
      downloads
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_migrated_debit_note(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma nota de débito migrada (documento histórico importado de
    outro sistema) pelo seu ID de documento: dados do documento, totais, reconciliação,
    dados da entidade, vencimento (`expirationDate`, `maturityDateDays`, `maturityDateName`)
    e comissão do vendedor. As linhas de produtos, os impostos, o cliente e os documentos
    relacionados não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (nota de débito migrada) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(MIGRATED_DEBIT_NOTE_QUERY, variables)
        return unwrap(data, "migratedDebitNote")
    except MolonionError as e:
        return _err(e)


MIGRATED_DEBIT_NOTE_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  migratedDebitNoteGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_migrated_debit_note_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma nota de débito
    migrada. Devolve `token`, `path` e `filename`, que se combinam para construir o URL
    de download do PDF. Nota: ao contrário de outras operações, não recebe `companyId` —
    apenas o `documentId`.

    Args:
        document_id: ID do documento (nota de débito migrada) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            MIGRATED_DEBIT_NOTE_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "migratedDebitNoteGetPDFToken")
    except MolonionError as e:
        return _err(e)


MIGRATED_DEBIT_NOTE_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  migratedDebitNoteGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_migrated_debit_note_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar várias notas de débito migradas
    como um arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para
    construir o URL de download. O `full_path` identifica o ZIP a descarregar (caminho
    devolvido por uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(MIGRATED_DEBIT_NOTE_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "migratedDebitNoteGetZIPToken")
    except MolonionError as e:
        return _err(e)


MIGRATED_DEBIT_NOTE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  migratedDebitNoteLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_migrated_debit_note_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às notas de débito migradas de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma nota de débito migrada específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_DEBIT_NOTE_LOGS_QUERY, variables)
        return unwrap(data, "migratedDebitNoteLogs")
    except MolonionError as e:
        return _err(e)


MIGRATED_DEBIT_NOTE_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  migratedDebitNoteMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_migrated_debit_note_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de notas de débito migradas e o
    estado de entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`).
    Útil para confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os
    logs detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_migrated_debit_note_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            MIGRATED_DEBIT_NOTE_MAIL_RECIPIENTS_QUERY, variables
        )
        return unwrap(data, "migratedDebitNoteMailRecipients")
    except MolonionError as e:
        return _err(e)


MIGRATED_DEBIT_NOTE_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  migratedDebitNoteMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_migrated_debit_note_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de emails enviados de uma nota de débito migrada: para cada
    envio, o email, o conteúdo, a data (`createdAt`) e o `deliveryId`. Usa o `deliveryId`
    de um envio em `get_migrated_debit_note_mail_recipients` para ver os destinatários e
    o estado de entrega desse envio.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (nota de débito migrada) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            MIGRATED_DEBIT_NOTE_MAILS_HISTORY_QUERY, variables
        )
        return unwrap(data, "migratedDebitNoteMailsHistory")
    except MolonionError as e:
        return _err(e)


MIGRATED_DEBIT_NOTE_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  migratedDebitNoteNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_migrated_debit_note_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para uma nota de débito migrada numa dada série
    de documentos. Devolve `number` (o próximo número) e `name` (o nome da série).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(MIGRATED_DEBIT_NOTE_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "migratedDebitNoteNextNumber")
    except MolonionError as e:
        return _err(e)


MIGRATED_DEBIT_NOTE_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: MigratedDebitNoteOptions) {
  migratedDebitNoteRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_migrated_debit_note_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as notas de débito migradas de uma entidade que podem ser
    relacionadas/ligadas a outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente) cujas notas de débito migradas relacionáveis
            se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_DEBIT_NOTE_RELATABLE_QUERY, variables)
        return unwrap(data, "migratedDebitNoteRelatable")
    except MolonionError as e:
        return _err(e)


MIGRATED_DEBIT_NOTES_QUERY = """
query ($companyId: Int!, $options: MigratedDebitNoteOptions) {
  migratedDebitNotes(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_migrated_debit_notes(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as notas de débito migradas de uma empresa (documentos históricos
    importados), com os campos principais de cada uma: número, data, série, entidade,
    valor total e estado. Para obter o detalhe completo usa `get_migrated_debit_note`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_DEBIT_NOTES_QUERY, variables)
        return unwrap(data, "migratedDebitNotes")
    except MolonionError as e:
        return _err(e)


MIGRATED_ESTIMATE_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  migratedEstimate(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscountValue
      totalDiscountValue
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      expirationDate
      maturityDateDays
      maturityDateName
      salespersonCommission
      notes
      notesRelatedDocs
      pdfExport
      downloads
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_migrated_estimate(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de um orçamento migrado (documento histórico importado de outro
    sistema) pelo seu ID de documento: dados do documento, totais, reconciliação, dados
    da entidade, validade (`expirationDate`, `maturityDateDays`, `maturityDateName`) e
    comissão do vendedor. As linhas de produtos, os impostos, o cliente e os documentos
    relacionados não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (orçamento migrado) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(MIGRATED_ESTIMATE_QUERY, variables)
        return unwrap(data, "migratedEstimate")
    except MolonionError as e:
        return _err(e)


MIGRATED_ESTIMATE_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  migratedEstimateGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_migrated_estimate_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de um orçamento migrado.
    Devolve `token`, `path` e `filename`, que se combinam para construir o URL de
    download do PDF. Nota: ao contrário de outras operações, não recebe `companyId` —
    apenas o `documentId`.

    Args:
        document_id: ID do documento (orçamento migrado) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            MIGRATED_ESTIMATE_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "migratedEstimateGetPDFToken")
    except MolonionError as e:
        return _err(e)


MIGRATED_ESTIMATE_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  migratedEstimateGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_migrated_estimate_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar vários orçamentos migrados como
    um arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para construir
    o URL de download. O `full_path` identifica o ZIP a descarregar (caminho devolvido
    por uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(MIGRATED_ESTIMATE_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "migratedEstimateGetZIPToken")
    except MolonionError as e:
        return _err(e)


MIGRATED_ESTIMATE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  migratedEstimateLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_migrated_estimate_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos orçamentos migrados de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de um orçamento migrado específico
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_ESTIMATE_LOGS_QUERY, variables)
        return unwrap(data, "migratedEstimateLogs")
    except MolonionError as e:
        return _err(e)


MIGRATED_ESTIMATE_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  migratedEstimateMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_migrated_estimate_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de orçamentos migrados e o estado de
    entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para
    confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os logs
    detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_migrated_estimate_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            MIGRATED_ESTIMATE_MAIL_RECIPIENTS_QUERY, variables
        )
        return unwrap(data, "migratedEstimateMailRecipients")
    except MolonionError as e:
        return _err(e)


MIGRATED_ESTIMATE_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  migratedEstimateMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_migrated_estimate_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de emails enviados de um orçamento migrado: para cada envio, o
    email, o conteúdo, a data (`createdAt`) e o `deliveryId`. Usa o `deliveryId` de um
    envio em `get_migrated_estimate_mail_recipients` para ver os destinatários e o estado
    de entrega desse envio.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (orçamento migrado) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            MIGRATED_ESTIMATE_MAILS_HISTORY_QUERY, variables
        )
        return unwrap(data, "migratedEstimateMailsHistory")
    except MolonionError as e:
        return _err(e)


MIGRATED_ESTIMATE_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  migratedEstimateNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_migrated_estimate_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para um orçamento migrado numa dada série de
    documentos. Devolve `number` (o próximo número) e `name` (o nome da série).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(MIGRATED_ESTIMATE_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "migratedEstimateNextNumber")
    except MolonionError as e:
        return _err(e)


MIGRATED_ESTIMATE_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: MigratedEstimateOptions) {
  migratedEstimateRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_migrated_estimate_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os orçamentos migrados de uma entidade que podem ser relacionados/ligados a
    outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente) cujos orçamentos migrados relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_ESTIMATE_RELATABLE_QUERY, variables)
        return unwrap(data, "migratedEstimateRelatable")
    except MolonionError as e:
        return _err(e)


MIGRATED_ESTIMATES_QUERY = """
query ($companyId: Int!, $options: MigratedEstimateOptions) {
  migratedEstimates(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_migrated_estimates(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) os orçamentos migrados de uma empresa (documentos históricos
    importados), com os campos principais de cada um: número, data, série, entidade,
    valor total e estado. Para obter o detalhe completo usa `get_migrated_estimate`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_ESTIMATES_QUERY, variables)
        return unwrap(data, "migratedEstimates")
    except MolonionError as e:
        return _err(e)


MIGRATED_INVOICE_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  migratedInvoice(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscountValue
      totalDiscountValue
      retentionsValue
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      expirationDate
      maturityDateDays
      maturityDateName
      salespersonCommission
      notes
      notesRelatedDocs
      pdfExport
      file
      fileOriginal
      downloads
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_migrated_invoice(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma fatura migrada (documento histórico importado de outro
    sistema) pelo seu ID de documento: dados do documento, totais, dados da entidade,
    vencimento (`expirationDate`, `maturityDateDays`, `maturityDateName`), comissão do
    vendedor e o ficheiro arquivado (`file`/`fileOriginal`). As linhas de produtos, os
    impostos, o cliente e os documentos relacionados não são incluídos neste selection
    set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (fatura migrada) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(MIGRATED_INVOICE_QUERY, variables)
        return unwrap(data, "migratedInvoice")
    except MolonionError as e:
        return _err(e)


MIGRATED_INVOICE_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  migratedInvoiceGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_migrated_invoice_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma fatura migrada.
    Devolve `token`, `path` e `filename`, que se combinam para construir o URL de
    download do PDF. Nota: ao contrário de outras operações, não recebe `companyId` —
    apenas o `documentId`.

    Args:
        document_id: ID do documento (fatura migrada) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            MIGRATED_INVOICE_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "migratedInvoiceGetPDFToken")
    except MolonionError as e:
        return _err(e)


MIGRATED_INVOICE_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  migratedInvoiceGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_migrated_invoice_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar várias faturas migradas como um
    arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para construir o
    URL de download. O `full_path` identifica o ZIP a descarregar (caminho devolvido por
    uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(MIGRATED_INVOICE_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "migratedInvoiceGetZIPToken")
    except MolonionError as e:
        return _err(e)


MIGRATED_INVOICE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  migratedInvoiceLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_migrated_invoice_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às faturas migradas de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma fatura migrada específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_INVOICE_LOGS_QUERY, variables)
        return unwrap(data, "migratedInvoiceLogs")
    except MolonionError as e:
        return _err(e)


MIGRATED_INVOICE_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  migratedInvoiceMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_migrated_invoice_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de faturas migradas e o estado de
    entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para
    confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os logs
    detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_migrated_invoice_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            MIGRATED_INVOICE_MAIL_RECIPIENTS_QUERY, variables
        )
        return unwrap(data, "migratedInvoiceMailRecipients")
    except MolonionError as e:
        return _err(e)


MIGRATED_INVOICE_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  migratedInvoiceMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_migrated_invoice_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de emails enviados de uma fatura migrada: para cada envio, o
    email, o conteúdo, a data (`createdAt`) e o `deliveryId`. Usa o `deliveryId` de um
    envio em `get_migrated_invoice_mail_recipients` para ver os destinatários e o estado
    de entrega desse envio.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (fatura migrada) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            MIGRATED_INVOICE_MAILS_HISTORY_QUERY, variables
        )
        return unwrap(data, "migratedInvoiceMailsHistory")
    except MolonionError as e:
        return _err(e)


MIGRATED_INVOICE_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  migratedInvoiceNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_migrated_invoice_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para uma fatura migrada numa dada série de
    documentos. Devolve `number` (o próximo número) e `name` (o nome da série).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(MIGRATED_INVOICE_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "migratedInvoiceNextNumber")
    except MolonionError as e:
        return _err(e)


MIGRATED_INVOICE_RECEIPT_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  migratedInvoiceReceipt(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscountValue
      totalDiscountValue
      financialDiscount
      retentionsValue
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      expirationDate
      maturityDateDays
      maturityDateName
      salespersonCommission
      notes
      notesRelatedDocs
      pdfExport
      file
      fileOriginal
      downloads
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_migrated_invoice_receipt(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma fatura-recibo migrada (documento histórico importado de
    outro sistema) pelo seu ID de documento: dados do documento, totais e descontos
    (`financialDiscount`), dados da entidade, vencimento, comissão do vendedor e o
    ficheiro arquivado (`file`/`fileOriginal`). As linhas de produtos, os impostos, o
    cliente e os documentos relacionados não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (fatura-recibo migrada) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(MIGRATED_INVOICE_RECEIPT_QUERY, variables)
        return unwrap(data, "migratedInvoiceReceipt")
    except MolonionError as e:
        return _err(e)


MIGRATED_INVOICE_RECEIPT_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  migratedInvoiceReceiptGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_migrated_invoice_receipt_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma fatura-recibo
    migrada. Devolve `token`, `path` e `filename`, que se combinam para construir o URL
    de download do PDF. Nota: ao contrário de outras operações, não recebe `companyId` —
    apenas o `documentId`.

    Args:
        document_id: ID do documento (fatura-recibo migrada) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            MIGRATED_INVOICE_RECEIPT_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "migratedInvoiceReceiptGetPDFToken")
    except MolonionError as e:
        return _err(e)


MIGRATED_INVOICE_RECEIPT_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  migratedInvoiceReceiptGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_migrated_invoice_receipt_zip_token(
    company_id: int, full_path: str
) -> Any:
    """Gera um token temporário e seguro para descarregar várias faturas-recibo migradas
    como um arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para
    construir o URL de download. O `full_path` identifica o ZIP a descarregar (caminho
    devolvido por uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(MIGRATED_INVOICE_RECEIPT_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "migratedInvoiceReceiptGetZIPToken")
    except MolonionError as e:
        return _err(e)


MIGRATED_INVOICE_RECEIPT_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  migratedInvoiceReceiptLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_migrated_invoice_receipt_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às faturas-recibo migradas de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma fatura-recibo migrada específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_INVOICE_RECEIPT_LOGS_QUERY, variables)
        return unwrap(data, "migratedInvoiceReceiptLogs")
    except MolonionError as e:
        return _err(e)


MIGRATED_INVOICE_RECEIPT_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  migratedInvoiceReceiptMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_migrated_invoice_receipt_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de faturas-recibo migradas e o estado
    de entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para
    confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os logs
    detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_migrated_invoice_receipt_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            MIGRATED_INVOICE_RECEIPT_MAIL_RECIPIENTS_QUERY, variables
        )
        return unwrap(data, "migratedInvoiceReceiptMailRecipients")
    except MolonionError as e:
        return _err(e)


MIGRATED_INVOICE_RECEIPT_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  migratedInvoiceReceiptMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_migrated_invoice_receipt_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de emails enviados de uma fatura-recibo migrada: para cada
    envio, o email, o conteúdo, a data (`createdAt`) e o `deliveryId`. Usa o `deliveryId`
    de um envio em `get_migrated_invoice_receipt_mail_recipients` para ver os
    destinatários e o estado de entrega desse envio.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (fatura-recibo migrada) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            MIGRATED_INVOICE_RECEIPT_MAILS_HISTORY_QUERY, variables
        )
        return unwrap(data, "migratedInvoiceReceiptMailsHistory")
    except MolonionError as e:
        return _err(e)


MIGRATED_INVOICE_RECEIPT_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  migratedInvoiceReceiptNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_migrated_invoice_receipt_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para uma fatura-recibo migrada numa dada série de
    documentos. Devolve `number` (o próximo número) e `name` (o nome da série).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(
            MIGRATED_INVOICE_RECEIPT_NEXT_NUMBER_QUERY, variables
        )
        return unwrap(data, "migratedInvoiceReceiptNextNumber")
    except MolonionError as e:
        return _err(e)


MIGRATED_INVOICE_RECEIPT_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: MigratedInvoiceReceiptOptions) {
  migratedInvoiceReceiptRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_migrated_invoice_receipt_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as faturas-recibo migradas de uma entidade que podem ser relacionadas/ligadas
    a outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente) cujas faturas-recibo migradas relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            MIGRATED_INVOICE_RECEIPT_RELATABLE_QUERY, variables
        )
        return unwrap(data, "migratedInvoiceReceiptRelatable")
    except MolonionError as e:
        return _err(e)


MIGRATED_INVOICE_RECEIPTS_QUERY = """
query ($companyId: Int!, $options: MigratedInvoiceReceiptOptions) {
  migratedInvoiceReceipts(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_migrated_invoice_receipts(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as faturas-recibo migradas de uma empresa (documentos históricos
    importados), com os campos principais de cada uma: número, data, série, entidade,
    valor total e estado. Para obter o detalhe completo usa `get_migrated_invoice_receipt`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_INVOICE_RECEIPTS_QUERY, variables)
        return unwrap(data, "migratedInvoiceReceipts")
    except MolonionError as e:
        return _err(e)


MIGRATED_INVOICE_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: MigratedInvoiceOptions) {
  migratedInvoiceRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_migrated_invoice_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as faturas migradas de uma entidade que podem ser relacionadas/ligadas a
    outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente) cujas faturas migradas relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_INVOICE_RELATABLE_QUERY, variables)
        return unwrap(data, "migratedInvoiceRelatable")
    except MolonionError as e:
        return _err(e)


MIGRATED_INVOICES_QUERY = """
query ($companyId: Int!, $options: MigratedInvoiceOptions) {
  migratedInvoices(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_migrated_invoices(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as faturas migradas de uma empresa (documentos históricos
    importados), com os campos principais de cada uma: número, data, série, entidade,
    valor total e estado. Para obter o detalhe completo usa `get_migrated_invoice`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_INVOICES_QUERY, variables)
        return unwrap(data, "migratedInvoices")
    except MolonionError as e:
        return _err(e)


MIGRATED_PURCHASE_ORDER_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  migratedPurchaseOrder(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscountValue
      totalDiscountValue
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      expirationDate
      maturityDateDays
      maturityDateName
      yourReference
      ourReference
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      file
      fileOriginal
      downloads
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_migrated_purchase_order(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma encomenda de compra migrada (documento histórico de
    compra importado de outro sistema) pelo seu ID de documento: dados do documento,
    totais, reconciliação, dados do fornecedor (`entityName`/`entityVat`), vencimento e o
    ficheiro arquivado (`file`/`fileOriginal`). As linhas de produtos, os impostos, o
    fornecedor completo e os documentos relacionados não são incluídos neste selection
    set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (encomenda de compra migrada) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(MIGRATED_PURCHASE_ORDER_QUERY, variables)
        return unwrap(data, "migratedPurchaseOrder")
    except MolonionError as e:
        return _err(e)


MIGRATED_PURCHASE_ORDER_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  migratedPurchaseOrderGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_migrated_purchase_order_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma encomenda de
    compra migrada. Devolve `token`, `path` e `filename`, que se combinam para construir
    o URL de download do PDF. Nota: ao contrário de outras operações, não recebe
    `companyId` — apenas o `documentId`.

    Args:
        document_id: ID do documento (encomenda de compra migrada) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            MIGRATED_PURCHASE_ORDER_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "migratedPurchaseOrderGetPDFToken")
    except MolonionError as e:
        return _err(e)


MIGRATED_PURCHASE_ORDER_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  migratedPurchaseOrderGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_migrated_purchase_order_zip_token(
    company_id: int, full_path: str
) -> Any:
    """Gera um token temporário e seguro para descarregar várias encomendas de compra
    migradas como um arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam
    para construir o URL de download. O `full_path` identifica o ZIP a descarregar
    (caminho devolvido por uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(
            MIGRATED_PURCHASE_ORDER_ZIP_TOKEN_QUERY, variables
        )
        return unwrap(data, "migratedPurchaseOrderGetZIPToken")
    except MolonionError as e:
        return _err(e)


MIGRATED_PURCHASE_ORDER_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  migratedPurchaseOrderLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_migrated_purchase_order_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às encomendas de compra migradas de uma
    empresa: criações, modificações e remoções. Cada entrada indica a operação
    (`operation`), os valores antigos/novos (`oldValues`/`newValues`), quem a fez
    (`userId`, `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma encomenda de compra migrada específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_PURCHASE_ORDER_LOGS_QUERY, variables)
        return unwrap(data, "migratedPurchaseOrderLogs")
    except MolonionError as e:
        return _err(e)


MIGRATED_PURCHASE_ORDER_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  migratedPurchaseOrderMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_migrated_purchase_order_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de encomendas de compra migradas e o
    estado de entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`).
    Útil para confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os
    logs detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_migrated_purchase_order_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            MIGRATED_PURCHASE_ORDER_MAIL_RECIPIENTS_QUERY, variables
        )
        return unwrap(data, "migratedPurchaseOrderMailRecipients")
    except MolonionError as e:
        return _err(e)


MIGRATED_PURCHASE_ORDER_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  migratedPurchaseOrderMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_migrated_purchase_order_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de emails enviados de uma encomenda de compra migrada: para cada
    envio, o email, o conteúdo, a data (`createdAt`) e o `deliveryId`. Usa o `deliveryId`
    de um envio em `get_migrated_purchase_order_mail_recipients` para ver os destinatários
    e o estado de entrega desse envio.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (encomenda de compra migrada) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            MIGRATED_PURCHASE_ORDER_MAILS_HISTORY_QUERY, variables
        )
        return unwrap(data, "migratedPurchaseOrderMailsHistory")
    except MolonionError as e:
        return _err(e)


MIGRATED_PURCHASE_ORDER_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  migratedPurchaseOrderNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_migrated_purchase_order_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para uma encomenda de compra migrada numa dada
    série de documentos. Devolve `number` (o próximo número) e `name` (o nome da série).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(
            MIGRATED_PURCHASE_ORDER_NEXT_NUMBER_QUERY, variables
        )
        return unwrap(data, "migratedPurchaseOrderNextNumber")
    except MolonionError as e:
        return _err(e)


MIGRATED_PURCHASE_ORDER_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: MigratedPurchaseOrderOptions) {
  migratedPurchaseOrderRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_migrated_purchase_order_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as encomendas de compra migradas de uma entidade que podem ser
    relacionadas/ligadas a outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (fornecedor) cujas encomendas de compra migradas
            relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            MIGRATED_PURCHASE_ORDER_RELATABLE_QUERY, variables
        )
        return unwrap(data, "migratedPurchaseOrderRelatable")
    except MolonionError as e:
        return _err(e)


MIGRATED_PURCHASE_ORDERS_QUERY = """
query ($companyId: Int!, $options: MigratedPurchaseOrderOptions) {
  migratedPurchaseOrders(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_migrated_purchase_orders(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as encomendas de compra migradas de uma empresa (documentos
    históricos de compra importados), com os campos principais de cada uma: número, data,
    série, fornecedor, valor total e estado. Para obter o detalhe completo usa
    `get_migrated_purchase_order`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_PURCHASE_ORDERS_QUERY, variables)
        return unwrap(data, "migratedPurchaseOrders")
    except MolonionError as e:
        return _err(e)


MIGRATED_RECEIPT_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  migratedReceipt(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      financialDiscount
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      notes
      notesRelatedDocs
      pdfExport
      file
      fileOriginal
      downloads
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_migrated_receipt(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de um recibo migrado (documento histórico importado de outro
    sistema) pelo seu ID de documento: dados do documento, valor total, desconto
    financeiro (`financialDiscount`), o estado de reconciliação com os documentos pagos
    (`reconciledValue`, `remainingReconciledValue`, `reconciliationPercentage`), dados da
    entidade e o ficheiro arquivado (`file`/`fileOriginal`). Os documentos pagos por este
    recibo e a entidade completa não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (recibo migrado) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(MIGRATED_RECEIPT_QUERY, variables)
        return unwrap(data, "migratedReceipt")
    except MolonionError as e:
        return _err(e)


MIGRATED_RECEIPT_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  migratedReceiptGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_migrated_receipt_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de um recibo migrado.
    Devolve `token`, `path` e `filename`, que se combinam para construir o URL de
    download do PDF. Nota: ao contrário de outras operações, não recebe `companyId` —
    apenas o `documentId`.

    Args:
        document_id: ID do documento (recibo migrado) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            MIGRATED_RECEIPT_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "migratedReceiptGetPDFToken")
    except MolonionError as e:
        return _err(e)


MIGRATED_RECEIPT_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  migratedReceiptGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_migrated_receipt_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar vários recibos migrados como um
    arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para construir o
    URL de download. O `full_path` identifica o ZIP a descarregar (caminho devolvido por
    uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(MIGRATED_RECEIPT_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "migratedReceiptGetZIPToken")
    except MolonionError as e:
        return _err(e)


MIGRATED_RECEIPT_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  migratedReceiptLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_migrated_receipt_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos recibos migrados de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de um recibo migrado específico (corresponde
            a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_RECEIPT_LOGS_QUERY, variables)
        return unwrap(data, "migratedReceiptLogs")
    except MolonionError as e:
        return _err(e)


MIGRATED_RECEIPT_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  migratedReceiptMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_migrated_receipt_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de recibos migrados e o estado de
    entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para
    confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os logs
    detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_migrated_receipt_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            MIGRATED_RECEIPT_MAIL_RECIPIENTS_QUERY, variables
        )
        return unwrap(data, "migratedReceiptMailRecipients")
    except MolonionError as e:
        return _err(e)


MIGRATED_RECEIPT_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  migratedReceiptMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_migrated_receipt_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de emails enviados de um recibo migrado: para cada envio, o
    email, o conteúdo, a data (`createdAt`) e o `deliveryId`. Usa o `deliveryId` de um
    envio em `get_migrated_receipt_mail_recipients` para ver os destinatários e o estado
    de entrega desse envio.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (recibo migrado) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            MIGRATED_RECEIPT_MAILS_HISTORY_QUERY, variables
        )
        return unwrap(data, "migratedReceiptMailsHistory")
    except MolonionError as e:
        return _err(e)


MIGRATED_RECEIPT_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  migratedReceiptNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_migrated_receipt_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para um recibo migrado numa dada série de
    documentos. Devolve `number` (o próximo número) e `name` (o nome da série).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(MIGRATED_RECEIPT_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "migratedReceiptNextNumber")
    except MolonionError as e:
        return _err(e)


MIGRATED_RECEIPT_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: MigratedReceiptOptions) {
  migratedReceiptRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_migrated_receipt_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os recibos migrados de uma entidade que podem ser relacionados/ligados a
    outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente) cujos recibos migrados relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_RECEIPT_RELATABLE_QUERY, variables)
        return unwrap(data, "migratedReceiptRelatable")
    except MolonionError as e:
        return _err(e)


MIGRATED_RECEIPTS_QUERY = """
query ($companyId: Int!, $options: MigratedReceiptOptions) {
  migratedReceipts(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_migrated_receipts(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) os recibos migrados de uma empresa (documentos históricos
    importados), com os campos principais de cada um: número, data, série, entidade,
    valor total e estado. Para obter o detalhe completo usa `get_migrated_receipt`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_RECEIPTS_QUERY, variables)
        return unwrap(data, "migratedReceipts")
    except MolonionError as e:
        return _err(e)


MIGRATED_SIMPLIFIED_INVOICE_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  migratedSimplifiedInvoice(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscountValue
      totalDiscountValue
      financialDiscount
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      expirationDate
      maturityDateDays
      maturityDateName
      salespersonCommission
      notes
      notesRelatedDocs
      pdfExport
      file
      fileOriginal
      downloads
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_migrated_simplified_invoice(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma fatura simplificada migrada (documento histórico
    importado de outro sistema) pelo seu ID de documento: dados do documento, totais,
    descontos (`financialDiscount`), impostos, reconciliação, dados da entidade,
    vencimento, comissão do vendedor e o ficheiro arquivado (`file`/`fileOriginal`). As
    linhas de produtos, os impostos detalhados, o cliente e os documentos relacionados
    não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (fatura simplificada migrada) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(MIGRATED_SIMPLIFIED_INVOICE_QUERY, variables)
        return unwrap(data, "migratedSimplifiedInvoice")
    except MolonionError as e:
        return _err(e)


MIGRATED_SIMPLIFIED_INVOICE_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  migratedSimplifiedInvoiceGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_migrated_simplified_invoice_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma fatura
    simplificada migrada. Devolve `token`, `path` e `filename`, que se combinam para
    construir o URL de download do PDF. Nota: ao contrário de outras operações, não
    recebe `companyId` — apenas o `documentId`.

    Args:
        document_id: ID do documento (fatura simplificada migrada) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            MIGRATED_SIMPLIFIED_INVOICE_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "migratedSimplifiedInvoiceGetPDFToken")
    except MolonionError as e:
        return _err(e)


MIGRATED_SIMPLIFIED_INVOICE_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  migratedSimplifiedInvoiceGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_migrated_simplified_invoice_zip_token(
    company_id: int, full_path: str
) -> Any:
    """Gera um token temporário e seguro para descarregar várias faturas simplificadas
    migradas como um arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam
    para construir o URL de download. O `full_path` identifica o ZIP a descarregar
    (caminho devolvido por uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(
            MIGRATED_SIMPLIFIED_INVOICE_ZIP_TOKEN_QUERY, variables
        )
        return unwrap(data, "migratedSimplifiedInvoiceGetZIPToken")
    except MolonionError as e:
        return _err(e)


MIGRATED_SIMPLIFIED_INVOICE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  migratedSimplifiedInvoiceLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_migrated_simplified_invoice_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às faturas simplificadas migradas de uma
    empresa: criações, modificações e remoções. Cada entrada indica a operação
    (`operation`), os valores antigos/novos (`oldValues`/`newValues`), quem a fez
    (`userId`, `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma fatura simplificada migrada específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_SIMPLIFIED_INVOICE_LOGS_QUERY, variables)
        return unwrap(data, "migratedSimplifiedInvoiceLogs")
    except MolonionError as e:
        return _err(e)


MIGRATED_SIMPLIFIED_INVOICE_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  migratedSimplifiedInvoiceMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_migrated_simplified_invoice_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de faturas simplificadas migradas e o
    estado de entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`).
    Útil para confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os
    logs detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_migrated_simplified_invoice_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            MIGRATED_SIMPLIFIED_INVOICE_MAIL_RECIPIENTS_QUERY, variables
        )
        return unwrap(data, "migratedSimplifiedInvoiceMailRecipients")
    except MolonionError as e:
        return _err(e)


MIGRATED_SIMPLIFIED_INVOICE_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  migratedSimplifiedInvoiceMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_migrated_simplified_invoice_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de emails enviados de uma fatura simplificada migrada: para cada
    envio, o email, o conteúdo, a data (`createdAt`) e o `deliveryId`. Usa o `deliveryId`
    de um envio em `get_migrated_simplified_invoice_mail_recipients` para ver os
    destinatários e o estado de entrega desse envio.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (fatura simplificada migrada) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            MIGRATED_SIMPLIFIED_INVOICE_MAILS_HISTORY_QUERY, variables
        )
        return unwrap(data, "migratedSimplifiedInvoiceMailsHistory")
    except MolonionError as e:
        return _err(e)


MIGRATED_SIMPLIFIED_INVOICE_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  migratedSimplifiedInvoiceNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_migrated_simplified_invoice_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para uma fatura simplificada migrada numa dada
    série de documentos. Devolve `number` (o próximo número) e `name` (o nome da série).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(
            MIGRATED_SIMPLIFIED_INVOICE_NEXT_NUMBER_QUERY, variables
        )
        return unwrap(data, "migratedSimplifiedInvoiceNextNumber")
    except MolonionError as e:
        return _err(e)


MIGRATED_SIMPLIFIED_INVOICE_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: MigratedSimplifiedInvoiceOptions) {
  migratedSimplifiedInvoiceRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_migrated_simplified_invoice_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as faturas simplificadas migradas de uma entidade que podem ser
    relacionadas/ligadas a outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente) cujas faturas simplificadas migradas
            relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            MIGRATED_SIMPLIFIED_INVOICE_RELATABLE_QUERY, variables
        )
        return unwrap(data, "migratedSimplifiedInvoiceRelatable")
    except MolonionError as e:
        return _err(e)


MIGRATED_SIMPLIFIED_INVOICES_QUERY = """
query ($companyId: Int!, $options: MigratedSimplifiedInvoiceOptions) {
  migratedSimplifiedInvoices(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_migrated_simplified_invoices(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as faturas simplificadas migradas de uma empresa (documentos
    históricos importados), com os campos principais de cada uma: número, data, série,
    entidade, valor total e estado. Para obter o detalhe completo usa
    `get_migrated_simplified_invoice`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(MIGRATED_SIMPLIFIED_INVOICES_QUERY, variables)
        return unwrap(data, "migratedSimplifiedInvoices")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Notificações
# ---------------------------------------------------------------------------
NOTIFICATIONS_QUERY = """
query ($options: NotificationOptions, $userId: Int) {
  notifications(options: $options, userId: $userId) {
    errors { field msg }
    data {
      notificationId
      ackd
      type
      title
      titleParams
      extraParams
      path
      createdAt
    }
  }
}
"""


@mcp.tool()
async def list_notifications(
    user_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as notificações do utilizador autenticado: para cada uma, se já foi lida
    (`ackd`), o tipo (`type`), o título e os seus parâmetros (`title`, `titleParams`,
    `extraParams`), o caminho/link (`path`) e a data (`createdAt`). Ao contrário da
    maioria das operações, não recebe `companyId` (é a nível do utilizador). Os objetos
    `user` e `company` ligados não são incluídos neste selection set.

    Args:
        user_id: opcional; ID do utilizador cujas notificações se pretendem (por omissão,
            o utilizador autenticado).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {}
    if options:
        variables["options"] = options
    if user_id is not None:
        variables["userId"] = user_id
    try:
        data = await _client.query(NOTIFICATIONS_QUERY, variables)
        return unwrap(data, "notifications")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Métodos de pagamento
# ---------------------------------------------------------------------------
PAYMENT_METHOD_QUERY = """
query ($companyId: Int!, $paymentMethodId: Int!) {
  paymentMethod(companyId: $companyId, paymentMethodId: $paymentMethodId) {
    errors { field msg }
    data {
      paymentMethodId
      name
      type
      commission
      fixedCommission
      isDefault
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_payment_method(company_id: int, payment_method_id: int) -> Any:
    """Obtém um método de pagamento de uma empresa pelo seu ID: o nome (`name`), o tipo
    (`type`), a comissão (`commission`/`fixedCommission`) e se é o método por omissão
    (`isDefault`). O objeto `company` ligado não é incluído neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        payment_method_id: ID do método de pagamento a obter.
    """
    variables = {"companyId": company_id, "paymentMethodId": payment_method_id}
    try:
        data = await _client.query(PAYMENT_METHOD_QUERY, variables)
        return unwrap(data, "paymentMethod")
    except MolonionError as e:
        return _err(e)


PAYMENT_METHOD_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  paymentMethodLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_payment_method_logs(
    company_id: int,
    payment_method_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos métodos de pagamento de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        payment_method_id: opcional; filtra os logs de um método de pagamento específico
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if payment_method_id is not None:
        options["relatedId"] = payment_method_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PAYMENT_METHOD_LOGS_QUERY, variables)
        return unwrap(data, "paymentMethodLogs")
    except MolonionError as e:
        return _err(e)


PAYMENT_METHODS_QUERY = """
query ($companyId: Int!, $options: PaymentMethodOptions) {
  paymentMethods(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      paymentMethodId
      name
      type
      commission
      fixedCommission
      isDefault
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_payment_methods(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os métodos de pagamento configurados numa empresa, cada um com o nome
    (`name`), o tipo (`type`), a comissão (`commission`/`fixedCommission`) e se é o método
    por omissão (`isDefault`). Para obter um único pelo seu ID usa `get_payment_method`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PAYMENT_METHODS_QUERY, variables)
        return unwrap(data, "paymentMethods")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Devoluções de pagamento (documentos)
# ---------------------------------------------------------------------------
PAYMENT_RETURN_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  paymentReturn(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      financialDiscount
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      yourReference
      ourReference
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      file
      fileOriginal
      downloads
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_payment_return(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma devolução de pagamento (estorno) pelo seu ID de
    documento: dados do documento, valor total, desconto financeiro (`financialDiscount`),
    o estado de reconciliação (`reconciledValue`, `remainingReconciledValue`,
    `reconciliationPercentage`), dados da entidade e o ficheiro arquivado
    (`file`/`fileOriginal`). Os documentos associados, os métodos de pagamento e a
    entidade completa não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (devolução de pagamento) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(PAYMENT_RETURN_QUERY, variables)
        return unwrap(data, "paymentReturn")
    except MolonionError as e:
        return _err(e)


PAYMENT_RETURN_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  paymentReturnGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_payment_return_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma devolução de
    pagamento. Devolve `token`, `path` e `filename`, que se combinam para construir o URL
    de download do PDF. Nota: ao contrário de outras operações, não recebe `companyId` —
    apenas o `documentId`.

    Args:
        document_id: ID do documento (devolução de pagamento) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            PAYMENT_RETURN_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "paymentReturnGetPDFToken")
    except MolonionError as e:
        return _err(e)


PAYMENT_RETURN_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  paymentReturnGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_payment_return_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar várias devoluções de pagamento
    como um arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para
    construir o URL de download. O `full_path` identifica o ZIP a descarregar (caminho
    devolvido por uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(PAYMENT_RETURN_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "paymentReturnGetZIPToken")
    except MolonionError as e:
        return _err(e)


PAYMENT_RETURN_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  paymentReturnLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_payment_return_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às devoluções de pagamento de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma devolução de pagamento específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PAYMENT_RETURN_LOGS_QUERY, variables)
        return unwrap(data, "paymentReturnLogs")
    except MolonionError as e:
        return _err(e)


PAYMENT_RETURN_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  paymentReturnMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_payment_return_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de devoluções de pagamento e o estado
    de entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para
    confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os logs
    detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_payment_return_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PAYMENT_RETURN_MAIL_RECIPIENTS_QUERY, variables)
        return unwrap(data, "paymentReturnMailRecipients")
    except MolonionError as e:
        return _err(e)


PAYMENT_RETURN_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  paymentReturnMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_payment_return_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de emails enviados de uma devolução de pagamento: para cada
    envio, o email, o conteúdo, a data (`createdAt`) e o `deliveryId`. Usa o `deliveryId`
    de um envio em `get_payment_return_mail_recipients` para ver os destinatários e o
    estado de entrega desse envio.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (devolução de pagamento) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PAYMENT_RETURN_MAILS_HISTORY_QUERY, variables)
        return unwrap(data, "paymentReturnMailsHistory")
    except MolonionError as e:
        return _err(e)


PAYMENT_RETURN_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  paymentReturnNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_payment_return_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para uma devolução de pagamento numa dada série
    de documentos. Devolve `number` (o próximo número) e `name` (o nome da série).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(PAYMENT_RETURN_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "paymentReturnNextNumber")
    except MolonionError as e:
        return _err(e)


PAYMENT_RETURN_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: PaymentReturnOptions) {
  paymentReturnRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_payment_return_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as devoluções de pagamento de uma entidade que podem ser relacionadas/ligadas
    a outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente) cujas devoluções de pagamento relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PAYMENT_RETURN_RELATABLE_QUERY, variables)
        return unwrap(data, "paymentReturnRelatable")
    except MolonionError as e:
        return _err(e)


PAYMENT_RETURNS_QUERY = """
query ($companyId: Int!, $options: PaymentReturnOptions) {
  paymentReturns(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      reconciledValue
      remainingReconciledValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_payment_returns(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as devoluções de pagamento de uma empresa, com os campos
    principais de cada uma: número, data, série, entidade, valor total e estado de
    reconciliação (`reconciledValue`, `remainingReconciledValue`). Para obter o detalhe
    completo usa `get_payment_return`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PAYMENT_RETURNS_QUERY, variables)
        return unwrap(data, "paymentReturns")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Classes de preço
# ---------------------------------------------------------------------------
PRICE_CLASS_QUERY = """
query ($companyId: Int!, $priceClassId: Int!) {
  priceClass(companyId: $companyId, priceClassId: $priceClassId) {
    errors { field msg }
    data {
      priceClassId
      name
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_price_class(company_id: int, price_class_id: int) -> Any:
    """Obtém uma classe de preço de uma empresa pelo seu ID: o nome (`name`) e a
    visibilidade. As classes de preço permitem definir preços diferenciados por
    cliente/grupo. O objeto `company` ligado não é incluído neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        price_class_id: ID da classe de preço a obter.
    """
    variables = {"companyId": company_id, "priceClassId": price_class_id}
    try:
        data = await _client.query(PRICE_CLASS_QUERY, variables)
        return unwrap(data, "priceClass")
    except MolonionError as e:
        return _err(e)


PRICE_CLASSES_QUERY = """
query ($companyId: Int!, $options: PriceClassOptions) {
  priceClasses(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      priceClassId
      name
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_price_classes(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as classes de preço configuradas numa empresa, cada uma com o nome (`name`)
    e a visibilidade. Permitem definir preços diferenciados por cliente/grupo. Para obter
    uma única pelo seu ID usa `get_price_class`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PRICE_CLASSES_QUERY, variables)
        return unwrap(data, "priceClasses")
    except MolonionError as e:
        return _err(e)


PRICE_CLASS_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  priceClassLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_price_class_logs(
    company_id: int,
    price_class_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às classes de preço de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        price_class_id: opcional; filtra os logs de uma classe de preço específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if price_class_id is not None:
        options["relatedId"] = price_class_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PRICE_CLASS_LOGS_QUERY, variables)
        return unwrap(data, "priceClassLogs")
    except MolonionError as e:
        return _err(e)


# NOTA: este envelope usa `count` (Int) em vez de `data` — o `unwrap()` não se aplica.
PRICE_CLASS_PRODUCTS_APPLIED_QUERY = """
query ($companyId: Int!, $priceClassId: Int!) {
  priceClassProductsApplied(companyId: $companyId, priceClassId: $priceClassId) {
    errors { field msg }
    count
  }
}
"""


@mcp.tool()
async def get_price_class_products_applied(
    company_id: int, price_class_id: int
) -> Any:
    """Obtém o número de produtos a que uma classe de preço está aplicada numa empresa.
    Devolve a contagem (`count`). Útil para saber o impacto de alterar/remover uma classe
    de preço.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        price_class_id: ID da classe de preço.
    """
    variables = {"companyId": company_id, "priceClassId": price_class_id}
    try:
        raw = await _client.query(PRICE_CLASS_PRODUCTS_APPLIED_QUERY, variables)
        node = (raw or {}).get("priceClassProductsApplied") or {}
        if node.get("errors"):
            raise MolonionError(
                "A operação 'priceClassProductsApplied' devolveu erros.",
                errors=node["errors"],
            )
        return {"count": node.get("count")}
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Produtos
# ---------------------------------------------------------------------------
PRODUCT_QUERY = """
query ($companyId: Int!, $productId: Int!) {
  product(companyId: $companyId, productId: $productId) {
    errors { field msg }
    data {
      productId
      type
      reference
      name
      summary
      notes
      price
      priceWithTaxes
      hasStock
      stock
      minStock
      hasStockMovements
      costPrice
      totalCostPrice
      totalSale
      img
      exemptionReason
      posFavorite
      visible
      variantsCount
      parentId
      productCategoryId
      warehouseId
      measurementUnitId
      propertyGroupId
      companyId
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_product(company_id: int, product_id: int) -> Any:
    """Obtém os detalhes de um produto pelo seu ID: identificação (`reference`, `name`,
    `summary`), tipo (`type`), preços (`price`, `priceWithTaxes`, `costPrice`), stock
    (`hasStock`, `stock`, `minStock`, `hasStockMovements`), motivo de isenção e os IDs das
    entidades associadas (`productCategoryId`, `warehouseId`, `measurementUnitId`,
    `parentId` para variantes) para encadear com outras operações. Os objetos ligados
    completos (categoria, armazém, fornecedores, impostos, identificações, variantes,
    campos personalizados) não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        product_id: ID do produto a obter.
    """
    variables = {"companyId": company_id, "productId": product_id}
    try:
        data = await _client.query(PRODUCT_QUERY, variables)
        return unwrap(data, "product")
    except MolonionError as e:
        return _err(e)


PRODUCT_CATEGORIES_QUERY = """
query ($companyId: Int!, $options: ProductCategoryOptions) {
  productCategories(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      productCategoryId
      name
      summary
      img
      posVisible
      visible
      parentId
      cntChildCategories
      cntChildProducts
      cntInactiveChildProducts
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_product_categories(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as categorias de produto de uma empresa (estrutura hierárquica de catálogo),
    cada uma com o nome (`name`), o resumo, a categoria-pai (`parentId`) e as contagens de
    subcategorias e produtos (`cntChildCategories`, `cntChildProducts`,
    `cntInactiveChildProducts`). Os objetos ligados (empresa, pai, filhos) não são
    incluídos neste selection set; usa `parentId` para reconstruir a árvore.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PRODUCT_CATEGORIES_QUERY, variables)
        return unwrap(data, "productCategories")
    except MolonionError as e:
        return _err(e)


PRODUCT_CATEGORY_QUERY = """
query ($companyId: Int!, $productCategoryId: Int!) {
  productCategory(companyId: $companyId, productCategoryId: $productCategoryId) {
    errors { field msg }
    data {
      productCategoryId
      name
      summary
      img
      posVisible
      visible
      parentId
      cntChildCategories
      cntChildProducts
      cntInactiveChildProducts
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_product_category(company_id: int, product_category_id: int) -> Any:
    """Obtém uma categoria de produto de uma empresa pelo seu ID: o nome (`name`), o
    resumo, a categoria-pai (`parentId`) e as contagens de subcategorias e produtos
    (`cntChildCategories`, `cntChildProducts`, `cntInactiveChildProducts`). Os objetos
    ligados (empresa, pai, filhos) não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        product_category_id: ID da categoria de produto a obter.
    """
    variables = {"companyId": company_id, "productCategoryId": product_category_id}
    try:
        data = await _client.query(PRODUCT_CATEGORY_QUERY, variables)
        return unwrap(data, "productCategory")
    except MolonionError as e:
        return _err(e)


PRODUCT_CATEGORY_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  productCategoryLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_product_category_logs(
    company_id: int,
    product_category_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às categorias de produto de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`),
    os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        product_category_id: opcional; filtra os logs de uma categoria específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if product_category_id is not None:
        options["relatedId"] = product_category_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PRODUCT_CATEGORY_LOGS_QUERY, variables)
        return unwrap(data, "productCategoryLogs")
    except MolonionError as e:
        return _err(e)


# `productDocuments` devolve a union `ProductDocumentRead` (25 tipos de documento onde o
# produto aparece como linha). Como nas outras unions ([[molonion-union-types]]),
# seleciona-se via inline fragments + `__typename`. Listamos os tipos de documento padrão
# (omitimos RecurringAgreement/TableConsult/PurchaseRecurringAgreement, que não partilham
# o conjunto comum — surgem na mesma via `__typename`).
PRODUCT_DOCUMENT_TYPES = [
    "InvoiceRead",
    "SimplifiedInvoiceRead",
    "InvoiceReceiptRead",
    "CreditNoteRead",
    "DebitNoteRead",
    "ProFormaInvoiceRead",
    "EstimateRead",
    "BillsOfLadingRead",
    "DeliveryNoteRead",
    "CustomerReturnNoteRead",
    "PurchaseOrderRead",
    "SupplierPurchaseOrderRead",
    "SupplierInvoiceRead",
    "SupplierCreditNoteRead",
    "SupplierBillsOfLadingRead",
    "MigratedInvoiceRead",
    "MigratedSimplifiedInvoiceRead",
    "MigratedInvoiceReceiptRead",
    "MigratedCreditNoteRead",
    "MigratedDebitNoteRead",
    "MigratedEstimateRead",
    "MigratedPurchaseOrderRead",
]
_product_document_fragments = "\n".join(
    f"      ... on {t} {{ {_DOC_FRAGMENT_FIELDS} }}"
    for t in PRODUCT_DOCUMENT_TYPES
)

PRODUCT_DOCUMENTS_QUERY = """
query ($companyId: Int!, $productId: Int!, $options: ProductDocumentsOptions) {
  productDocuments(companyId: $companyId, productId: $productId, options: $options) {
    errors { field msg }
    data {
      __typename
__FRAGMENTS__
    }
  }
}
""".replace("__FRAGMENTS__", _product_document_fragments)


@mcp.tool()
async def get_product_documents(
    company_id: int,
    product_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os documentos onde um produto aparece como linha (faturas, guias, notas,
    encomendas, etc.), com os campos comuns de cada documento (número, data, série, total,
    estado). O campo `__typename` identifica o tipo de cada documento. Útil para ver o
    histórico de movimentação de um produto.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        product_id: ID do produto cujos documentos se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "productId": product_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PRODUCT_DOCUMENTS_QUERY, variables)
        return unwrap(data, "productDocuments")
    except MolonionError as e:
        return _err(e)


PRODUCT_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  productLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_product_logs(
    company_id: int,
    product_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos produtos de uma empresa: criações,
    modificações e remoções. Cada entrada indica a operação (`operation`), os valores
    antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`, `email`)
    e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        product_id: opcional; filtra os logs de um produto específico (corresponde a
            `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if product_id is not None:
        options["relatedId"] = product_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PRODUCT_LOGS_QUERY, variables)
        return unwrap(data, "productLogs")
    except MolonionError as e:
        return _err(e)


PRODUCTS_QUERY = """
query ($companyId: Int!, $options: ProductOptions) {
  products(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      productId
      type
      reference
      name
      price
      priceWithTaxes
      hasStock
      stock
      minStock
      costPrice
      productCategoryId
      warehouseId
      measurementUnitId
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_products(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) os produtos de uma empresa, com os campos principais de cada um:
    referência, nome, tipo, preços (`price`, `priceWithTaxes`, `costPrice`), stock
    (`hasStock`, `stock`, `minStock`) e os IDs de categoria/armazém/unidade. Para o detalhe
    completo de um produto usa `get_product`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PRODUCTS_QUERY, variables)
        return unwrap(data, "products")
    except MolonionError as e:
        return _err(e)


PROFIT_MARGINS_BY_PRODUCT_QUERY = """
query ($companyId: Int!, $options: ProfitMarginsOptions) {
  profitMarginsByProduct(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      productId
      productParentId
      avgCostPrice
      avgSellingPrice
      qtySold
      totalProfitMargin
      percentageProfitMargin
      markupPercentage
      markupIndex
      product { productId reference name }
    }
  }
}
"""


@mcp.tool()
async def list_profit_margins_by_product(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as margens de lucro por produto de uma empresa: para cada produto, o custo
    e preço médios (`avgCostPrice`, `avgSellingPrice`), a quantidade vendida (`qtySold`),
    a margem total e percentual (`totalProfitMargin`, `percentageProfitMargin`) e o markup
    (`markupPercentage`, `markupIndex`). Inclui a identificação mínima do produto
    (`product`: referência, nome). Útil para análise de rentabilidade.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PROFIT_MARGINS_BY_PRODUCT_QUERY, variables)
        return unwrap(data, "profitMarginsByProduct")
    except MolonionError as e:
        return _err(e)


# NOTA: aqui o `options` é uma LISTA (`[ProfitMarginsOptions]`).
PROFIT_MARGINS_PRODUCT_DOCUMENTS_QUERY = """
query ($companyId: Int!, $productId: Int!, $options: [ProfitMarginsOptions]) {
  profitMarginsProductDocuments(companyId: $companyId, productId: $productId, options: $options) {
    errors { field msg }
    data {
      documentProductId
      productId
      productParentId
      documentId
      qty
      price
      grossValue
      discountValue
      taxesValue
      retentionsValue
      totalValue
      product { productId reference name }
    }
  }
}
"""


@mcp.tool()
async def list_profit_margins_product_documents(
    company_id: int,
    product_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as linhas de documento que contribuem para a margem de lucro de um produto:
    para cada linha, o documento (`documentId`), a quantidade (`qty`), o preço (`price`),
    o valor bruto/desconto/impostos/total e a identificação mínima do produto. Útil para
    detalhar como se forma a margem de um produto.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        product_id: ID do produto cujas linhas de margem se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    opt: dict[str, Any] = {}
    if page is not None and qty is not None:
        opt["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "productId": product_id}
    if opt:
        variables["options"] = [opt]
    try:
        data = await _client.query(PROFIT_MARGINS_PRODUCT_DOCUMENTS_QUERY, variables)
        return unwrap(data, "profitMarginsProductDocuments")
    except MolonionError as e:
        return _err(e)


PROFIT_MARGINS_TOTALS_QUERY = """
query ($companyId: Int!, $options: ProfitMarginsTotalsOptions) {
  profitMarginsTotals(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      productsCount
      productsQtySold
      totalProfitMargin
      percentageProfitMargin
      markupPercentage
      markupIndex
    }
  }
}
"""


@mcp.tool()
async def get_profit_margins_totals(company_id: int) -> Any:
    """Obtém os totais agregados de margem de lucro de uma empresa: o número de produtos
    (`productsCount`), a quantidade total vendida (`productsQtySold`), a margem total e
    percentual (`totalProfitMargin`, `percentageProfitMargin`) e o markup
    (`markupPercentage`, `markupIndex`). Útil para uma vista global da rentabilidade.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
    """
    try:
        data = await _client.query(
            PROFIT_MARGINS_TOTALS_QUERY, {"companyId": company_id}
        )
        return unwrap(data, "profitMarginsTotals")
    except MolonionError as e:
        return _err(e)


PROFIT_MARGINS_TEMPLATES_QUERY = """
query ($companyId: Int!) {
  profitMarginsUserSettingsTemplates(companyId: $companyId) {
    errors { field msg }
    data {
      userSettingsTemplateId
      formName
      name
    }
  }
}
"""


@mcp.tool()
async def list_profit_margins_templates(company_id: int) -> Any:
    """Lista os modelos (templates) de definições do utilizador para o ecrã de análise de
    margens de lucro — filtros/colunas guardados pelo utilizador para reutilizar. Cada
    modelo tem `userSettingsTemplateId`, `formName` (o formulário a que se aplica) e
    `name`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
    """
    try:
        data = await _client.query(
            PROFIT_MARGINS_TEMPLATES_QUERY, {"companyId": company_id}
        )
        return unwrap(data, "profitMarginsUserSettingsTemplates")
    except MolonionError as e:
        return _err(e)


# ===========================================================================
# Faturas pró-forma (ProForma)
# ===========================================================================

PRO_FORMA_INVOICE_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  proFormaInvoice(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscountValue
      totalDiscountValue
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      expirationDate
      maturityDateDays
      maturityDateName
      yourReference
      ourReference
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      deliveryMethodName
      deliveryVehicleName
      deliveryVehicleLicensePlate
      deliveryLoadDate
      deliveryLoadAddress
      deliveryLoadCity
      deliveryLoadZipCode
      deliveryUnloadAddress
      deliveryUnloadCity
      deliveryUnloadZipCode
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_pro_forma_invoice(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma fatura pró-forma pelo seu ID de documento. A pró-forma
    é um documento preliminar (proposta/confirmação de encomenda) emitido antes da
    fatura final. Inclui os dados do documento (número, série, data, estado, totais),
    os dados da entidade/cliente (`entityName`, `entityVat`, morada), o estado de
    reconciliação, a validade/vencimento (`expirationDate`, `maturityDateDays`,
    `maturityDateName`) e os dados de transporte (método de entrega, veículo/matrícula,
    carga/descarga). As linhas de produtos, os impostos, o cliente completo, os
    documentos relacionados e os dados AT não são incluídos neste selection set — podem
    ser adicionados se necessário.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (fatura pró-forma) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(PRO_FORMA_INVOICE_QUERY, variables)
        return unwrap(data, "proFormaInvoice")
    except MolonionError as e:
        return _err(e)


PRO_FORMA_INVOICE_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  proFormaInvoiceGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_pro_forma_invoice_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma fatura pró-forma.
    Devolve `token`, `path` e `filename`, que se combinam para construir o URL de
    download do PDF. Nota: ao contrário de outras operações, não recebe `companyId` —
    apenas o `documentId`.

    Args:
        document_id: ID do documento (fatura pró-forma) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            PRO_FORMA_INVOICE_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "proFormaInvoiceGetPDFToken")
    except MolonionError as e:
        return _err(e)


PRO_FORMA_INVOICE_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  proFormaInvoiceGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_pro_forma_invoice_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar várias faturas pró-forma como um
    arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para construir o
    URL de download. O `full_path` identifica o ZIP a descarregar (caminho devolvido por
    uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(PRO_FORMA_INVOICE_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "proFormaInvoiceGetZIPToken")
    except MolonionError as e:
        return _err(e)


PRO_FORMA_INVOICE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  proFormaInvoiceLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_pro_forma_invoice_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às faturas pró-forma de uma empresa: criações,
    modificações e remoções. Cada entrada indica a operação (`operation`), os valores
    antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`, `email`)
    e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma fatura pró-forma específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PRO_FORMA_INVOICE_LOGS_QUERY, variables)
        return unwrap(data, "proFormaInvoiceLogs")
    except MolonionError as e:
        return _err(e)


PRO_FORMA_INVOICE_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  proFormaInvoiceMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_pro_forma_invoice_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de faturas pró-forma e o estado de
    entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para
    confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os logs
    detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_pro_forma_invoice_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PRO_FORMA_INVOICE_MAIL_RECIPIENTS_QUERY, variables)
        return unwrap(data, "proFormaInvoiceMailRecipients")
    except MolonionError as e:
        return _err(e)


PRO_FORMA_INVOICE_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  proFormaInvoiceMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_pro_forma_invoice_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de envios por email de uma fatura pró-forma: cada registo indica
    o email de destino, o conteúdo, o `deliveryId` (que liga aos destinatários via
    `get_pro_forma_invoice_mail_recipients`) e a data de envio (`createdAt`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (fatura pró-forma) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PRO_FORMA_INVOICE_MAILS_HISTORY_QUERY, variables)
        return unwrap(data, "proFormaInvoiceMailsHistory")
    except MolonionError as e:
        return _err(e)


PRO_FORMA_INVOICE_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  proFormaInvoiceNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_pro_forma_invoice_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para uma fatura pró-forma numa dada série de
    documentos. Devolve `number` (o próximo número) e `name` (o nome da série). Útil
    antes de criar uma nova pró-forma, para saber o número que lhe será atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(PRO_FORMA_INVOICE_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "proFormaInvoiceNextNumber")
    except MolonionError as e:
        return _err(e)


PRO_FORMA_INVOICE_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: ProFormaInvoiceOptions) {
  proFormaInvoiceRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_pro_forma_invoice_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as faturas pró-forma de uma entidade que podem ser relacionadas/ligadas a
    outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente) cujas pró-formas relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PRO_FORMA_INVOICE_RELATABLE_QUERY, variables)
        return unwrap(data, "proFormaInvoiceRelatable")
    except MolonionError as e:
        return _err(e)


PRO_FORMA_INVOICES_QUERY = """
query ($companyId: Int!, $options: ProFormaInvoiceOptions) {
  proFormaInvoices(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      expirationDate
      documentSetName
      entityName
      entityVat
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_pro_forma_invoices(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as faturas pró-forma de uma empresa, com os campos principais de
    cada uma: número, data, validade (`expirationDate`), série, entidade, valor total e
    estado. Para obter o detalhe completo de uma pró-forma usa `get_pro_forma_invoice`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PRO_FORMA_INVOICES_QUERY, variables)
        return unwrap(data, "proFormaInvoices")
    except MolonionError as e:
        return _err(e)


# ===========================================================================
# Grupos de propriedades (variantes)
# ===========================================================================

PROPERTY_GROUP_QUERY = """
query ($companyId: Int!, $propertyGroupId: String!) {
  propertyGroup(companyId: $companyId, propertyGroupId: $propertyGroupId) {
    errors { field msg }
    data {
      propertyGroupId
      name
      visible
      deletable
      properties {
        propertyId
        name
        visible
        ordering
        deletable
        values {
          propertyValueId
          code
          value
          visible
          ordering
          deletable
        }
      }
    }
  }
}
"""


@mcp.tool()
async def get_property_group(company_id: int, property_group_id: str) -> Any:
    """Obtém um grupo de propriedades (usado para variantes de produto) pelo seu ID.
    Devolve o grupo (`name`, `visible`, `deletable`) e a árvore completa das suas
    propriedades (`properties`, ex. "Cor", "Tamanho"), cada uma com os respetivos
    valores (`values`, ex. "Vermelho", "Azul" / "S", "M", "L"), incluindo `code`,
    `ordering` e `visible` de cada valor. É esta estrutura que define as combinações de
    variantes de um produto.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        property_group_id: ID do grupo de propriedades a obter.
    """
    variables = {"companyId": company_id, "propertyGroupId": property_group_id}
    try:
        data = await _client.query(PROPERTY_GROUP_QUERY, variables)
        return unwrap(data, "propertyGroup")
    except MolonionError as e:
        return _err(e)


PROPERTY_GROUP_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  propertyGroupLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_property_group_logs(
    company_id: int,
    related_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos grupos de propriedades de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`), os
    valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`,
    `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        related_id: opcional; filtra os logs de um grupo de propriedades específico (ID
            numérico interno, corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if related_id is not None:
        options["relatedId"] = related_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PROPERTY_GROUP_LOGS_QUERY, variables)
        return unwrap(data, "propertyGroupLogs")
    except MolonionError as e:
        return _err(e)


PROPERTY_GROUPS_QUERY = """
query ($companyId: Int!, $options: PropertyGroupOptions) {
  propertyGroups(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      propertyGroupId
      name
      visible
      deletable
      properties {
        propertyId
        name
        visible
        ordering
      }
    }
  }
}
"""


@mcp.tool()
async def list_property_groups(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) os grupos de propriedades (variantes) de uma empresa. Para cada
    grupo devolve `propertyGroupId`, `name`, `visible` e a lista das suas propriedades
    (`properties`: `propertyId`, `name`, `ordering`) — sem descer ao nível dos valores.
    Para a árvore completa (propriedades → valores) de um grupo usa `get_property_group`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PROPERTY_GROUPS_QUERY, variables)
        return unwrap(data, "propertyGroups")
    except MolonionError as e:
        return _err(e)


# ===========================================================================
# Encomendas de compra (PurchaseOrder)
# ===========================================================================

PURCHASE_ORDER_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  purchaseOrder(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscountValue
      commercialDiscountValue
      totalDiscountValue
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      currencyExchangeTotalValue
      currencyExchangeExchange
      documentCalculationsMode
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      expirationDate
      maturityDateDays
      maturityDateName
      yourReference
      ourReference
      salespersonCommission
      economicActivityClassificationCodeId
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      file
      fileOriginal
      importStatus
      deliveryMethodName
      deliveryVehicleName
      deliveryVehicleLicensePlate
      deliveryLoadDate
      deliveryLoadAddress
      deliveryLoadCity
      deliveryLoadZipCode
      deliveryUnloadAddress
      deliveryUnloadCity
      deliveryUnloadZipCode
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_purchase_order(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma encomenda de compra (documento de compra a fornecedor)
    pelo seu ID de documento: dados do documento (número, série, data, estado, totais),
    dados da entidade/fornecedor (`entityName`, `entityVat`, morada), descontos, câmbio
    (`currencyExchangeTotalValue`, `currencyExchangeExchange`), reconciliação, vencimento
    (`expirationDate`, `maturityDateDays`, `maturityDateName`), comissão do vendedor, o
    código CAE (`economicActivityClassificationCodeId`), o ficheiro arquivado
    (`file`/`fileOriginal`), o estado de importação (`importStatus`) e os dados de
    transporte. As linhas de produtos, os impostos, o fornecedor completo e os documentos
    relacionados não são incluídos neste selection set — podem ser adicionados se
    necessário.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (encomenda de compra) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(PURCHASE_ORDER_QUERY, variables)
        return unwrap(data, "purchaseOrder")
    except MolonionError as e:
        return _err(e)


PURCHASE_ORDER_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  purchaseOrderGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_purchase_order_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma encomenda de compra.
    Devolve `token`, `path` e `filename`, que se combinam para construir o URL de
    download do PDF. Nota: ao contrário de outras operações, não recebe `companyId` —
    apenas o `documentId`.

    Args:
        document_id: ID do documento (encomenda de compra) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            PURCHASE_ORDER_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "purchaseOrderGetPDFToken")
    except MolonionError as e:
        return _err(e)


PURCHASE_ORDER_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  purchaseOrderGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_purchase_order_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar várias encomendas de compra como
    um arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para construir
    o URL de download. O `full_path` identifica o ZIP a descarregar (caminho devolvido
    por uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(PURCHASE_ORDER_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "purchaseOrderGetZIPToken")
    except MolonionError as e:
        return _err(e)


PURCHASE_ORDER_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  purchaseOrderLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_purchase_order_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às encomendas de compra de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`), os
    valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`,
    `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma encomenda de compra específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PURCHASE_ORDER_LOGS_QUERY, variables)
        return unwrap(data, "purchaseOrderLogs")
    except MolonionError as e:
        return _err(e)


PURCHASE_ORDER_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  purchaseOrderMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_purchase_order_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de encomendas de compra e o estado de
    entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para
    confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os logs
    detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_purchase_order_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PURCHASE_ORDER_MAIL_RECIPIENTS_QUERY, variables)
        return unwrap(data, "purchaseOrderMailRecipients")
    except MolonionError as e:
        return _err(e)


PURCHASE_ORDER_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  purchaseOrderMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_purchase_order_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de envios por email de uma encomenda de compra: cada registo
    indica o email de destino, o conteúdo, o `deliveryId` (que liga aos destinatários via
    `get_purchase_order_mail_recipients`) e a data de envio (`createdAt`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (encomenda de compra) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PURCHASE_ORDER_MAILS_HISTORY_QUERY, variables)
        return unwrap(data, "purchaseOrderMailsHistory")
    except MolonionError as e:
        return _err(e)


PURCHASE_ORDER_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  purchaseOrderNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_purchase_order_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para uma encomenda de compra numa dada série de
    documentos. Devolve `number` (o próximo número) e `name` (o nome da série). Útil
    antes de criar uma nova encomenda de compra, para saber o número que lhe será
    atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(PURCHASE_ORDER_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "purchaseOrderNextNumber")
    except MolonionError as e:
        return _err(e)


PURCHASE_ORDER_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: PurchaseOrderOptions) {
  purchaseOrderRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_purchase_order_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as encomendas de compra de uma entidade (fornecedor) que podem ser
    relacionadas/ligadas a outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (fornecedor) cujas encomendas relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PURCHASE_ORDER_RELATABLE_QUERY, variables)
        return unwrap(data, "purchaseOrderRelatable")
    except MolonionError as e:
        return _err(e)


PURCHASE_ORDERS_QUERY = """
query ($companyId: Int!, $options: PurchaseOrderOptions) {
  purchaseOrders(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      expirationDate
      documentSetName
      entityName
      entityVat
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_purchase_orders(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as encomendas de compra de uma empresa, com os campos principais
    de cada uma: número, data, validade (`expirationDate`), série, entidade/fornecedor,
    valor total e estado. Para obter o detalhe completo de uma encomenda usa
    `get_purchase_order`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PURCHASE_ORDERS_QUERY, variables)
        return unwrap(data, "purchaseOrders")
    except MolonionError as e:
        return _err(e)


# ===========================================================================
# Acordos recorrentes de compra (PurchaseRecurringAgreement)
# ===========================================================================

PURCHASE_RECURRING_AGREEMENT_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  purchaseRecurringAgreement(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscount
      globalDiscountValue
      commercialDiscountValue
      totalDiscountValue
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      currencyExchangeTotalValue
      currencyExchangeExchange
      documentCalculationsMode
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      geographicZoneId
      terminalId
      expirationDate
      maturityDateDays
      yourReference
      ourReference
      salespersonCommission
      economicActivityClassificationCodeId
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      importStatus
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_purchase_recurring_agreement(
    company_id: int, document_id: int
) -> Any:
    """Obtém os detalhes de um acordo recorrente de compra (documento-modelo que gera
    compras a fornecedor de forma periódica) pelo seu ID de documento: dados do documento
    (número, série, data, estado, totais), dados da entidade/fornecedor (`entityName`,
    `entityVat`, morada), descontos, câmbio (`currencyExchangeTotalValue`,
    `currencyExchangeExchange`), reconciliação, vencimento, comissão do vendedor, a zona
    geográfica (`geographicZoneId`), o terminal (`terminalId`) e o código CAE
    (`economicActivityClassificationCodeId`). As linhas de produtos, os impostos, o
    fornecedor completo, os eventos de recorrência e os documentos relacionados não são
    incluídos neste selection set — podem ser adicionados se necessário.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (acordo recorrente de compra) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(PURCHASE_RECURRING_AGREEMENT_QUERY, variables)
        return unwrap(data, "purchaseRecurringAgreement")
    except MolonionError as e:
        return _err(e)


PURCHASE_RECURRING_AGREEMENT_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  purchaseRecurringAgreementGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_purchase_recurring_agreement_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de um acordo recorrente de
    compra. Devolve `token`, `path` e `filename`, que se combinam para construir o URL de
    download do PDF. Nota: ao contrário de outras operações, não recebe `companyId` —
    apenas o `documentId`.

    Args:
        document_id: ID do documento (acordo recorrente de compra) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            PURCHASE_RECURRING_AGREEMENT_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "purchaseRecurringAgreementGetPDFToken")
    except MolonionError as e:
        return _err(e)


PURCHASE_RECURRING_AGREEMENT_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  purchaseRecurringAgreementGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_purchase_recurring_agreement_zip_token(
    company_id: int, full_path: str
) -> Any:
    """Gera um token temporário e seguro para descarregar vários acordos recorrentes de
    compra como um arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam
    para construir o URL de download. O `full_path` identifica o ZIP a descarregar
    (caminho devolvido por uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(
            PURCHASE_RECURRING_AGREEMENT_ZIP_TOKEN_QUERY, variables
        )
        return unwrap(data, "purchaseRecurringAgreementGetZIPToken")
    except MolonionError as e:
        return _err(e)


PURCHASE_RECURRING_AGREEMENT_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  purchaseRecurringAgreementLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_purchase_recurring_agreement_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos acordos recorrentes de compra de uma
    empresa: criações, modificações e remoções. Cada entrada indica a operação
    (`operation`), os valores antigos/novos (`oldValues`/`newValues`), quem a fez
    (`userId`, `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de um acordo recorrente de compra específico
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PURCHASE_RECURRING_AGREEMENT_LOGS_QUERY, variables)
        return unwrap(data, "purchaseRecurringAgreementLogs")
    except MolonionError as e:
        return _err(e)


PURCHASE_RECURRING_AGREEMENT_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  purchaseRecurringAgreementMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_purchase_recurring_agreement_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de acordos recorrentes de compra e o
    estado de entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`).
    Útil para confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os
    logs detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_purchase_recurring_agreement_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            PURCHASE_RECURRING_AGREEMENT_MAIL_RECIPIENTS_QUERY, variables
        )
        return unwrap(data, "purchaseRecurringAgreementMailRecipients")
    except MolonionError as e:
        return _err(e)


PURCHASE_RECURRING_AGREEMENT_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  purchaseRecurringAgreementMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_purchase_recurring_agreement_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de envios por email de um acordo recorrente de compra: cada
    registo indica o email de destino, o conteúdo, o `deliveryId` (que liga aos
    destinatários via `get_purchase_recurring_agreement_mail_recipients`) e a data de
    envio (`createdAt`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (acordo recorrente de compra) cujos envios se
            pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            PURCHASE_RECURRING_AGREEMENT_MAILS_HISTORY_QUERY, variables
        )
        return unwrap(data, "purchaseRecurringAgreementMailsHistory")
    except MolonionError as e:
        return _err(e)


PURCHASE_RECURRING_AGREEMENT_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  purchaseRecurringAgreementNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_purchase_recurring_agreement_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para um acordo recorrente de compra numa dada
    série de documentos. Devolve `number` (o próximo número) e `name` (o nome da série).
    Útil antes de criar um novo acordo recorrente de compra, para saber o número que lhe
    será atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(
            PURCHASE_RECURRING_AGREEMENT_NEXT_NUMBER_QUERY, variables
        )
        return unwrap(data, "purchaseRecurringAgreementNextNumber")
    except MolonionError as e:
        return _err(e)


PURCHASE_RECURRING_AGREEMENT_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: PurchaseRecurringAgreementOptions) {
  purchaseRecurringAgreementRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_purchase_recurring_agreement_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os acordos recorrentes de compra de uma entidade (fornecedor) que podem ser
    relacionados/ligados a outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (fornecedor) cujos acordos relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            PURCHASE_RECURRING_AGREEMENT_RELATABLE_QUERY, variables
        )
        return unwrap(data, "purchaseRecurringAgreementRelatable")
    except MolonionError as e:
        return _err(e)


PURCHASE_RECURRING_AGREEMENTS_QUERY = """
query ($companyId: Int!, $options: PurchaseRecurringAgreementOptions) {
  purchaseRecurringAgreements(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      expirationDate
      documentSetName
      entityName
      entityVat
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_purchase_recurring_agreements(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) os acordos recorrentes de compra de uma empresa, com os campos
    principais de cada um: número, data, validade (`expirationDate`), série,
    entidade/fornecedor, valor total e estado. Para obter o detalhe completo de um acordo
    usa `get_purchase_recurring_agreement`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PURCHASE_RECURRING_AGREEMENTS_QUERY, variables)
        return unwrap(data, "purchaseRecurringAgreements")
    except MolonionError as e:
        return _err(e)


# ===========================================================================
# Análise de compras (PurchasesAnalysis)
# ===========================================================================

PURCHASES_ANALYSIS_BY_DATE_QUERY = """
query ($companyId: Int!, $options: PurchasesAnalysisOptions) {
  purchasesAnalysisByDate(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      purchasesAnalysisByDateId
      productId
      productParentId
      productCategoryId
      name
      reference
      date
      qty
      discountValue
      grossValue
      taxesValue
      retentionsValue
      totalValue
      stock
    }
  }
}
"""


@mcp.tool()
async def get_purchases_analysis_by_date(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Análise de compras agregada por data, ao nível do produto. Cada linha representa um
    produto num período e traz `name`/`reference`, a(s) `date`(s), a quantidade comprada
    (`qty`), os valores (`grossValue`, `discountValue`, `taxesValue`, `retentionsValue`,
    `totalValue`) e o `stock`. Útil para relatórios de compras por período.

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON: passa uma lista de dicionários, ex.
    `[{"field": "date", "comparison": "GREATER_OR_EQUAL", "value": "2026-01-01"},
      {"field": "date", "comparison": "LESS_OR_EQUAL", "value": "2026-03-31"}]`.
    Os nomes de `field`/`comparison` válidos são os dos enums `PurchasesAnalysisFilterField`
    e `Comparison` da API.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}` (ver acima).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PURCHASES_ANALYSIS_BY_DATE_QUERY, variables)
        return unwrap(data, "purchasesAnalysisByDate")
    except MolonionError as e:
        return _err(e)


PURCHASES_ANALYSIS_BY_DATE_DOCS_QUERY = """
query ($companyId: Int!, $options: PurchasesAnalysisOptions) {
  purchasesAnalysisByDateDocs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentProductId
      productId
      productParentId
      name
      reference
      price
      qty
      discountValue
      grossValue
      taxesValue
      retentionsValue
      totalValue
      stock
      document {
        documentId
        documentSetName
        number
        date
        year
        totalValue
        status
        nullified
        entityVat
        entityName
        entityNumber
        geographicZoneId
      }
    }
  }
}
"""


@mcp.tool()
async def get_purchases_analysis_by_date_docs(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Análise de compras por data ao nível da LINHA de documento (detalhe por documento),
    ao contrário de `get_purchases_analysis_by_date` que agrega por produto/período. Cada
    linha traz o produto (`name`/`reference`, `price`, `qty`, valores) e o documento de
    origem aninhado (`document`: número, data, série, entidade/fornecedor, total, estado).

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON — passa uma lista de dicionários, ex.
    `[{"field": "date", "comparison": "GREATER_OR_EQUAL", "value": "2026-01-01"}]`
    (ver `get_purchases_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PURCHASES_ANALYSIS_BY_DATE_DOCS_QUERY, variables)
        return unwrap(data, "purchasesAnalysisByDateDocs")
    except MolonionError as e:
        return _err(e)


PURCHASES_ANALYSIS_BY_PRODUCT_QUERY = """
query ($companyId: Int!, $options: PurchasesAnalysisOptions) {
  purchasesAnalysisByProduct(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      productId
      productParentId
      productCategoryId
      name
      reference
      date
      qty
      discountValue
      grossValue
      taxesValue
      retentionsValue
      totalValue
      stock
    }
  }
}
"""


@mcp.tool()
async def get_purchases_analysis_by_product(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Análise de compras agregada por produto. Cada linha representa um produto e traz
    `name`/`reference`, a(s) `date`(s) das compras, a quantidade total comprada (`qty`),
    os valores (`grossValue`, `discountValue`, `taxesValue`, `retentionsValue`,
    `totalValue`) e o `stock`. Útil para saber o que mais se comprou a fornecedores.

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON — passa uma lista de dicionários
    (ver `get_purchases_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PURCHASES_ANALYSIS_BY_PRODUCT_QUERY, variables)
        return unwrap(data, "purchasesAnalysisByProduct")
    except MolonionError as e:
        return _err(e)


PURCHASES_ANALYSIS_BY_PRODUCT_CATEGORY_QUERY = """
query ($companyId: Int!, $options: PurchasesAnalysisOptions) {
  purchasesAnalysisByProductCategory(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      productCategoryId
      name
      date
      qty
      discountValue
      grossValue
      taxesValue
      retentionsValue
      totalValue
    }
  }
}
"""


@mcp.tool()
async def get_purchases_analysis_by_product_category(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Análise de compras agregada por categoria de produto. Cada linha representa uma
    categoria (`productCategoryId`, `name`) e traz a(s) `date`(s), a quantidade comprada
    (`qty`) e os valores (`grossValue`, `discountValue`, `taxesValue`, `retentionsValue`,
    `totalValue`). Útil para ver a distribuição das compras por categoria.

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON — passa uma lista de dicionários
    (ver `get_purchases_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            PURCHASES_ANALYSIS_BY_PRODUCT_CATEGORY_QUERY, variables
        )
        return unwrap(data, "purchasesAnalysisByProductCategory")
    except MolonionError as e:
        return _err(e)


PURCHASES_ANALYSIS_BY_PRODUCT_CATEGORY_DOCS_QUERY = """
query ($companyId: Int!, $options: PurchasesAnalysisOptions) {
  purchasesAnalysisByProductCategoryDocs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentProductId
      productCategoryId
      productId
      productParentId
      name
      reference
      price
      qty
      discountValue
      grossValue
      taxesValue
      retentionsValue
      totalValue
      document {
        documentId
        documentSetName
        number
        date
        year
        totalValue
        status
        nullified
        entityVat
        entityName
        entityNumber
        geographicZoneId
      }
    }
  }
}
"""


@mcp.tool()
async def get_purchases_analysis_by_product_category_docs(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Análise de compras por categoria de produto ao nível da LINHA de documento (detalhe
    por documento), ao contrário de `get_purchases_analysis_by_product_category` que
    agrega por categoria. Cada linha traz a categoria (`productCategoryId`), o produto
    (`name`/`reference`, `price`, `qty`, valores) e o(s) documento(s) de origem
    aninhado(s) (`document`: número, data, série, entidade/fornecedor, total, estado).

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON — passa uma lista de dicionários
    (ver `get_purchases_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            PURCHASES_ANALYSIS_BY_PRODUCT_CATEGORY_DOCS_QUERY, variables
        )
        return unwrap(data, "purchasesAnalysisByProductCategoryDocs")
    except MolonionError as e:
        return _err(e)


PURCHASES_ANALYSIS_BY_PRODUCT_DOCS_QUERY = """
query ($companyId: Int!, $options: PurchasesAnalysisOptions) {
  purchasesAnalysisByProductDocs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentProductId
      productId
      productParentId
      name
      reference
      price
      qty
      discountValue
      grossValue
      taxesValue
      retentionsValue
      totalValue
      document {
        documentId
        documentSetName
        number
        date
        year
        totalValue
        status
        nullified
        entityVat
        entityName
        entityNumber
        geographicZoneId
      }
    }
  }
}
"""


@mcp.tool()
async def get_purchases_analysis_by_product_docs(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Análise de compras por produto ao nível da LINHA de documento (detalhe por
    documento), ao contrário de `get_purchases_analysis_by_product` que agrega por
    produto. Cada linha traz o produto (`name`/`reference`, `price`, `qty`, valores) e
    o(s) documento(s) de origem aninhado(s) (`document`: número, data, série,
    entidade/fornecedor, total, estado).

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON — passa uma lista de dicionários
    (ver `get_purchases_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            PURCHASES_ANALYSIS_BY_PRODUCT_DOCS_QUERY, variables
        )
        return unwrap(data, "purchasesAnalysisByProductDocs")
    except MolonionError as e:
        return _err(e)


PURCHASES_ANALYSIS_TOTALS_QUERY = """
query ($companyId: Int!, $options: PurchasesAnalysisTotalsOptions) {
  purchasesAnalysisTotals(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      grossValue
      discountValue
      taxesValue
      retentionsValue
      totalValue
      docsCount
      productsCount
      suppliersCount
    }
  }
}
"""


@mcp.tool()
async def get_purchases_analysis_totals(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
) -> Any:
    """Obtém os totais agregados da análise de compras de uma empresa (um único registo):
    valores totais (`grossValue`, `discountValue`, `taxesValue`, `retentionsValue`,
    `totalValue`) e contagens (`docsCount`, `productsCount`, `suppliersCount`). Útil para
    uma vista global das compras num período.

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON — passa uma lista de dicionários
    (ver `get_purchases_analysis_by_date`). Nota: esta operação não tem paginação.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PURCHASES_ANALYSIS_TOTALS_QUERY, variables)
        return unwrap(data, "purchasesAnalysisTotals")
    except MolonionError as e:
        return _err(e)


PURCHASES_PENDING_LIST_QUERY = """
query ($companyId: Int!, $options: PurchasesPendingListOptions) {
  purchasesPendingList(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      supplier {
        supplierId
        name
        vat
      }
      docsCount
      ammountTotal
      ammountPaid
      ammountPending
      delay
    }
  }
}
"""


@mcp.tool()
async def get_purchases_pending_list(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
) -> Any:
    """Lista as compras pendentes (por liquidar) agrupadas por fornecedor. Para cada
    fornecedor (`supplier`: `supplierId`, `name`, `vat`) traz o número de documentos
    pendentes (`docsCount`), o montante total (`ammountTotal`), o já pago (`ammountPaid`),
    o pendente (`ammountPending`) e o atraso médio em dias (`delay`). Útil para gerir
    contas a pagar a fornecedores.

    Atenção: ao contrário das outras operações, esta devolve uma LISTA de envelopes
    (um por fornecedor) — o resultado já vem achatado numa única lista de registos.

    Os filtros usam a estrutura genérica `field`/`comparison`/`value` da Moloni ON —
    passa uma lista de dicionários (ver `get_purchases_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        raw = await _client.query(PURCHASES_PENDING_LIST_QUERY, variables)
        envelopes = (raw or {}).get("purchasesPendingList") or []
        errs = [
            e for env in envelopes if env for e in (env.get("errors") or [])
        ]
        if errs:
            raise MolonionError(
                "A operação 'purchasesPendingList' devolveu erros.",
                errors=errs,
            )
        return [t for env in envelopes if env for t in (env.get("data") or [])]
    except MolonionError as e:
        return _err(e)


PURCHASES_PENDING_LIST_BY_DATE_QUERY = """
query ($companyId: Int!, $options: [PurchasesPendingListOptions]) {
  purchasesPendingListByDate(companyId: $companyId, options: $options) {
    errors { field msg }
    accumulator
    data {
      __typename
      documentId
      documentTypeId
      documentSetName
      number
      date
      status
      totalValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      entityVat
      entityName
      entityNumber
    }
  }
}
"""


@mcp.tool()
async def get_purchases_pending_list_by_date(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
) -> Any:
    """Lista os documentos de compra pendentes (por liquidar) agrupados por data de
    vencimento — para acompanhar pagamentos a fornecedores futuros e em atraso. Devolve
    uma lista de grupos; cada grupo traz `accumulator` (saldo acumulado do grupo) e
    `documents`, a lista de documentos pendentes desse vencimento.

    Cada documento usa a interface `DocumentRead` (campos comuns: número, série, data,
    estado, totais, reconciliação, entidade/fornecedor) e `__typename` identifica o tipo
    concreto. Para campos específicos de um tipo usa a tool dedicada.

    Atenção: ao contrário das outras operações, esta devolve uma LISTA de envelopes (um
    por grupo de vencimento), cada um com o seu `accumulator` — por isso o resultado é
    uma lista de grupos, não uma lista achatada de documentos.

    Os filtros usam a estrutura genérica `field`/`comparison`/`value` da Moloni ON —
    passa uma lista de dicionários (ver `get_purchases_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = [options]
    try:
        raw = await _client.query(PURCHASES_PENDING_LIST_BY_DATE_QUERY, variables)
        envelopes = (raw or {}).get("purchasesPendingListByDate") or []
        errs = [
            e for env in envelopes if env for e in (env.get("errors") or [])
        ]
        if errs:
            raise MolonionError(
                "A operação 'purchasesPendingListByDate' devolveu erros.",
                errors=errs,
            )
        return [
            {
                "accumulator": env.get("accumulator"),
                "documents": env.get("data") or [],
            }
            for env in envelopes
            if env
        ]
    except MolonionError as e:
        return _err(e)


PURCHASES_PENDING_LIST_SUPPLIER_QUERY = """
query ($companyId: Int!, $supplierId: Int, $options: PurchasesPendingListOptions) {
  purchasesPendingListSupplier(companyId: $companyId, supplierId: $supplierId, options: $options) {
    errors { field msg }
    accumulator
    data {
      __typename
      documentId
      documentTypeId
      documentSetName
      number
      date
      status
      totalValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      entityVat
      entityName
      entityNumber
    }
  }
}
"""


@mcp.tool()
async def get_purchases_pending_list_supplier(
    company_id: int,
    supplier_id: int | None = None,
    filters: list[dict[str, Any]] | None = None,
) -> Any:
    """Lista os documentos de compra pendentes (por liquidar) de um fornecedor — o extrato
    de contas a pagar a esse fornecedor. Devolve `accumulator` (saldo acumulado) e
    `documents`, a lista de documentos pendentes.

    Cada documento usa a interface `DocumentRead` (campos comuns: número, série, data,
    estado, totais, reconciliação, entidade/fornecedor) e `__typename` identifica o tipo
    concreto. Para campos específicos de um tipo usa a tool dedicada.

    Os filtros usam a estrutura genérica `field`/`comparison`/`value` da Moloni ON —
    passa uma lista de dicionários (ver `get_purchases_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        supplier_id: opcional; ID do fornecedor cujo extrato de pendentes se pretende.
        filters: opcional; lista de filtros `{field, comparison, value}`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    variables: dict[str, Any] = {"companyId": company_id}
    if supplier_id is not None:
        variables["supplierId"] = supplier_id
    if options:
        variables["options"] = options
    try:
        raw = await _client.query(PURCHASES_PENDING_LIST_SUPPLIER_QUERY, variables)
        documents = unwrap(raw, "purchasesPendingListSupplier")  # valida erros
        node = (raw or {}).get("purchasesPendingListSupplier") or {}
        return {"accumulator": node.get("accumulator"), "documents": documents}
    except MolonionError as e:
        return _err(e)


PURCHASES_PENDING_LIST_TOTALS_QUERY = """
query ($companyId: Int!, $options: PurchasesPendingListTotalsOptions) {
  purchasesPendingListTotals(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      docsCount
      ammountTotal
      ammountPaid
      ammountPending
      suppliersCount
      delay
    }
  }
}
"""


@mcp.tool()
async def get_purchases_pending_list_totals(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
) -> Any:
    """Obtém os totais agregados das compras pendentes (por liquidar) de uma empresa (um
    único registo): o número de documentos pendentes (`docsCount`), o montante total
    (`ammountTotal`), o já pago (`ammountPaid`), o pendente (`ammountPending`), o número
    de fornecedores (`suppliersCount`) e o atraso médio em dias (`delay`). Útil para uma
    vista global das contas a pagar.

    Os filtros usam a estrutura genérica `field`/`comparison`/`value` da Moloni ON —
    passa uma lista de dicionários (ver `get_purchases_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PURCHASES_PENDING_LIST_TOTALS_QUERY, variables)
        return unwrap(data, "purchasesPendingListTotals")
    except MolonionError as e:
        return _err(e)


# NOTA: tal como `customerHistoryUserSettingsTemplates`, esta devolve uma LISTA de
# envelopes (`[PurchasesPendingListUserSettingsTemplates]!`), não um único envelope —
# por isso o `unwrap()` não se aplica; tratamos a lista à mão.
PURCHASES_PENDING_LIST_TEMPLATES_QUERY = """
query ($companyId: Int!) {
  purchasesPendingListUserSettingsTemplates(companyId: $companyId) {
    errors { field msg }
    data {
      userSettingsTemplateId
      formName
      name
    }
  }
}
"""


@mcp.tool()
async def list_purchases_pending_list_templates(company_id: int) -> Any:
    """Lista os modelos (templates) de definições do utilizador para o ecrã das compras
    pendentes — filtros/colunas guardados pelo utilizador para reutilizar. Cada modelo
    tem `userSettingsTemplateId`, `formName` (o formulário a que se aplica) e `name`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
    """
    try:
        raw = await _client.query(
            PURCHASES_PENDING_LIST_TEMPLATES_QUERY, {"companyId": company_id}
        )
        envelopes = (
            raw or {}
        ).get("purchasesPendingListUserSettingsTemplates") or []
        errs = [
            e for env in envelopes if env for e in (env.get("errors") or [])
        ]
        if errs:
            raise MolonionError(
                "A operação 'purchasesPendingListUserSettingsTemplates' devolveu erros.",
                errors=errs,
            )
        return [t for env in envelopes if env for t in (env.get("data") or [])]
    except MolonionError as e:
        return _err(e)


PURCHASES_STATEMENTS_QUERY = """
query ($companyId: Int!, $options: PurchasesStatementOptions) {
  purchasesStatements(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      __typename
      documentId
      documentTypeId
      documentSetName
      number
      date
      status
      totalValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      entityVat
      entityName
      entityNumber
    }
  }
}
"""


@mcp.tool()
async def get_purchases_statements(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o extrato de compras a fornecedores: a lista de documentos de compra e o seu
    estado de liquidação/reconciliação num período. Cada documento usa a interface
    `DocumentRead` (campos comuns: número, série, data, estado, totais, reconciliação,
    entidade/fornecedor) e `__typename` identifica o tipo concreto. Para campos
    específicos de um tipo usa a tool dedicada.

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON — passa uma lista de dicionários
    (ver `get_purchases_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PURCHASES_STATEMENTS_QUERY, variables)
        return unwrap(data, "purchasesStatements")
    except MolonionError as e:
        return _err(e)


PURCHASES_STATEMENTS_TOTALS_QUERY = """
query ($companyId: Int!, $options: PurchasesStatementTotalsOptions) {
  purchasesStatementsTotals(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      grossValues
      totalDiscountValues
      taxesValues
      retentionsValues
      totalValues
      productsCount
      suppliersCount
      docsCount
    }
  }
}
"""


@mcp.tool()
async def get_purchases_statements_totals(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
) -> Any:
    """Obtém os totais agregados do extrato de compras a fornecedores (um único registo):
    os valores totais (`grossValues`, `totalDiscountValues`, `taxesValues`,
    `retentionsValues`, `totalValues`) e as contagens (`productsCount`, `suppliersCount`,
    `docsCount`). Útil para uma vista global do extrato de compras.

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON — passa uma lista de dicionários
    (ver `get_purchases_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(PURCHASES_STATEMENTS_TOTALS_QUERY, variables)
        return unwrap(data, "purchasesStatementsTotals")
    except MolonionError as e:
        return _err(e)


# ===========================================================================
# Recibos (Receipt)
# ===========================================================================

RECEIPT_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  receipt(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      financialDiscount
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      currencyExchangeTotalValue
      currencyExchangeExchange
      documentCalculationsMode
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      geographicZoneId
      terminalId
      yourReference
      ourReference
      economicActivityClassificationCodeId
      economicActivityClassificationCodeCode
      economicActivityClassificationCodeName
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_receipt(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de um recibo (documento de liquidação que salda faturas/notas)
    pelo seu ID de documento: dados do documento (número, série, data, estado), o total
    (`totalValue`), o desconto financeiro (`financialDiscount`), o câmbio
    (`currencyExchangeTotalValue`, `currencyExchangeExchange`), o estado de reconciliação
    (`reconciledValue`, `remainingReconciledValue`, `reconciliationPercentage`,
    `totalRelatedAppliedValue`), os dados da entidade/cliente e o código CAE. Os documentos
    saldados (`payments`/documentos relacionados), a entidade completa e os dados AT não
    são incluídos neste selection set — podem ser adicionados se necessário.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (recibo) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(RECEIPT_QUERY, variables)
        return unwrap(data, "receipt")
    except MolonionError as e:
        return _err(e)


RECEIPT_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  receiptGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_receipt_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de um recibo. Devolve
    `token`, `path` e `filename`, que se combinam para construir o URL de download do
    PDF. Nota: ao contrário de outras operações, não recebe `companyId` — apenas o
    `documentId`.

    Args:
        document_id: ID do documento (recibo) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            RECEIPT_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "receiptGetPDFToken")
    except MolonionError as e:
        return _err(e)


RECEIPT_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  receiptGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_receipt_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar vários recibos como um arquivo
    ZIP. Devolve `token`, `path` e `filename`, que se combinam para construir o URL de
    download. O `full_path` identifica o ZIP a descarregar (caminho devolvido por uma
    operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(RECEIPT_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "receiptGetZIPToken")
    except MolonionError as e:
        return _err(e)


RECEIPT_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  receiptLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_receipt_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos recibos de uma empresa: criações,
    modificações e remoções. Cada entrada indica a operação (`operation`), os valores
    antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`, `email`)
    e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de um recibo específico (corresponde a
            `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(RECEIPT_LOGS_QUERY, variables)
        return unwrap(data, "receiptLogs")
    except MolonionError as e:
        return _err(e)


RECEIPT_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  receiptMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_receipt_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de recibos e o estado de entrega de
    cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para confirmar a
    quem foi enviado o documento e se a entrega teve sucesso. Os logs detalhados de cada
    destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_receipt_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(RECEIPT_MAIL_RECIPIENTS_QUERY, variables)
        return unwrap(data, "receiptMailRecipients")
    except MolonionError as e:
        return _err(e)


RECEIPT_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  receiptMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_receipt_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de envios por email de um recibo: cada registo indica o email de
    destino, o conteúdo, o `deliveryId` (que liga aos destinatários via
    `get_receipt_mail_recipients`) e a data de envio (`createdAt`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (recibo) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(RECEIPT_MAILS_HISTORY_QUERY, variables)
        return unwrap(data, "receiptMailsHistory")
    except MolonionError as e:
        return _err(e)


RECEIPT_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  receiptNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_receipt_next_number(company_id: int, document_set_id: int) -> Any:
    """Obtém o próximo número disponível para um recibo numa dada série de documentos.
    Devolve `number` (o próximo número) e `name` (o nome da série). Útil antes de criar
    um novo recibo, para saber o número que lhe será atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(RECEIPT_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "receiptNextNumber")
    except MolonionError as e:
        return _err(e)


RECEIPT_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: ReceiptOptions) {
  receiptRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_receipt_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os recibos de uma entidade que podem ser relacionados/ligados a outro
    documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente) cujos recibos relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(RECEIPT_RELATABLE_QUERY, variables)
        return unwrap(data, "receiptRelatable")
    except MolonionError as e:
        return _err(e)


RECEIPTS_QUERY = """
query ($companyId: Int!, $options: ReceiptOptions) {
  receipts(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      reconciledValue
      reconciliationPercentage
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_receipts(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) os recibos de uma empresa, com os campos principais de cada um:
    número, data, série, entidade/cliente, valor total, valor reconciliado
    (`reconciledValue`, `reconciliationPercentage`) e estado. Para obter o detalhe
    completo de um recibo usa `get_receipt`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(RECEIPTS_QUERY, variables)
        return unwrap(data, "receipts")
    except MolonionError as e:
        return _err(e)


# ===========================================================================
# Acordos recorrentes de venda (RecurringAgreement)
# ===========================================================================

RECURRING_AGREEMENT_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  recurringAgreement(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscount
      globalDiscountValue
      commercialDiscountValue
      totalDiscountValue
      financialDiscount
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      currencyExchangeTotalValue
      currencyExchangeExchange
      documentCalculationsMode
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      geographicZoneId
      terminalId
      expirationDate
      maturityDateDays
      maturityDateName
      yourReference
      ourReference
      salespersonCommission
      economicActivityClassificationCodeId
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      importStatus
      deliveryLoadDate
      deliveryLoadAddress
      deliveryLoadCity
      deliveryLoadZipCode
      deliveryUnloadAddress
      deliveryUnloadCity
      deliveryUnloadZipCode
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_recurring_agreement(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de um acordo recorrente de venda (documento-modelo que gera vendas
    a cliente de forma periódica) pelo seu ID de documento: dados do documento (número,
    série, data, estado, totais), dados da entidade/cliente (`entityName`, `entityVat`,
    morada), descontos, câmbio (`currencyExchangeTotalValue`, `currencyExchangeExchange`),
    reconciliação, vencimento (`expirationDate`, `maturityDateDays`, `maturityDateName`),
    comissão do vendedor, a zona geográfica (`geographicZoneId`), o terminal (`terminalId`),
    o código CAE (`economicActivityClassificationCodeId`) e os dados de transporte
    (carga/descarga). As linhas de produtos, os impostos, o cliente completo, os eventos de
    recorrência e os documentos relacionados não são incluídos neste selection set — podem
    ser adicionados se necessário.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (acordo recorrente de venda) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(RECURRING_AGREEMENT_QUERY, variables)
        return unwrap(data, "recurringAgreement")
    except MolonionError as e:
        return _err(e)


RECURRING_AGREEMENT_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  recurringAgreementGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_recurring_agreement_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de um acordo recorrente de
    venda. Devolve `token`, `path` e `filename`, que se combinam para construir o URL de
    download do PDF. Nota: ao contrário de outras operações, não recebe `companyId` —
    apenas o `documentId`.

    Args:
        document_id: ID do documento (acordo recorrente de venda) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            RECURRING_AGREEMENT_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "recurringAgreementGetPDFToken")
    except MolonionError as e:
        return _err(e)


RECURRING_AGREEMENT_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  recurringAgreementGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_recurring_agreement_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar vários acordos recorrentes de
    venda como um arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para
    construir o URL de download. O `full_path` identifica o ZIP a descarregar (caminho
    devolvido por uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(RECURRING_AGREEMENT_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "recurringAgreementGetZIPToken")
    except MolonionError as e:
        return _err(e)


RECURRING_AGREEMENT_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  recurringAgreementLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_recurring_agreement_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos acordos recorrentes de venda de uma
    empresa: criações, modificações e remoções. Cada entrada indica a operação
    (`operation`), os valores antigos/novos (`oldValues`/`newValues`), quem a fez
    (`userId`, `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de um acordo recorrente de venda específico
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(RECURRING_AGREEMENT_LOGS_QUERY, variables)
        return unwrap(data, "recurringAgreementLogs")
    except MolonionError as e:
        return _err(e)


RECURRING_AGREEMENT_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  recurringAgreementMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_recurring_agreement_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de acordos recorrentes de venda e o
    estado de entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`).
    Útil para confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os
    logs detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_recurring_agreement_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            RECURRING_AGREEMENT_MAIL_RECIPIENTS_QUERY, variables
        )
        return unwrap(data, "recurringAgreementMailRecipients")
    except MolonionError as e:
        return _err(e)


RECURRING_AGREEMENT_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  recurringAgreementMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_recurring_agreement_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de envios por email de um acordo recorrente de venda: cada registo
    indica o email de destino, o conteúdo, o `deliveryId` (que liga aos destinatários via
    `get_recurring_agreement_mail_recipients`) e a data de envio (`createdAt`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (acordo recorrente de venda) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            RECURRING_AGREEMENT_MAILS_HISTORY_QUERY, variables
        )
        return unwrap(data, "recurringAgreementMailsHistory")
    except MolonionError as e:
        return _err(e)


RECURRING_AGREEMENT_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  recurringAgreementNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_recurring_agreement_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para um acordo recorrente de venda numa dada série
    de documentos. Devolve `number` (o próximo número) e `name` (o nome da série). Útil
    antes de criar um novo acordo recorrente de venda, para saber o número que lhe será
    atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(RECURRING_AGREEMENT_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "recurringAgreementNextNumber")
    except MolonionError as e:
        return _err(e)


RECURRING_AGREEMENT_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: RecurringAgreementOptions) {
  recurringAgreementRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_recurring_agreement_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os acordos recorrentes de venda de uma entidade (cliente) que podem ser
    relacionados/ligados a outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente) cujos acordos relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(RECURRING_AGREEMENT_RELATABLE_QUERY, variables)
        return unwrap(data, "recurringAgreementRelatable")
    except MolonionError as e:
        return _err(e)


RECURRING_AGREEMENTS_QUERY = """
query ($companyId: Int!, $options: RecurringAgreementOptions) {
  recurringAgreements(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      expirationDate
      documentSetName
      entityName
      entityVat
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_recurring_agreements(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) os acordos recorrentes de venda de uma empresa, com os campos
    principais de cada um: número, data, validade (`expirationDate`), série,
    entidade/cliente, valor total e estado. Para obter o detalhe completo de um acordo usa
    `get_recurring_agreement`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(RECURRING_AGREEMENTS_QUERY, variables)
        return unwrap(data, "recurringAgreements")
    except MolonionError as e:
        return _err(e)


# ===========================================================================
# Retenções na fonte (Retention)
# ===========================================================================

RETENTION_QUERY = """
query ($companyId: Int!, $retentionId: Int!) {
  retention(companyId: $companyId, retentionId: $retentionId) {
    errors { field msg }
    data {
      retentionId
      name
      value
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_retention(company_id: int, retention_id: int) -> Any:
    """Obtém os detalhes de uma retenção na fonte pelo seu ID: o nome (`name`), a taxa
    (`value`, em percentagem), se está visível (`visible`) e se é removível (`deletable`).
    As retenções aplicam-se às linhas dos documentos para reter parte do valor (ex. IRS).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        retention_id: ID da retenção a obter.
    """
    variables = {"companyId": company_id, "retentionId": retention_id}
    try:
        data = await _client.query(RETENTION_QUERY, variables)
        return unwrap(data, "retention")
    except MolonionError as e:
        return _err(e)


RETENTION_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  retentionLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_retention_logs(
    company_id: int,
    retention_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às retenções de uma empresa: criações,
    modificações e remoções. Cada entrada indica a operação (`operation`), os valores
    antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`, `email`)
    e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        retention_id: opcional; filtra os logs de uma retenção específica (corresponde a
            `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if retention_id is not None:
        options["relatedId"] = retention_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(RETENTION_LOGS_QUERY, variables)
        return unwrap(data, "retentionLogs")
    except MolonionError as e:
        return _err(e)


RETENTIONS_QUERY = """
query ($companyId: Int!, $options: RetentionOptions) {
  retentions(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      retentionId
      name
      value
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_retentions(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as retenções na fonte de uma empresa, cada uma com `retentionId`,
    `name`, a taxa (`value`, em percentagem) e `visible`. Útil para escolher a retenção a
    aplicar a uma linha de documento.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(RETENTIONS_QUERY, variables)
        return unwrap(data, "retentions")
    except MolonionError as e:
        return _err(e)


# ===========================================================================
# Análise de vendas (SalesAnalysis)
# ===========================================================================

SALES_ANALYSIS_BY_DATE_QUERY = """
query ($companyId: Int!, $options: SalesAnalysisOptions) {
  salesAnalysisByDate(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      salesAnalysisByDateId
      productId
      productParentId
      productCategoryId
      name
      reference
      date
      qty
      discountValue
      grossValue
      taxesValue
      retentionsValue
      totalValue
      stock
    }
  }
}
"""


@mcp.tool()
async def get_sales_analysis_by_date(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Análise de vendas agregada por data, ao nível do produto. Cada linha representa um
    produto num período e traz `name`/`reference`, a(s) `date`(s), a quantidade vendida
    (`qty`), os valores (`grossValue`, `discountValue`, `taxesValue`, `retentionsValue`,
    `totalValue`) e o `stock`. Útil para relatórios de vendas por período.

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON: passa uma lista de dicionários, ex.
    `[{"field": "date", "comparison": "GREATER_OR_EQUAL", "value": "2026-01-01"},
      {"field": "date", "comparison": "LESS_OR_EQUAL", "value": "2026-03-31"}]`.
    Os nomes de `field`/`comparison` válidos são os dos enums `SalesAnalysisFilterField`
    e `Comparison` da API.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}` (ver acima).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SALES_ANALYSIS_BY_DATE_QUERY, variables)
        return unwrap(data, "salesAnalysisByDate")
    except MolonionError as e:
        return _err(e)


SALES_ANALYSIS_BY_DATE_DOCS_QUERY = """
query ($companyId: Int!, $options: SalesAnalysisOptions) {
  salesAnalysisByDateDocs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentProductId
      documentId
      productId
      productParentId
      name
      reference
      price
      qty
      discountValue
      grossValue
      taxesValue
      retentionsValue
      totalValue
      stock
      document {
        documentId
        documentSetName
        number
        date
        year
        totalValue
        status
        nullified
        entityVat
        entityName
        entityNumber
        geographicZoneId
      }
    }
  }
}
"""


@mcp.tool()
async def get_sales_analysis_by_date_docs(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Análise de vendas por data ao nível da LINHA de documento (detalhe por documento),
    ao contrário de `get_sales_analysis_by_date` que agrega por produto/período. Cada
    linha traz o produto (`name`/`reference`, `price`, `qty`, valores) e o(s) documento(s)
    de origem aninhado(s) (`document`: número, data, série, entidade/cliente, total,
    estado).

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON — passa uma lista de dicionários
    (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SALES_ANALYSIS_BY_DATE_DOCS_QUERY, variables)
        return unwrap(data, "salesAnalysisByDateDocs")
    except MolonionError as e:
        return _err(e)


SALES_ANALYSIS_BY_PRODUCT_QUERY = """
query ($companyId: Int!, $options: SalesAnalysisOptions) {
  salesAnalysisByProduct(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      productId
      productParentId
      productCategoryId
      name
      reference
      date
      qty
      discountValue
      grossValue
      taxesValue
      retentionsValue
      totalValue
      stock
    }
  }
}
"""


@mcp.tool()
async def get_sales_analysis_by_product(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Análise de vendas agregada por produto. Cada linha representa um produto e traz
    `name`/`reference`, a(s) `date`(s) das vendas, a quantidade total vendida (`qty`),
    os valores (`grossValue`, `discountValue`, `taxesValue`, `retentionsValue`,
    `totalValue`) e o `stock`. Útil para saber o que mais se vendeu.

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON — passa uma lista de dicionários
    (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SALES_ANALYSIS_BY_PRODUCT_QUERY, variables)
        return unwrap(data, "salesAnalysisByProduct")
    except MolonionError as e:
        return _err(e)


SALES_ANALYSIS_BY_PRODUCT_CATEGORY_QUERY = """
query ($companyId: Int!, $options: SalesAnalysisOptions) {
  salesAnalysisByProductCategory(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      productCategoryId
      name
      date
      qty
      discountValue
      grossValue
      taxesValue
      retentionsValue
      totalValue
    }
  }
}
"""


@mcp.tool()
async def get_sales_analysis_by_product_category(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Análise de vendas agregada por categoria de produto. Cada linha representa uma
    categoria (`productCategoryId`, `name`) e traz a(s) `date`(s), a quantidade vendida
    (`qty`) e os valores (`grossValue`, `discountValue`, `taxesValue`, `retentionsValue`,
    `totalValue`). Útil para ver a distribuição das vendas por categoria.

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON — passa uma lista de dicionários
    (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SALES_ANALYSIS_BY_PRODUCT_CATEGORY_QUERY, variables
        )
        return unwrap(data, "salesAnalysisByProductCategory")
    except MolonionError as e:
        return _err(e)


SALES_ANALYSIS_BY_PRODUCT_CATEGORY_DOCS_QUERY = """
query ($companyId: Int!, $options: SalesAnalysisOptions) {
  salesAnalysisByProductCategoryDocs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentProductId
      documentId
      productCategoryId
      productId
      productParentId
      name
      reference
      price
      qty
      discountValue
      grossValue
      taxesValue
      retentionsValue
      totalValue
      document {
        documentId
        documentSetName
        number
        date
        year
        totalValue
        status
        nullified
        entityVat
        entityName
        entityNumber
        geographicZoneId
      }
    }
  }
}
"""


@mcp.tool()
async def get_sales_analysis_by_product_category_docs(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Análise de vendas por categoria de produto ao nível da LINHA de documento (detalhe
    por documento), ao contrário de `get_sales_analysis_by_product_category` que agrega
    por categoria. Cada linha traz a categoria (`productCategoryId`), o produto
    (`name`/`reference`, `price`, `qty`, valores) e o(s) documento(s) de origem
    aninhado(s) (`document`: número, data, série, entidade/cliente, total, estado).

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON — passa uma lista de dicionários
    (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SALES_ANALYSIS_BY_PRODUCT_CATEGORY_DOCS_QUERY, variables
        )
        return unwrap(data, "salesAnalysisByProductCategoryDocs")
    except MolonionError as e:
        return _err(e)


SALES_ANALYSIS_BY_PRODUCT_DOCS_QUERY = """
query ($companyId: Int!, $options: SalesAnalysisOptions) {
  salesAnalysisByProductDocs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentProductId
      documentId
      productId
      productParentId
      name
      reference
      price
      qty
      discountValue
      grossValue
      taxesValue
      retentionsValue
      totalValue
      document {
        documentId
        documentSetName
        number
        date
        year
        totalValue
        status
        nullified
        entityVat
        entityName
        entityNumber
        geographicZoneId
      }
    }
  }
}
"""


@mcp.tool()
async def get_sales_analysis_by_product_docs(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Análise de vendas por produto ao nível da LINHA de documento (detalhe por
    documento), ao contrário de `get_sales_analysis_by_product` que agrega por produto.
    Cada linha traz o produto (`name`/`reference`, `price`, `qty`, valores) e o(s)
    documento(s) de origem aninhado(s) (`document`: número, data, série, entidade/cliente,
    total, estado).

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON — passa uma lista de dicionários
    (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SALES_ANALYSIS_BY_PRODUCT_DOCS_QUERY, variables)
        return unwrap(data, "salesAnalysisByProductDocs")
    except MolonionError as e:
        return _err(e)


SALES_ANALYSIS_TOTALS_QUERY = """
query ($companyId: Int!, $options: SalesAnalysisTotalsOptions) {
  salesAnalysisTotals(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      grossValue
      discountValue
      taxesValue
      retentionsValue
      totalValue
      docsCount
      productsCount
      customersCount
    }
  }
}
"""


@mcp.tool()
async def get_sales_analysis_totals(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
) -> Any:
    """Obtém os totais agregados da análise de vendas de uma empresa (um único registo):
    valores totais (`grossValue`, `discountValue`, `taxesValue`, `retentionsValue`,
    `totalValue`) e contagens (`docsCount`, `productsCount`, `customersCount`). Útil para
    uma vista global das vendas num período.

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON — passa uma lista de dicionários
    (ver `get_sales_analysis_by_date`). Nota: esta operação não tem paginação.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SALES_ANALYSIS_TOTALS_QUERY, variables)
        return unwrap(data, "salesAnalysisTotals")
    except MolonionError as e:
        return _err(e)


SALES_PENDING_LIST_QUERY = """
query ($companyId: Int!, $options: SalesPendingListOptions) {
  salesPendingList(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      customer {
        customerId
        name
        vat
      }
      docsCount
      ammountTotal
      ammountPaid
      ammountPending
      delay
    }
  }
}
"""


@mcp.tool()
async def get_sales_pending_list(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
) -> Any:
    """Lista as vendas pendentes (por receber) agrupadas por cliente. Para cada cliente
    (`customer`: `customerId`, `name`, `vat`) traz o número de documentos pendentes
    (`docsCount`), o montante total (`ammountTotal`), o já recebido (`ammountPaid`), o
    pendente (`ammountPending`) e o atraso médio em dias (`delay`). Útil para gerir
    contas a receber de clientes.

    Atenção: ao contrário das outras operações, esta devolve uma LISTA de envelopes
    (um por cliente) — o resultado já vem achatado numa única lista de registos.

    Os filtros usam a estrutura genérica `field`/`comparison`/`value` da Moloni ON —
    passa uma lista de dicionários (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        raw = await _client.query(SALES_PENDING_LIST_QUERY, variables)
        envelopes = (raw or {}).get("salesPendingList") or []
        errs = [
            e for env in envelopes if env for e in (env.get("errors") or [])
        ]
        if errs:
            raise MolonionError(
                "A operação 'salesPendingList' devolveu erros.",
                errors=errs,
            )
        return [t for env in envelopes if env for t in (env.get("data") or [])]
    except MolonionError as e:
        return _err(e)


SALES_PENDING_LIST_BY_DATE_QUERY = """
query ($companyId: Int!, $options: [SalesPendingListOptions]) {
  salesPendingListByDate(companyId: $companyId, options: $options) {
    errors { field msg }
    accumulator
    data {
      __typename
      documentId
      documentTypeId
      documentSetName
      number
      date
      status
      totalValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      entityVat
      entityName
      entityNumber
    }
  }
}
"""


@mcp.tool()
async def get_sales_pending_list_by_date(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
) -> Any:
    """Lista os documentos de venda pendentes (por receber) agrupados por data de
    vencimento — para acompanhar recebimentos de clientes futuros e em atraso. Devolve
    uma lista de grupos; cada grupo traz `accumulator` (saldo acumulado do grupo) e
    `documents`, a lista de documentos pendentes desse vencimento.

    Cada documento usa a interface `DocumentRead` (campos comuns: número, série, data,
    estado, totais, reconciliação, entidade/cliente) e `__typename` identifica o tipo
    concreto. Para campos específicos de um tipo usa a tool dedicada.

    Atenção: ao contrário das outras operações, esta devolve uma LISTA de envelopes (um
    por grupo de vencimento), cada um com o seu `accumulator` — por isso o resultado é
    uma lista de grupos, não uma lista achatada de documentos.

    Os filtros usam a estrutura genérica `field`/`comparison`/`value` da Moloni ON —
    passa uma lista de dicionários (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = [options]
    try:
        raw = await _client.query(SALES_PENDING_LIST_BY_DATE_QUERY, variables)
        envelopes = (raw or {}).get("salesPendingListByDate") or []
        errs = [
            e for env in envelopes if env for e in (env.get("errors") or [])
        ]
        if errs:
            raise MolonionError(
                "A operação 'salesPendingListByDate' devolveu erros.",
                errors=errs,
            )
        return [
            {
                "accumulator": env.get("accumulator"),
                "documents": env.get("data") or [],
            }
            for env in envelopes
            if env
        ]
    except MolonionError as e:
        return _err(e)


SALES_PENDING_LIST_CLIENT_QUERY = """
query ($companyId: Int!, $customerId: Int, $options: SalesPendingListOptions) {
  salesPendingListClient(companyId: $companyId, customerId: $customerId, options: $options) {
    errors { field msg }
    accumulator
    data {
      __typename
      documentId
      documentTypeId
      documentSetName
      number
      date
      status
      totalValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      entityVat
      entityName
      entityNumber
    }
  }
}
"""


@mcp.tool()
async def get_sales_pending_list_client(
    company_id: int,
    customer_id: int | None = None,
    filters: list[dict[str, Any]] | None = None,
) -> Any:
    """Lista os documentos de venda pendentes (por receber) de um cliente — o extrato de
    contas a receber desse cliente. Devolve `accumulator` (saldo acumulado) e
    `documents`, a lista de documentos pendentes.

    Cada documento usa a interface `DocumentRead` (campos comuns: número, série, data,
    estado, totais, reconciliação, entidade/cliente) e `__typename` identifica o tipo
    concreto. Para campos específicos de um tipo usa a tool dedicada.

    Os filtros usam a estrutura genérica `field`/`comparison`/`value` da Moloni ON —
    passa uma lista de dicionários (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        customer_id: opcional; ID do cliente cujo extrato de pendentes se pretende.
        filters: opcional; lista de filtros `{field, comparison, value}`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    variables: dict[str, Any] = {"companyId": company_id}
    if customer_id is not None:
        variables["customerId"] = customer_id
    if options:
        variables["options"] = options
    try:
        raw = await _client.query(SALES_PENDING_LIST_CLIENT_QUERY, variables)
        documents = unwrap(raw, "salesPendingListClient")  # valida erros
        node = (raw or {}).get("salesPendingListClient") or {}
        return {"accumulator": node.get("accumulator"), "documents": documents}
    except MolonionError as e:
        return _err(e)


SALES_PENDING_LIST_TOTALS_QUERY = """
query ($companyId: Int!, $options: SalesPendingListTotalsOptions) {
  salesPendingListTotals(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      docsCount
      ammountTotal
      ammountPaid
      ammountPending
      ammountPendingPercent
      delayAverage
    }
  }
}
"""


@mcp.tool()
async def get_sales_pending_list_totals(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
) -> Any:
    """Obtém os totais agregados das vendas pendentes (por receber) de uma empresa (um
    único registo): o número de documentos pendentes (`docsCount`), o montante total
    (`ammountTotal`), o já recebido (`ammountPaid`), o pendente (`ammountPending`), a
    percentagem pendente (`ammountPendingPercent`) e o atraso médio em dias
    (`delayAverage`). Útil para uma vista global das contas a receber.

    Os filtros usam a estrutura genérica `field`/`comparison`/`value` da Moloni ON —
    passa uma lista de dicionários (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SALES_PENDING_LIST_TOTALS_QUERY, variables)
        return unwrap(data, "salesPendingListTotals")
    except MolonionError as e:
        return _err(e)


# ===========================================================================
# Vendedores (Salesperson)
# ===========================================================================

SALESPERSON_QUERY = """
query ($companyId: Int!, $salespersonId: Int!) {
  salesperson(companyId: $companyId, salespersonId: $salespersonId) {
    errors { field msg }
    data {
      salespersonId
      number
      name
      vat
      email
      phone
      address
      city
      zipCode
      website
      contactName
      contactEmail
      contactPhone
      baseCommission
      documentCopies
      notes
      countryId
      geographicZoneId
      languageId
      companyId
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_salesperson(company_id: int, salesperson_id: int) -> Any:
    """Obtém os detalhes de um vendedor pelo seu ID: o número (`number`), o nome, o NIF
    (`vat`), os contactos (`email`, `phone`, morada), a taxa-base de comissão
    (`baseCommission`), o número de cópias de documentos (`documentCopies`), as notas e
    as chaves estrangeiras (`countryId`, `geographicZoneId`, `languageId`). Os clientes
    atribuídos e os objetos aninhados (país, zona, idioma) não são incluídos neste
    selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        salesperson_id: ID do vendedor a obter.
    """
    variables = {"companyId": company_id, "salespersonId": salesperson_id}
    try:
        data = await _client.query(SALESPERSON_QUERY, variables)
        return unwrap(data, "salesperson")
    except MolonionError as e:
        return _err(e)


SALESPERSON_COMMISSIONS_QUERY = """
query ($companyId: Int!, $options: SalespersonCommissionsOptions) {
  salespersonCommissions(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      salespersonCommissionDocumentId
      salespersonId
      commission
      reconciled
      remaining
      fullyReconciled
      document {
        __typename
        documentId
        documentTypeId
        documentSetName
        number
        date
        status
        totalValue
        entityVat
        entityName
        entityNumber
      }
    }
  }
}
"""


@mcp.tool()
async def get_salesperson_commissions(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as comissões de vendedores por documento: cada linha indica o vendedor
    (`salespersonId`), o valor da comissão (`commission`), o valor já reconciliado
    (`reconciled`), o que falta (`remaining`), se está totalmente reconciliado
    (`fullyReconciled`) e o documento de origem aninhado (`document`, interface
    `DocumentRead` com número, data, série, entidade, total; `__typename` dá o tipo).
    Útil para apurar comissões a pagar/pagas por vendedor.

    Os filtros usam a estrutura genérica `field`/`comparison`/`value` da Moloni ON —
    passa uma lista de dicionários (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}` (ex. por
            vendedor ou intervalo de datas).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SALESPERSON_COMMISSIONS_QUERY, variables)
        return unwrap(data, "salespersonCommissions")
    except MolonionError as e:
        return _err(e)


SALESPERSON_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  salespersonLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_salesperson_logs(
    company_id: int,
    salesperson_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos vendedores de uma empresa: criações,
    modificações e remoções. Cada entrada indica a operação (`operation`), os valores
    antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`, `email`)
    e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        salesperson_id: opcional; filtra os logs de um vendedor específico (corresponde a
            `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if salesperson_id is not None:
        options["relatedId"] = salesperson_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SALESPERSON_LOGS_QUERY, variables)
        return unwrap(data, "salespersonLogs")
    except MolonionError as e:
        return _err(e)


SALESPERSON_PAYMENT_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  salespersonPayment(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      financialDiscount
      salespersonCommission
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      currencyExchangeTotalValue
      currencyExchangeExchange
      documentCalculationsMode
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      geographicZoneId
      terminalId
      yourReference
      ourReference
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_salesperson_payment(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de um pagamento a vendedor (documento de liquidação que salda as
    comissões de um vendedor) pelo seu ID de documento: dados do documento (número, série,
    data, estado), o total (`totalValue`), o desconto financeiro (`financialDiscount`), a
    comissão (`salespersonCommission`), o câmbio, o estado de reconciliação e os dados da
    entidade/vendedor. As comissões saldadas, os pagamentos e a entidade completa não são
    incluídos neste selection set — podem ser adicionados se necessário.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (pagamento a vendedor) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(SALESPERSON_PAYMENT_QUERY, variables)
        return unwrap(data, "salespersonPayment")
    except MolonionError as e:
        return _err(e)


SALESPERSON_PAYMENT_COMMISSIONS_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: SalespersonPaymentCommissionsOptions) {
  salespersonPaymentCommissions(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      salespersonPaymentDocumentId
      salespersonCommissionDocumentId
      reconciled
      salespersonCommissionDocument {
        salespersonCommissionDocumentId
        salespersonId
        commission
        reconciled
        remaining
        fullyReconciled
        document {
          __typename
          documentId
          documentSetName
          number
          date
          status
          totalValue
          entityName
        }
      }
    }
  }
}
"""


@mcp.tool()
async def get_salesperson_payment_commissions(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as comissões saldadas por um pagamento a vendedor: a ligação de reconciliação
    entre o documento de pagamento e cada documento de comissão. Cada linha indica o
    `reconciled` (valor reconciliado nessa ligação) e o documento de comissão aninhado
    (`salespersonCommissionDocument`: vendedor, comissão, reconciliação e o documento de
    venda de origem). Útil para ver que comissões foram pagas por um pagamento.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (pagamento a vendedor) cujas comissões se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SALESPERSON_PAYMENT_COMMISSIONS_QUERY, variables)
        return unwrap(data, "salespersonPaymentCommissions")
    except MolonionError as e:
        return _err(e)


SALESPERSON_PAYMENT_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  salespersonPaymentGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_salesperson_payment_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de um pagamento a vendedor.
    Devolve `token`, `path` e `filename`, que se combinam para construir o URL de download
    do PDF. Nota: ao contrário de outras operações, não recebe `companyId` — apenas o
    `documentId`.

    Args:
        document_id: ID do documento (pagamento a vendedor) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            SALESPERSON_PAYMENT_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "salespersonPaymentGetPDFToken")
    except MolonionError as e:
        return _err(e)


SALESPERSON_PAYMENT_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  salespersonPaymentGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_salesperson_payment_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar vários pagamentos a vendedor como
    um arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para construir o
    URL de download. O `full_path` identifica o ZIP a descarregar (caminho devolvido por
    uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(SALESPERSON_PAYMENT_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "salespersonPaymentGetZIPToken")
    except MolonionError as e:
        return _err(e)


SALESPERSON_PAYMENT_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  salespersonPaymentLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_salesperson_payment_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos pagamentos a vendedor de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`), os
    valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`,
    `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de um pagamento a vendedor específico
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SALESPERSON_PAYMENT_LOGS_QUERY, variables)
        return unwrap(data, "salespersonPaymentLogs")
    except MolonionError as e:
        return _err(e)


SALESPERSON_PAYMENT_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  salespersonPaymentMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_salesperson_payment_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de pagamentos a vendedor e o estado de
    entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para
    confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os logs
    detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_salesperson_payment_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SALESPERSON_PAYMENT_MAIL_RECIPIENTS_QUERY, variables
        )
        return unwrap(data, "salespersonPaymentMailRecipients")
    except MolonionError as e:
        return _err(e)


SALESPERSON_PAYMENT_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  salespersonPaymentMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_salesperson_payment_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de envios por email de um pagamento a vendedor: cada registo indica
    o email de destino, o conteúdo, o `deliveryId` (que liga aos destinatários via
    `get_salesperson_payment_mail_recipients`) e a data de envio (`createdAt`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (pagamento a vendedor) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SALESPERSON_PAYMENT_MAILS_HISTORY_QUERY, variables
        )
        return unwrap(data, "salespersonPaymentMailsHistory")
    except MolonionError as e:
        return _err(e)


SALESPERSON_PAYMENT_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  salespersonPaymentNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_salesperson_payment_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para um pagamento a vendedor numa dada série de
    documentos. Devolve `number` (o próximo número) e `name` (o nome da série). Útil antes
    de criar um novo pagamento a vendedor, para saber o número que lhe será atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(
            SALESPERSON_PAYMENT_NEXT_NUMBER_QUERY, variables
        )
        return unwrap(data, "salespersonPaymentNextNumber")
    except MolonionError as e:
        return _err(e)


SALESPERSON_PAYMENT_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: SalespersonPaymentOptions) {
  salespersonPaymentRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_salesperson_payment_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os pagamentos a vendedor de uma entidade (vendedor) que podem ser
    relacionados/ligados a outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (vendedor) cujos pagamentos relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SALESPERSON_PAYMENT_RELATABLE_QUERY, variables)
        return unwrap(data, "salespersonPaymentRelatable")
    except MolonionError as e:
        return _err(e)


SALESPERSON_PAYMENTS_QUERY = """
query ($companyId: Int!, $options: SalespersonPaymentOptions) {
  salespersonPayments(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      reconciledValue
      reconciliationPercentage
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_salesperson_payments(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) os pagamentos a vendedor de uma empresa, com os campos principais
    de cada um: número, data, série, entidade/vendedor, valor total, valor reconciliado
    (`reconciledValue`, `reconciliationPercentage`) e estado. Para obter o detalhe
    completo de um pagamento usa `get_salesperson_payment`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SALESPERSON_PAYMENTS_QUERY, variables)
        return unwrap(data, "salespersonPayments")
    except MolonionError as e:
        return _err(e)


SALESPERSONS_QUERY = """
query ($companyId: Int!, $options: SalespersonOptions) {
  salespersons(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      salespersonId
      number
      name
      vat
      email
      phone
      baseCommission
      visible
    }
  }
}
"""


@mcp.tool()
async def list_salespersons(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) os vendedores de uma empresa, cada um com `salespersonId`,
    `number`, `name`, `vat`, contactos (`email`, `phone`), a taxa-base de comissão
    (`baseCommission`) e `visible`. Para o detalhe completo de um vendedor usa
    `get_salesperson`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SALESPERSONS_QUERY, variables)
        return unwrap(data, "salespersons")
    except MolonionError as e:
        return _err(e)


SALESPERSONS_PAYMENTS_HISTORY_BY_SALESPERSON_QUERY = """
query ($companyId: Int!, $options: SalespersonsPaymentsHistoryOptions) {
  salespersonsPaymentsHistoryBySalesperson(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      salespersonId
      docsCount
      totalDocsValue
      salesperson {
        salespersonId
        number
        name
        vat
        baseCommission
      }
    }
  }
}
"""


@mcp.tool()
async def get_salespersons_payments_history_by_salesperson(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Histórico de pagamentos a vendedores agregado por vendedor: cada linha traz o
    vendedor (`salesperson`: número, nome, NIF, comissão-base), o número de documentos
    (`docsCount`) e o valor total dos documentos (`totalDocsValue`). Útil para uma vista
    por vendedor do que já lhes foi pago/processado.

    Os filtros usam a estrutura genérica `field`/`comparison`/`value` da Moloni ON —
    passa uma lista de dicionários (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SALESPERSONS_PAYMENTS_HISTORY_BY_SALESPERSON_QUERY, variables
        )
        return unwrap(data, "salespersonsPaymentsHistoryBySalesperson")
    except MolonionError as e:
        return _err(e)


SALESPERSONS_PAYMENTS_HISTORY_DOCS_QUERY = """
query ($companyId: Int!, $options: SalespersonsPaymentsHistoryOptions) {
  salespersonsPaymentsHistoryDocs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      documentTypeId
      documentSetName
      salespersonId
      number
      date
      totalValue
      yourReference
      geographicZoneId
    }
  }
}
"""


@mcp.tool()
async def get_salespersons_payments_history_docs(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Histórico de pagamentos a vendedores ao nível do DOCUMENTO: cada linha representa um
    documento e traz `documentId`, `documentTypeId`, série (`documentSetName`), o vendedor
    (`salespersonId`), número, data, valor total (`totalValue`), a referência
    (`yourReference`) e a zona geográfica (`geographicZoneId`). Detalhe por documento, ao
    contrário de `get_salespersons_payments_history_by_salesperson` que agrega por vendedor.

    Os filtros usam a estrutura genérica `field`/`comparison`/`value` da Moloni ON —
    passa uma lista de dicionários (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SALESPERSONS_PAYMENTS_HISTORY_DOCS_QUERY, variables
        )
        return unwrap(data, "salespersonsPaymentsHistoryDocs")
    except MolonionError as e:
        return _err(e)


SALESPERSONS_PAYMENTS_HISTORY_TOTALS_QUERY = """
query ($companyId: Int!, $options: SalespersonsPaymentsHistoryOptions) {
  salespersonsPaymentsHistoryTotals(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      docsCount
      totalDocsValue
    }
  }
}
"""


@mcp.tool()
async def get_salespersons_payments_history_totals(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
) -> Any:
    """Obtém os totais agregados do histórico de pagamentos a vendedores de uma empresa (um
    único registo): o número de documentos (`docsCount`) e o valor total dos documentos
    (`totalDocsValue`). Útil para uma vista global.

    Os filtros usam a estrutura genérica `field`/`comparison`/`value` da Moloni ON —
    passa uma lista de dicionários (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SALESPERSONS_PAYMENTS_HISTORY_TOTALS_QUERY, variables
        )
        return unwrap(data, "salespersonsPaymentsHistoryTotals")
    except MolonionError as e:
        return _err(e)


SALESPERSONS_PAYMENTS_PENDING_BY_SALESPERSON_QUERY = """
query ($companyId: Int!, $options: SalespersonsPaymentsPendingOptions) {
  salespersonsPaymentsPendingBySalesperson(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      salespersonId
      docsCount
      totalDocsValue
      totalCommission
      totalReconciledCommission
      totalRemainingCommission
      salesperson {
        salespersonId
        number
        name
        vat
        baseCommission
      }
    }
  }
}
"""


@mcp.tool()
async def get_salespersons_payments_pending_by_salesperson(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Comissões de vendedores pendentes (por pagar) agregadas por vendedor: cada linha
    traz o vendedor (`salesperson`: número, nome, NIF, comissão-base), o número de
    documentos (`docsCount`), o valor total dos documentos (`totalDocsValue`) e os totais
    de comissão — total (`totalCommission`), já reconciliada/paga
    (`totalReconciledCommission`) e em falta (`totalRemainingCommission`). Útil para saber
    quanto falta pagar de comissões a cada vendedor.

    Os filtros usam a estrutura genérica `field`/`comparison`/`value` da Moloni ON —
    passa uma lista de dicionários (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SALESPERSONS_PAYMENTS_PENDING_BY_SALESPERSON_QUERY, variables
        )
        return unwrap(data, "salespersonsPaymentsPendingBySalesperson")
    except MolonionError as e:
        return _err(e)


SALESPERSONS_PAYMENTS_PENDING_DOCS_QUERY = """
query ($companyId: Int!, $options: SalespersonsPaymentsPendingOptions) {
  salespersonsPaymentsPendingDocs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      salespersonCommissionDocumentId
      salespersonId
      commission
      reconciled
      remaining
      fullyReconciled
      document {
        documentId
        documentSetName
        number
        date
        expirationDate
        totalValue
        salespersonCommission
        entityVat
        entityName
        entityNumber
        geographicZoneId
      }
    }
  }
}
"""


@mcp.tool()
async def get_salespersons_payments_pending_docs(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Comissões de vendedores pendentes (por pagar) ao nível do DOCUMENTO: cada linha
    indica o vendedor (`salespersonId`), o valor da comissão (`commission`), o já
    reconciliado/pago (`reconciled`), o que falta (`remaining`), se está totalmente
    reconciliado (`fullyReconciled`) e o documento de origem aninhado (`document`: número,
    data, vencimento, série, total, comissão, entidade/cliente). Detalhe por documento, ao
    contrário de `get_salespersons_payments_pending_by_salesperson` que agrega por vendedor.

    Os filtros usam a estrutura genérica `field`/`comparison`/`value` da Moloni ON —
    passa uma lista de dicionários (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SALESPERSONS_PAYMENTS_PENDING_DOCS_QUERY, variables
        )
        return unwrap(data, "salespersonsPaymentsPendingDocs")
    except MolonionError as e:
        return _err(e)


SALESPERSONS_PAYMENTS_PENDING_TOTALS_QUERY = """
query ($companyId: Int!, $options: SalespersonsPaymentsPendingOptions) {
  salespersonsPaymentsPendingTotals(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      docsCount
      totalValue
      avgCommission
      avgDelayDays
    }
  }
}
"""


@mcp.tool()
async def get_salespersons_payments_pending_totals(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
) -> Any:
    """Obtém os totais agregados das comissões de vendedores pendentes (por pagar) de uma
    empresa (um único registo): o número de documentos (`docsCount`), o valor total
    pendente (`totalValue`), a comissão média (`avgCommission`) e o atraso médio em dias
    (`avgDelayDays`). Útil para uma vista global das comissões por pagar.

    Os filtros usam a estrutura genérica `field`/`comparison`/`value` da Moloni ON —
    passa uma lista de dicionários (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SALESPERSONS_PAYMENTS_PENDING_TOTALS_QUERY, variables
        )
        return unwrap(data, "salespersonsPaymentsPendingTotals")
    except MolonionError as e:
        return _err(e)


# ===========================================================================
# Extratos de vendas (SalesStatements)
# ===========================================================================

SALES_STATEMENTS_QUERY = """
query ($companyId: Int!, $options: SalesStatementOptions) {
  salesStatements(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      __typename
      documentId
      documentTypeId
      documentSetName
      number
      date
      status
      totalValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      entityVat
      entityName
      entityNumber
    }
  }
}
"""


@mcp.tool()
async def get_sales_statements(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o extrato de vendas a clientes: a lista de documentos de venda e o seu estado
    de liquidação/reconciliação num período. Cada documento usa a interface `DocumentRead`
    (campos comuns: número, série, data, estado, totais, reconciliação, entidade/cliente)
    e `__typename` identifica o tipo concreto. Para campos específicos de um tipo usa a
    tool dedicada.

    Atenção: ao contrário do extrato de compras, esta devolve uma LISTA de envelopes — o
    resultado já vem achatado numa única lista de documentos.

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON — passa uma lista de dicionários
    (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        raw = await _client.query(SALES_STATEMENTS_QUERY, variables)
        envelopes = (raw or {}).get("salesStatements") or []
        errs = [
            e for env in envelopes if env for e in (env.get("errors") or [])
        ]
        if errs:
            raise MolonionError(
                "A operação 'salesStatements' devolveu erros.",
                errors=errs,
            )
        return [t for env in envelopes if env for t in (env.get("data") or [])]
    except MolonionError as e:
        return _err(e)


SALES_STATEMENTS_TOTALS_QUERY = """
query ($companyId: Int!, $options: SalesStatementTotalsOptions) {
  salesStatementsTotals(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      grossValues
      totalDiscountValues
      taxesValues
      retentionsValues
      totalValues
      productsCount
      customersCount
      docsCount
    }
  }
}
"""


@mcp.tool()
async def get_sales_statements_totals(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
) -> Any:
    """Obtém os totais agregados do extrato de vendas a clientes (um único registo): os
    valores totais (`grossValues`, `totalDiscountValues`, `taxesValues`,
    `retentionsValues`, `totalValues`) e as contagens (`productsCount`, `customersCount`,
    `docsCount`). Útil para uma vista global do extrato de vendas.

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON — passa uma lista de dicionários
    (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SALES_STATEMENTS_TOTALS_QUERY, variables)
        return unwrap(data, "salesStatementsTotals")
    except MolonionError as e:
        return _err(e)


# ===========================================================================
# Notas de acerto (SettlementNote)
# ===========================================================================

SETTLEMENT_NOTE_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  settlementNote(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      financialDiscount
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      currencyExchangeTotalValue
      currencyExchangeExchange
      documentCalculationsMode
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      geographicZoneId
      terminalId
      yourReference
      ourReference
      economicActivityClassificationCodeId
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      importStatus
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_settlement_note(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma nota de acerto (documento de liquidação que salda/concilia
    valores entre documentos) pelo seu ID de documento: dados do documento (número, série,
    data, estado), o total (`totalValue`), o desconto financeiro (`financialDiscount`), o
    câmbio (`currencyExchangeTotalValue`, `currencyExchangeExchange`), o estado de
    reconciliação (`reconciledValue`, `remainingReconciledValue`,
    `reconciliationPercentage`, `totalRelatedAppliedValue`), os dados da entidade e o
    código CAE. Os documentos saldados, a entidade completa e os dados AT não são incluídos
    neste selection set — podem ser adicionados se necessário.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (nota de acerto) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(SETTLEMENT_NOTE_QUERY, variables)
        return unwrap(data, "settlementNote")
    except MolonionError as e:
        return _err(e)


SETTLEMENT_NOTE_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  settlementNoteGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_settlement_note_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma nota de acerto.
    Devolve `token`, `path` e `filename`, que se combinam para construir o URL de download
    do PDF. Nota: ao contrário de outras operações, não recebe `companyId` — apenas o
    `documentId`.

    Args:
        document_id: ID do documento (nota de acerto) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            SETTLEMENT_NOTE_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "settlementNoteGetPDFToken")
    except MolonionError as e:
        return _err(e)


SETTLEMENT_NOTE_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  settlementNoteGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_settlement_note_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar várias notas de acerto como um
    arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para construir o URL
    de download. O `full_path` identifica o ZIP a descarregar (caminho devolvido por uma
    operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(SETTLEMENT_NOTE_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "settlementNoteGetZIPToken")
    except MolonionError as e:
        return _err(e)


SETTLEMENT_NOTE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  settlementNoteLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_settlement_note_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às notas de acerto de uma empresa: criações,
    modificações e remoções. Cada entrada indica a operação (`operation`), os valores
    antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`, `email`)
    e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma nota de acerto específica (corresponde
            a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SETTLEMENT_NOTE_LOGS_QUERY, variables)
        return unwrap(data, "settlementNoteLogs")
    except MolonionError as e:
        return _err(e)


SETTLEMENT_NOTE_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  settlementNoteMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_settlement_note_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de notas de acerto e o estado de entrega
    de cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para confirmar a
    quem foi enviado o documento e se a entrega teve sucesso. Os logs detalhados de cada
    destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_settlement_note_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SETTLEMENT_NOTE_MAIL_RECIPIENTS_QUERY, variables
        )
        return unwrap(data, "settlementNoteMailRecipients")
    except MolonionError as e:
        return _err(e)


SETTLEMENT_NOTE_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  settlementNoteMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_settlement_note_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de envios por email de uma nota de acerto: cada registo indica o
    email de destino, o conteúdo, o `deliveryId` (que liga aos destinatários via
    `get_settlement_note_mail_recipients`) e a data de envio (`createdAt`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (nota de acerto) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SETTLEMENT_NOTE_MAILS_HISTORY_QUERY, variables
        )
        return unwrap(data, "settlementNoteMailsHistory")
    except MolonionError as e:
        return _err(e)


SETTLEMENT_NOTE_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  settlementNoteNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_settlement_note_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para uma nota de acerto numa dada série de
    documentos. Devolve `number` (o próximo número) e `name` (o nome da série). Útil antes
    de criar uma nova nota de acerto, para saber o número que lhe será atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(SETTLEMENT_NOTE_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "settlementNoteNextNumber")
    except MolonionError as e:
        return _err(e)


SETTLEMENT_NOTE_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: SettlementNoteOptions) {
  settlementNoteRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_settlement_note_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as notas de acerto de uma entidade que podem ser relacionadas/ligadas a outro
    documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade cujas notas de acerto relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SETTLEMENT_NOTE_RELATABLE_QUERY, variables)
        return unwrap(data, "settlementNoteRelatable")
    except MolonionError as e:
        return _err(e)


SETTLEMENT_NOTES_QUERY = """
query ($companyId: Int!, $options: SettlementNoteOptions) {
  settlementNotes(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      reconciledValue
      reconciliationPercentage
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_settlement_notes(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as notas de acerto de uma empresa, com os campos principais de cada
    uma: número, data, série, entidade, valor total, valor reconciliado (`reconciledValue`,
    `reconciliationPercentage`) e estado. Para obter o detalhe completo de uma nota de
    acerto usa `get_settlement_note`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SETTLEMENT_NOTES_QUERY, variables)
        return unwrap(data, "settlementNotes")
    except MolonionError as e:
        return _err(e)


# ===========================================================================
# Faturas simplificadas (SimplifiedInvoice)
# ===========================================================================

SIMPLIFIED_INVOICE_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  simplifiedInvoice(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscount
      globalDiscountValue
      commercialDiscountValue
      totalDiscountValue
      financialDiscount
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      currencyExchangeTotalValue
      currencyExchangeExchange
      documentCalculationsMode
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      geographicZoneId
      terminalId
      expirationDate
      maturityDateDays
      maturityDateName
      yourReference
      ourReference
      salespersonCommission
      economicActivityClassificationCodeId
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      importStatus
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_simplified_invoice(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma fatura simplificada pelo seu ID de documento: dados do
    documento (número, série, data, estado, totais), dados da entidade/cliente
    (`entityName`, `entityVat`, morada), descontos (`globalDiscountValue`,
    `commercialDiscountValue`, `financialDiscount`), câmbio (`currencyExchangeTotalValue`,
    `currencyExchangeExchange`), reconciliação, vencimento (`expirationDate`,
    `maturityDateDays`, `maturityDateName`), comissão do vendedor e o código CAE. As linhas
    de produtos, os impostos, o cliente completo, os documentos relacionados e os dados AT
    não são incluídos neste selection set — podem ser adicionados se necessário.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (fatura simplificada) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(SIMPLIFIED_INVOICE_QUERY, variables)
        return unwrap(data, "simplifiedInvoice")
    except MolonionError as e:
        return _err(e)


SIMPLIFIED_INVOICE_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  simplifiedInvoiceGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_simplified_invoice_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma fatura simplificada.
    Devolve `token`, `path` e `filename`, que se combinam para construir o URL de download
    do PDF. Nota: ao contrário de outras operações, não recebe `companyId` — apenas o
    `documentId`.

    Args:
        document_id: ID do documento (fatura simplificada) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            SIMPLIFIED_INVOICE_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "simplifiedInvoiceGetPDFToken")
    except MolonionError as e:
        return _err(e)


SIMPLIFIED_INVOICE_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  simplifiedInvoiceGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_simplified_invoice_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar várias faturas simplificadas como
    um arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para construir o
    URL de download. O `full_path` identifica o ZIP a descarregar (caminho devolvido por
    uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(SIMPLIFIED_INVOICE_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "simplifiedInvoiceGetZIPToken")
    except MolonionError as e:
        return _err(e)


SIMPLIFIED_INVOICE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  simplifiedInvoiceLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_simplified_invoice_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às faturas simplificadas de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`), os
    valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`,
    `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma fatura simplificada específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SIMPLIFIED_INVOICE_LOGS_QUERY, variables)
        return unwrap(data, "simplifiedInvoiceLogs")
    except MolonionError as e:
        return _err(e)


SIMPLIFIED_INVOICE_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  simplifiedInvoiceMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_simplified_invoice_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de faturas simplificadas e o estado de
    entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para
    confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os logs detalhados
    de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_simplified_invoice_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SIMPLIFIED_INVOICE_MAIL_RECIPIENTS_QUERY, variables
        )
        return unwrap(data, "simplifiedInvoiceMailRecipients")
    except MolonionError as e:
        return _err(e)


SIMPLIFIED_INVOICE_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  simplifiedInvoiceMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_simplified_invoice_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de envios por email de uma fatura simplificada: cada registo indica
    o email de destino, o conteúdo, o `deliveryId` (que liga aos destinatários via
    `get_simplified_invoice_mail_recipients`) e a data de envio (`createdAt`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (fatura simplificada) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SIMPLIFIED_INVOICE_MAILS_HISTORY_QUERY, variables
        )
        return unwrap(data, "simplifiedInvoiceMailsHistory")
    except MolonionError as e:
        return _err(e)


SIMPLIFIED_INVOICE_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  simplifiedInvoiceNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_simplified_invoice_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para uma fatura simplificada numa dada série de
    documentos. Devolve `number` (o próximo número) e `name` (o nome da série). Útil antes
    de criar uma nova fatura simplificada, para saber o número que lhe será atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(
            SIMPLIFIED_INVOICE_NEXT_NUMBER_QUERY, variables
        )
        return unwrap(data, "simplifiedInvoiceNextNumber")
    except MolonionError as e:
        return _err(e)


SIMPLIFIED_INVOICE_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: SimplifiedInvoiceOptions) {
  simplifiedInvoiceRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_simplified_invoice_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as faturas simplificadas de uma entidade que podem ser relacionadas/ligadas a
    outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (cliente) cujas faturas simplificadas relacionáveis se
            procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SIMPLIFIED_INVOICE_RELATABLE_QUERY, variables)
        return unwrap(data, "simplifiedInvoiceRelatable")
    except MolonionError as e:
        return _err(e)


SIMPLIFIED_INVOICES_QUERY = """
query ($companyId: Int!, $options: SimplifiedInvoiceOptions) {
  simplifiedInvoices(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      reconciledValue
      reconciliationPercentage
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_simplified_invoices(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as faturas simplificadas de uma empresa, com os campos principais de
    cada uma: número, data, série, entidade/cliente, valor total, valor reconciliado
    (`reconciledValue`, `reconciliationPercentage`) e estado. Para obter o detalhe completo
    de uma fatura simplificada usa `get_simplified_invoice`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SIMPLIFIED_INVOICES_QUERY, variables)
        return unwrap(data, "simplifiedInvoices")
    except MolonionError as e:
        return _err(e)


# ===========================================================================
# Regimes especiais de imposto (SpecialTaxScheme)
# ===========================================================================

SPECIAL_TAX_SCHEME_QUERY = """
query ($specialTaxSchemeId: Int!) {
  specialTaxScheme(specialTaxSchemeId: $specialTaxSchemeId) {
    errors { field msg }
    data {
      specialTaxSchemeId
      code
      title
      notes
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_special_tax_scheme(special_tax_scheme_id: int) -> Any:
    """Obtém um regime especial de imposto (tabela de referência global da Moloni ON) pelo
    seu ID: o código do país de IVA (`code`, ex. "pt"), o título (`title`), notas
    (`notes`), se está visível (`visible`) e se é removível (`deletable`). Nota: ao
    contrário da maioria das operações, NÃO recebe `companyId` — é uma tabela global. O
    país e as traduções não são incluídos neste selection set.

    Args:
        special_tax_scheme_id: ID do regime especial de imposto a obter.
    """
    variables = {"specialTaxSchemeId": special_tax_scheme_id}
    try:
        data = await _client.query(SPECIAL_TAX_SCHEME_QUERY, variables)
        return unwrap(data, "specialTaxScheme")
    except MolonionError as e:
        return _err(e)


SPECIAL_TAX_SCHEMES_QUERY = """
query ($options: SpecialTaxSchemeOptions) {
  specialTaxSchemes(options: $options) {
    errors { field msg }
    data {
      specialTaxSchemeId
      code
      title
      notes
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def list_special_tax_schemes(
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os regimes especiais de imposto (tabela de referência global da Moloni ON),
    cada um com `specialTaxSchemeId`, o código de país de IVA (`code`), o título (`title`),
    notas (`notes`) e `visible`. Nota: ao contrário da maioria das operações, NÃO recebe
    `companyId` — é uma tabela global.

    Args:
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SPECIAL_TAX_SCHEMES_QUERY, variables)
        return unwrap(data, "specialTaxSchemes")
    except MolonionError as e:
        return _err(e)


# ===========================================================================
# Movimentos de stock (StockMovements)
# ===========================================================================

STOCK_MOVEMENTS_QUERY = """
query ($companyId: Int!, $productId: Int!, $options: StockMovementOptions) {
  stockMovements(companyId: $companyId, productId: $productId, options: $options) {
    errors { field msg }
    data {
      stockMovementId
      type
      direction
      date
      qty
      acc
      order
      costPrice
      unitPrice
      lineUnitPrice
      totalValue
      fifoStock
      lifoStock
      fifoProfit
      lifoProfit
      notes
      parentId
      document {
        __typename
        documentId
        documentTypeId
        documentSetName
        number
        date
        entityName
      }
    }
  }
}
"""


@mcp.tool()
async def get_stock_movements(
    company_id: int,
    product_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de movimentos de stock de um produto (entradas, saídas,
    transferências) em todos os armazéns, por ordem cronológica. Cada linha indica o tipo
    (`type`), o sentido (`direction`), a data, a quantidade (`qty`), o stock acumulado
    (`acc`), preços (`costPrice`, `unitPrice`, `lineUnitPrice`, `totalValue`), os valores
    FIFO/LIFO de stock e lucro (`fifoStock`/`lifoStock`/`fifoProfit`/`lifoProfit`), as notas
    e o documento de origem aninhado (`document`, interface `DocumentRead`; `__typename` dá
    o tipo). Os movimentos por armazém (`warehouseMovements`) não são incluídos.

    Os filtros usam a estrutura genérica `field`/`comparison`/`value` da Moloni ON — passa
    uma lista de dicionários (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        product_id: ID do produto cujos movimentos de stock se pretendem.
        filters: opcional; lista de filtros `{field, comparison, value}`.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "productId": product_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(STOCK_MOVEMENTS_QUERY, variables)
        return unwrap(data, "stockMovements")
    except MolonionError as e:
        return _err(e)


STOCK_PRODUCTS_QUERY = """
query ($companyId: Int!, $options: ListStockMovementOptions) {
  stockProducts(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      productId
      reference
      name
      type
      stock
      minStock
      costPrice
      price
      priceWithTaxes
      totalCostPrice
      totalSale
      warehouseId
      productCategoryId
      measurementUnitId
      propertyGroupId
      parentId
      variantsCount
      img
    }
  }
}
"""


@mcp.tool()
async def list_stock_products(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os produtos com a respetiva informação de stock de uma empresa: cada linha traz
    `productId`, `reference`, `name`, `type`, o stock atual (`stock`) e mínimo (`minStock`),
    os preços (`costPrice`, `price`, `priceWithTaxes`), o valor de inventário
    (`totalCostPrice`, `totalSale`) e as chaves estrangeiras (armazém, categoria, unidade,
    grupo de propriedades, produto-pai). Útil para relatórios de inventário/stock.

    Os filtros usam a estrutura genérica `field`/`comparison`/`value` da Moloni ON — passa
    uma lista de dicionários (ver `get_sales_analysis_by_date`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: opcional; lista de filtros `{field, comparison, value}`.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(STOCK_PRODUCTS_QUERY, variables)
        return unwrap(data, "stockProducts")
    except MolonionError as e:
        return _err(e)


# NOTA: tal como `customerHistoryUserSettingsTemplates`, esta devolve uma LISTA de
# envelopes (`[StockUserSettingsTemplates]!`), não um único envelope — por isso o
# `unwrap()` não se aplica; tratamos a lista à mão.
STOCK_TEMPLATES_QUERY = """
query ($companyId: Int!) {
  stockUserSettingsTemplates(companyId: $companyId) {
    errors { field msg }
    data {
      userSettingsTemplateId
      formName
      name
    }
  }
}
"""


@mcp.tool()
async def list_stock_templates(company_id: int) -> Any:
    """Lista os modelos (templates) de definições do utilizador para o ecrã de stock —
    filtros/colunas guardados pelo utilizador para reutilizar. Cada modelo tem
    `userSettingsTemplateId`, `formName` (o formulário a que se aplica) e `name`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
    """
    try:
        raw = await _client.query(STOCK_TEMPLATES_QUERY, {"companyId": company_id})
        envelopes = (raw or {}).get("stockUserSettingsTemplates") or []
        errs = [
            e for env in envelopes if env for e in (env.get("errors") or [])
        ]
        if errs:
            raise MolonionError(
                "A operação 'stockUserSettingsTemplates' devolveu erros.",
                errors=errs,
            )
        return [t for env in envelopes if env for t in (env.get("data") or [])]
    except MolonionError as e:
        return _err(e)


# ===========================================================================
# Suplementos / módulos disponíveis (SupplementAvailableModules)
# ===========================================================================

# NOTA: o campo `data` é o scalar `SupplementAvailableModules` (um JSON), não um
# objeto — por isso o selection set pede `data` sem subcampos (padrão "data escalar",
# como em `meLoggedIn`/`customerNextNumber`).
SUPPLEMENT_AVAILABLE_MODULES_QUERY = """
query ($countryISO: String!, $languageISO: String!) {
  supplementAvailableModules(countryISO: $countryISO, languageISO: $languageISO) {
    errors { field msg }
    data
  }
}
"""


@mcp.tool()
async def get_supplement_available_modules(
    country_iso: str, language_iso: str
) -> Any:
    """Obtém os módulos/suplementos disponíveis (add-ons da subscrição Moloni ON) para um
    país e idioma. Devolve `data` como um objeto JSON livre (scalar
    `SupplementAvailableModules`) com a estrutura dos módulos disponíveis (nomes, códigos,
    preços, etc., conforme devolvido pela API). Nota: ao contrário da maioria das
    operações, NÃO recebe `companyId` — é parametrizada por país/idioma.

    Args:
        country_iso: código ISO do país (ex. "PT").
        language_iso: código ISO do idioma (ex. "pt").
    """
    variables = {"countryISO": country_iso, "languageISO": language_iso}
    try:
        data = await _client.query(SUPPLEMENT_AVAILABLE_MODULES_QUERY, variables)
        return unwrap(data, "supplementAvailableModules")
    except MolonionError as e:
        return _err(e)


# ===========================================================================
# Fornecedores (Supplier)
# ===========================================================================

SUPPLIER_QUERY = """
query ($companyId: Int!, $supplierId: Int!) {
  supplier(companyId: $companyId, supplierId: $supplierId) {
    errors { field msg }
    data {
      supplierId
      number
      name
      vat
      address
      city
      zipCode
      email
      phone
      fax
      website
      contactName
      contactEmail
      contactPhone
      notes
      documentNotes
      notesOnDocs
      exemptionReason
      swift
      iban
      sepaId
      discount
      creditLimit
      countryId
      languageId
      geographicZoneId
      maturityDateId
      paymentMethodId
      deliveryMethodId
      companyId
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_supplier(company_id: int, supplier_id: int) -> Any:
    """Obtém os detalhes de um fornecedor pelo seu ID: o número (`number`), o nome, o NIF
    (`vat`), a morada, os contactos (`email`, `phone`, `contactName`/`contactEmail`/
    `contactPhone`), as notas (`notes`, `documentNotes`), os dados bancários (`swift`,
    `iban`, `sepaId`), o desconto (`discount`), o limite de crédito (`creditLimit`), a
    razão de isenção e as chaves estrangeiras (país, idioma, zona, vencimento, método de
    pagamento/entrega). Os objetos aninhados (país, impostos, etc.) não são incluídos.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        supplier_id: ID do fornecedor a obter.
    """
    variables = {"companyId": company_id, "supplierId": supplier_id}
    try:
        data = await _client.query(SUPPLIER_QUERY, variables)
        return unwrap(data, "supplier")
    except MolonionError as e:
        return _err(e)


SUPPLIER_BILLS_OF_LADING_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  supplierBillsOfLading(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscount
      globalDiscountValue
      commercialDiscountValue
      totalDiscountValue
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      currencyExchangeTotalValue
      currencyExchangeExchange
      documentCalculationsMode
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      geographicZoneId
      terminalId
      expirationDate
      maturityDateDays
      maturityDateName
      yourReference
      ourReference
      economicActivityClassificationCodeId
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      file
      fileOriginal
      importStatus
      deliveryMethodName
      deliveryVehicleLicensePlate
      deliveryLoadDate
      deliveryLoadAddress
      deliveryLoadCity
      deliveryLoadZipCode
      deliveryUnloadAddress
      deliveryUnloadCity
      deliveryUnloadZipCode
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_supplier_bills_of_lading(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma guia de transporte de compra (documento de fornecedor) pelo
    seu ID de documento: dados do documento (número, série, data, estado, totais), dados da
    entidade/fornecedor (`entityName`, `entityVat`, morada), descontos, câmbio,
    reconciliação, vencimento, o código CAE, o ficheiro arquivado (`file`/`fileOriginal`),
    o estado de importação (`importStatus`) e os dados de transporte (método de entrega,
    matrícula, carga/descarga). As linhas de produtos, os impostos, o fornecedor completo e
    os documentos relacionados não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (guia de transporte de compra) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(SUPPLIER_BILLS_OF_LADING_QUERY, variables)
        return unwrap(data, "supplierBillsOfLading")
    except MolonionError as e:
        return _err(e)


SUPPLIER_BILLS_OF_LADING_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  supplierBillsOfLadingGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_supplier_bills_of_lading_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma guia de transporte de
    compra. Devolve `token`, `path` e `filename`, que se combinam para construir o URL de
    download do PDF. Nota: ao contrário de outras operações, não recebe `companyId` —
    apenas o `documentId`.

    Args:
        document_id: ID do documento (guia de transporte de compra) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            SUPPLIER_BILLS_OF_LADING_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "supplierBillsOfLadingGetPDFToken")
    except MolonionError as e:
        return _err(e)


SUPPLIER_BILLS_OF_LADING_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  supplierBillsOfLadingGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_supplier_bills_of_lading_zip_token(
    company_id: int, full_path: str
) -> Any:
    """Gera um token temporário e seguro para descarregar várias guias de transporte de
    compra como um arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para
    construir o URL de download. O `full_path` identifica o ZIP a descarregar (caminho
    devolvido por uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(
            SUPPLIER_BILLS_OF_LADING_ZIP_TOKEN_QUERY, variables
        )
        return unwrap(data, "supplierBillsOfLadingGetZIPToken")
    except MolonionError as e:
        return _err(e)


SUPPLIER_BILLS_OF_LADING_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  supplierBillsOfLadingLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_supplier_bills_of_lading_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às guias de transporte de compra de uma
    empresa: criações, modificações e remoções. Cada entrada indica a operação
    (`operation`), os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma guia de transporte de compra específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SUPPLIER_BILLS_OF_LADING_LOGS_QUERY, variables)
        return unwrap(data, "supplierBillsOfLadingLogs")
    except MolonionError as e:
        return _err(e)


SUPPLIER_BILLS_OF_LADING_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  supplierBillsOfLadingMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_supplier_bills_of_lading_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de guias de transporte de compra e o
    estado de entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`).
    Útil para confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os logs
    detalhados de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_supplier_bills_of_lading_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SUPPLIER_BILLS_OF_LADING_MAIL_RECIPIENTS_QUERY, variables
        )
        return unwrap(data, "supplierBillsOfLadingMailRecipients")
    except MolonionError as e:
        return _err(e)


SUPPLIER_BILLS_OF_LADING_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  supplierBillsOfLadingMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_supplier_bills_of_lading_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de envios por email de uma guia de transporte de compra: cada
    registo indica o email de destino, o conteúdo, o `deliveryId` (que liga aos
    destinatários via `get_supplier_bills_of_lading_mail_recipients`) e a data de envio
    (`createdAt`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (guia de transporte de compra) cujos envios se
            pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SUPPLIER_BILLS_OF_LADING_MAILS_HISTORY_QUERY, variables
        )
        return unwrap(data, "supplierBillsOfLadingMailsHistory")
    except MolonionError as e:
        return _err(e)


SUPPLIER_BILLS_OF_LADING_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  supplierBillsOfLadingNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_supplier_bills_of_lading_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para uma guia de transporte de compra numa dada
    série de documentos. Devolve `number` (o próximo número) e `name` (o nome da série).
    Útil antes de criar uma nova guia de transporte de compra, para saber o número que lhe
    será atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(
            SUPPLIER_BILLS_OF_LADING_NEXT_NUMBER_QUERY, variables
        )
        return unwrap(data, "supplierBillsOfLadingNextNumber")
    except MolonionError as e:
        return _err(e)


SUPPLIER_BILLS_OF_LADING_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: SupplierBillsOfLadingOptions) {
  supplierBillsOfLadingRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_supplier_bills_of_lading_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as guias de transporte de compra de uma entidade (fornecedor) que podem ser
    relacionadas/ligadas a outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (fornecedor) cujas guias relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SUPPLIER_BILLS_OF_LADING_RELATABLE_QUERY, variables
        )
        return unwrap(data, "supplierBillsOfLadingRelatable")
    except MolonionError as e:
        return _err(e)


SUPPLIER_BILLS_OF_LADINGS_QUERY = """
query ($companyId: Int!, $options: SupplierBillsOfLadingOptions) {
  supplierBillsOfLadings(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_supplier_bills_of_ladings(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as guias de transporte de compra de uma empresa, com os campos
    principais de cada uma: número, data, série, entidade/fornecedor, valor total e estado.
    Para obter o detalhe completo de uma guia usa `get_supplier_bills_of_lading`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SUPPLIER_BILLS_OF_LADINGS_QUERY, variables)
        return unwrap(data, "supplierBillsOfLadings")
    except MolonionError as e:
        return _err(e)


SUPPLIER_CREDIT_NOTE_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  supplierCreditNote(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscount
      globalDiscountValue
      commercialDiscountValue
      totalDiscountValue
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      currencyExchangeTotalValue
      currencyExchangeExchange
      documentCalculationsMode
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      geographicZoneId
      terminalId
      yourReference
      ourReference
      economicActivityClassificationCodeId
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      file
      fileOriginal
      importStatus
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_supplier_credit_note(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma nota de crédito de compra (documento de fornecedor que anula
    ou corrige uma compra) pelo seu ID de documento: dados do documento (número, série,
    data, estado, totais), dados da entidade/fornecedor (`entityName`, `entityVat`, morada),
    descontos, câmbio, reconciliação, o código CAE, o ficheiro arquivado
    (`file`/`fileOriginal`) e o estado de importação (`importStatus`). Ao contrário de outros
    documentos de compra, NÃO tem dados de vencimento nem de transporte. As linhas de
    produtos, os impostos, o fornecedor completo e os documentos relacionados não são
    incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (nota de crédito de compra) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(SUPPLIER_CREDIT_NOTE_QUERY, variables)
        return unwrap(data, "supplierCreditNote")
    except MolonionError as e:
        return _err(e)


SUPPLIER_CREDIT_NOTE_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  supplierCreditNoteGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_supplier_credit_note_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma nota de crédito de
    compra. Devolve `token`, `path` e `filename`, que se combinam para construir o URL de
    download do PDF. Nota: ao contrário de outras operações, não recebe `companyId` —
    apenas o `documentId`.

    Args:
        document_id: ID do documento (nota de crédito de compra) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            SUPPLIER_CREDIT_NOTE_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "supplierCreditNoteGetPDFToken")
    except MolonionError as e:
        return _err(e)


SUPPLIER_CREDIT_NOTE_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  supplierCreditNoteGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_supplier_credit_note_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar várias notas de crédito de compra
    como um arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para
    construir o URL de download. O `full_path` identifica o ZIP a descarregar (caminho
    devolvido por uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(SUPPLIER_CREDIT_NOTE_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "supplierCreditNoteGetZIPToken")
    except MolonionError as e:
        return _err(e)


SUPPLIER_CREDIT_NOTE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  supplierCreditNoteLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_supplier_credit_note_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às notas de crédito de compra de uma empresa:
    criações, modificações e remoções. Cada entrada indica a operação (`operation`), os
    valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`,
    `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma nota de crédito de compra específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SUPPLIER_CREDIT_NOTE_LOGS_QUERY, variables)
        return unwrap(data, "supplierCreditNoteLogs")
    except MolonionError as e:
        return _err(e)


SUPPLIER_CREDIT_NOTE_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  supplierCreditNoteMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_supplier_credit_note_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de notas de crédito de compra e o estado
    de entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para
    confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os logs detalhados
    de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_supplier_credit_note_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SUPPLIER_CREDIT_NOTE_MAIL_RECIPIENTS_QUERY, variables
        )
        return unwrap(data, "supplierCreditNoteMailRecipients")
    except MolonionError as e:
        return _err(e)


SUPPLIER_CREDIT_NOTE_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  supplierCreditNoteMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_supplier_credit_note_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de envios por email de uma nota de crédito de compra: cada registo
    indica o email de destino, o conteúdo, o `deliveryId` (que liga aos destinatários via
    `get_supplier_credit_note_mail_recipients`) e a data de envio (`createdAt`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (nota de crédito de compra) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SUPPLIER_CREDIT_NOTE_MAILS_HISTORY_QUERY, variables
        )
        return unwrap(data, "supplierCreditNoteMailsHistory")
    except MolonionError as e:
        return _err(e)


SUPPLIER_CREDIT_NOTE_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  supplierCreditNoteNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_supplier_credit_note_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para uma nota de crédito de compra numa dada série
    de documentos. Devolve `number` (o próximo número) e `name` (o nome da série). Útil
    antes de criar uma nova nota de crédito de compra, para saber o número que lhe será
    atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(
            SUPPLIER_CREDIT_NOTE_NEXT_NUMBER_QUERY, variables
        )
        return unwrap(data, "supplierCreditNoteNextNumber")
    except MolonionError as e:
        return _err(e)


SUPPLIER_CREDIT_NOTE_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: SupplierCreditNoteOptions) {
  supplierCreditNoteRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_supplier_credit_note_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as notas de crédito de compra de uma entidade (fornecedor) que podem ser
    relacionadas/ligadas a outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (fornecedor) cujas notas de crédito relacionáveis se
            procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SUPPLIER_CREDIT_NOTE_RELATABLE_QUERY, variables
        )
        return unwrap(data, "supplierCreditNoteRelatable")
    except MolonionError as e:
        return _err(e)


SUPPLIER_CREDIT_NOTES_QUERY = """
query ($companyId: Int!, $options: SupplierCreditNoteOptions) {
  supplierCreditNotes(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      reconciledValue
      reconciliationPercentage
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_supplier_credit_notes(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as notas de crédito de compra de uma empresa, com os campos
    principais de cada uma: número, data, série, entidade/fornecedor, valor total, valor
    reconciliado (`reconciledValue`, `reconciliationPercentage`) e estado. Para obter o
    detalhe completo de uma nota de crédito de compra usa `get_supplier_credit_note`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SUPPLIER_CREDIT_NOTES_QUERY, variables)
        return unwrap(data, "supplierCreditNotes")
    except MolonionError as e:
        return _err(e)


SUPPLIER_INVOICE_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  supplierInvoice(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscount
      globalDiscountValue
      commercialDiscountValue
      totalDiscountValue
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      currencyExchangeTotalValue
      currencyExchangeExchange
      documentCalculationsMode
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      geographicZoneId
      terminalId
      expirationDate
      maturityDateDays
      maturityDateName
      yourReference
      ourReference
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      file
      fileOriginal
      importStatus
      deliveryMethodName
      deliveryVehicleName
      deliveryVehicleLicensePlate
      deliveryLoadDate
      deliveryLoadAddress
      deliveryLoadCity
      deliveryLoadZipCode
      deliveryUnloadAddress
      deliveryUnloadCity
      deliveryUnloadZipCode
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_supplier_invoice(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma fatura de compra (documento de fornecedor) pelo seu ID de
    documento: dados do documento (número, série, data, estado, totais), dados da
    entidade/fornecedor (`entityName`, `entityVat`, morada), descontos, câmbio,
    reconciliação, vencimento (`expirationDate`, `maturityDateDays`, `maturityDateName`),
    o ficheiro arquivado (`file`/`fileOriginal`), o estado de importação (`importStatus`) e
    os dados de transporte. As linhas de produtos, os impostos, o fornecedor completo e os
    documentos relacionados não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (fatura de compra) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(SUPPLIER_INVOICE_QUERY, variables)
        return unwrap(data, "supplierInvoice")
    except MolonionError as e:
        return _err(e)


SUPPLIER_INVOICE_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  supplierInvoiceGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_supplier_invoice_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma fatura de compra.
    Devolve `token`, `path` e `filename`, que se combinam para construir o URL de download
    do PDF. Nota: ao contrário de outras operações, não recebe `companyId` — apenas o
    `documentId`.

    Args:
        document_id: ID do documento (fatura de compra) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            SUPPLIER_INVOICE_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "supplierInvoiceGetPDFToken")
    except MolonionError as e:
        return _err(e)


SUPPLIER_INVOICE_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  supplierInvoiceGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_supplier_invoice_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar várias faturas de compra como um
    arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para construir o URL
    de download. O `full_path` identifica o ZIP a descarregar (caminho devolvido por uma
    operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(SUPPLIER_INVOICE_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "supplierInvoiceGetZIPToken")
    except MolonionError as e:
        return _err(e)


SUPPLIER_INVOICE_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  supplierInvoiceLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_supplier_invoice_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às faturas de compra de uma empresa: criações,
    modificações e remoções. Cada entrada indica a operação (`operation`), os valores
    antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`, `email`)
    e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma fatura de compra específica
            (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SUPPLIER_INVOICE_LOGS_QUERY, variables)
        return unwrap(data, "supplierInvoiceLogs")
    except MolonionError as e:
        return _err(e)


SUPPLIER_INVOICE_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  supplierInvoiceMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_supplier_invoice_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de faturas de compra e o estado de
    entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para
    confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os logs detalhados
    de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_supplier_invoice_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SUPPLIER_INVOICE_MAIL_RECIPIENTS_QUERY, variables
        )
        return unwrap(data, "supplierInvoiceMailRecipients")
    except MolonionError as e:
        return _err(e)


SUPPLIER_INVOICE_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  supplierInvoiceMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_supplier_invoice_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de envios por email de uma fatura de compra: cada registo indica o
    email de destino, o conteúdo, o `deliveryId` (que liga aos destinatários via
    `get_supplier_invoice_mail_recipients`) e a data de envio (`createdAt`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (fatura de compra) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SUPPLIER_INVOICE_MAILS_HISTORY_QUERY, variables
        )
        return unwrap(data, "supplierInvoiceMailsHistory")
    except MolonionError as e:
        return _err(e)


SUPPLIER_INVOICE_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  supplierInvoiceNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_supplier_invoice_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para uma fatura de compra numa dada série de
    documentos. Devolve `number` (o próximo número) e `name` (o nome da série). Útil antes
    de criar uma nova fatura de compra, para saber o número que lhe será atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(SUPPLIER_INVOICE_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "supplierInvoiceNextNumber")
    except MolonionError as e:
        return _err(e)


SUPPLIER_INVOICE_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: SupplierInvoiceOptions) {
  supplierInvoiceRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_supplier_invoice_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as faturas de compra de uma entidade (fornecedor) que podem ser
    relacionadas/ligadas a outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (fornecedor) cujas faturas relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SUPPLIER_INVOICE_RELATABLE_QUERY, variables)
        return unwrap(data, "supplierInvoiceRelatable")
    except MolonionError as e:
        return _err(e)


SUPPLIER_INVOICES_QUERY = """
query ($companyId: Int!, $options: SupplierInvoiceOptions) {
  supplierInvoices(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      expirationDate
      documentSetName
      entityName
      entityVat
      totalValue
      reconciledValue
      reconciliationPercentage
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_supplier_invoices(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as faturas de compra de uma empresa, com os campos principais de
    cada uma: número, data, validade (`expirationDate`), série, entidade/fornecedor, valor
    total, valor reconciliado (`reconciledValue`, `reconciliationPercentage`) e estado.
    Para obter o detalhe completo de uma fatura de compra usa `get_supplier_invoice`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SUPPLIER_INVOICES_QUERY, variables)
        return unwrap(data, "supplierInvoices")
    except MolonionError as e:
        return _err(e)


SUPPLIER_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  supplierLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_supplier_logs(
    company_id: int,
    supplier_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos fornecedores de uma empresa: criações,
    modificações e remoções. Cada entrada indica a operação (`operation`), os valores
    antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`, `email`)
    e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        supplier_id: opcional; filtra os logs de um fornecedor específico (corresponde a
            `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if supplier_id is not None:
        options["relatedId"] = supplier_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SUPPLIER_LOGS_QUERY, variables)
        return unwrap(data, "supplierLogs")
    except MolonionError as e:
        return _err(e)


SUPPLIER_PURCHASE_ORDER_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  supplierPurchaseOrder(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      grossValue
      taxesValue
      globalDiscount
      globalDiscountValue
      commercialDiscountValue
      totalDiscountValue
      retentionsValue
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      currencyExchangeTotalValue
      currencyExchangeExchange
      documentCalculationsMode
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      geographicZoneId
      terminalId
      expirationDate
      maturityDateDays
      maturityDateName
      yourReference
      ourReference
      economicActivityClassificationCodeId
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      importStatus
      deliveryMethodName
      deliveryVehicleName
      deliveryVehicleLicensePlate
      deliveryLoadDate
      deliveryLoadAddress
      deliveryLoadCity
      deliveryLoadZipCode
      deliveryUnloadAddress
      deliveryUnloadCity
      deliveryUnloadZipCode
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_supplier_purchase_order(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de uma nota de encomenda de compra a fornecedor (documento de
    fornecedor) pelo seu ID de documento: dados do documento (número, série, data, estado,
    totais), dados da entidade/fornecedor (`entityName`, `entityVat`, morada), descontos,
    câmbio, reconciliação, vencimento (`expirationDate`, `maturityDateDays`,
    `maturityDateName`), o código CAE (`economicActivityClassificationCodeId`), o estado de
    importação (`importStatus`) e os dados de transporte. As linhas de produtos, os impostos,
    o fornecedor completo e os documentos relacionados não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (nota de encomenda de compra a fornecedor) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(SUPPLIER_PURCHASE_ORDER_QUERY, variables)
        return unwrap(data, "supplierPurchaseOrder")
    except MolonionError as e:
        return _err(e)


SUPPLIER_PURCHASE_ORDER_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  supplierPurchaseOrderGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_supplier_purchase_order_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de uma nota de encomenda de
    compra a fornecedor. Devolve `token`, `path` e `filename`, que se combinam para
    construir o URL de download do PDF. Nota: ao contrário de outras operações, não recebe
    `companyId` — apenas o `documentId`.

    Args:
        document_id: ID do documento (nota de encomenda de compra a fornecedor) cujo PDF se
            pretende.
    """
    try:
        data = await _client.query(
            SUPPLIER_PURCHASE_ORDER_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "supplierPurchaseOrderGetPDFToken")
    except MolonionError as e:
        return _err(e)


SUPPLIER_PURCHASE_ORDER_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  supplierPurchaseOrderGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_supplier_purchase_order_zip_token(
    company_id: int, full_path: str
) -> Any:
    """Gera um token temporário e seguro para descarregar várias notas de encomenda de
    compra a fornecedor como um arquivo ZIP. Devolve `token`, `path` e `filename`, que se
    combinam para construir o URL de download. O `full_path` identifica o ZIP a descarregar
    (caminho devolvido por uma operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(
            SUPPLIER_PURCHASE_ORDER_ZIP_TOKEN_QUERY, variables
        )
        return unwrap(data, "supplierPurchaseOrderGetZIPToken")
    except MolonionError as e:
        return _err(e)


SUPPLIER_PURCHASE_ORDER_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  supplierPurchaseOrderLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_supplier_purchase_order_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às notas de encomenda de compra a fornecedor de
    uma empresa: criações, modificações e remoções. Cada entrada indica a operação
    (`operation`), os valores antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`,
    `username`, `email`) e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de uma nota de encomenda de compra a fornecedor
            específica (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SUPPLIER_PURCHASE_ORDER_LOGS_QUERY, variables)
        return unwrap(data, "supplierPurchaseOrderLogs")
    except MolonionError as e:
        return _err(e)


SUPPLIER_PURCHASE_ORDER_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  supplierPurchaseOrderMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_supplier_purchase_order_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de notas de encomenda de compra a
    fornecedor e o estado de entrega de cada um (`status`, `internalStatus`,
    `mailServiceResponseId`). Útil para confirmar a quem foi enviado o documento e se a
    entrega teve sucesso. Os logs detalhados de cada destinatário não são incluídos neste
    selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_supplier_purchase_order_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SUPPLIER_PURCHASE_ORDER_MAIL_RECIPIENTS_QUERY, variables
        )
        return unwrap(data, "supplierPurchaseOrderMailRecipients")
    except MolonionError as e:
        return _err(e)


SUPPLIER_PURCHASE_ORDER_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  supplierPurchaseOrderMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_supplier_purchase_order_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de envios por email de uma nota de encomenda de compra a fornecedor:
    cada registo indica o email de destino, o conteúdo, o `deliveryId` (que liga aos
    destinatários via `get_supplier_purchase_order_mail_recipients`) e a data de envio
    (`createdAt`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (nota de encomenda de compra a fornecedor) cujos envios
            se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SUPPLIER_PURCHASE_ORDER_MAILS_HISTORY_QUERY, variables
        )
        return unwrap(data, "supplierPurchaseOrderMailsHistory")
    except MolonionError as e:
        return _err(e)


SUPPLIER_PURCHASE_ORDER_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  supplierPurchaseOrderNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_supplier_purchase_order_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para uma nota de encomenda de compra a fornecedor
    numa dada série de documentos. Devolve `number` (o próximo número) e `name` (o nome da
    série). Útil antes de criar uma nova nota de encomenda de compra a fornecedor, para
    saber o número que lhe será atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(
            SUPPLIER_PURCHASE_ORDER_NEXT_NUMBER_QUERY, variables
        )
        return unwrap(data, "supplierPurchaseOrderNextNumber")
    except MolonionError as e:
        return _err(e)


SUPPLIER_PURCHASE_ORDER_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: SupplierPurchaseOrderOptions) {
  supplierPurchaseOrderRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_supplier_purchase_order_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista as notas de encomenda de compra a fornecedor de uma entidade (fornecedor) que
    podem ser relacionadas/ligadas a outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (fornecedor) cujas notas de encomenda relacionáveis se
            procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SUPPLIER_PURCHASE_ORDER_RELATABLE_QUERY, variables
        )
        return unwrap(data, "supplierPurchaseOrderRelatable")
    except MolonionError as e:
        return _err(e)


SUPPLIER_PURCHASE_ORDERS_QUERY = """
query ($companyId: Int!, $options: SupplierPurchaseOrderOptions) {
  supplierPurchaseOrders(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      expirationDate
      documentSetName
      entityName
      entityVat
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_supplier_purchase_orders(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as notas de encomenda de compra a fornecedor de uma empresa, com os
    campos principais de cada uma: número, data, validade (`expirationDate`), série,
    entidade/fornecedor, valor total e estado. Para obter o detalhe completo de uma usa
    `get_supplier_purchase_order`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SUPPLIER_PURCHASE_ORDERS_QUERY, variables)
        return unwrap(data, "supplierPurchaseOrders")
    except MolonionError as e:
        return _err(e)


SUPPLIER_RECEIPT_QUERY = """
query ($companyId: Int!, $documentId: Int!) {
  supplierReceipt(companyId: $companyId, documentId: $documentId) {
    errors { field msg }
    data {
      documentId
      companyId
      documentTypeId
      documentSetName
      documentSetId
      number
      date
      year
      fiscalZone
      status
      suspended
      nullified
      deletable
      nullifiable
      totalValue
      documentTotal
      reconciledValue
      remainingReconciledValue
      reconciliationPercentage
      totalRelatedAppliedValue
      currencyExchangeTotalValue
      currencyExchangeExchange
      documentCalculationsMode
      entityVat
      entityName
      entityNumber
      entityAddress
      entityZipCode
      entityCity
      entityCountryName
      countryId
      geographicZoneId
      terminalId
      yourReference
      ourReference
      economicActivityClassificationCodeId
      notes
      notesRelatedDocs
      hash
      hashControl
      pdfExport
      emailsCount
      downloads
      file
      fileOriginal
      importStatus
      createdAt
      updatedAt
      lastModified
    }
  }
}
"""


@mcp.tool()
async def get_supplier_receipt(company_id: int, document_id: int) -> Any:
    """Obtém os detalhes de um recibo de compra (documento de liquidação que salda compras a
    um fornecedor) pelo seu ID de documento: dados do documento (número, série, data,
    estado), o total (`totalValue`), o câmbio (`currencyExchangeTotalValue`,
    `currencyExchangeExchange`), o estado de reconciliação (`reconciledValue`,
    `remainingReconciledValue`, `reconciliationPercentage`, `totalRelatedAppliedValue`), os
    dados da entidade/fornecedor, o código CAE, o ficheiro arquivado (`file`/`fileOriginal`)
    e o estado de importação (`importStatus`). Os documentos saldados, a entidade completa e
    os dados AT não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (recibo de compra) a obter.
    """
    variables = {"companyId": company_id, "documentId": document_id}
    try:
        data = await _client.query(SUPPLIER_RECEIPT_QUERY, variables)
        return unwrap(data, "supplierReceipt")
    except MolonionError as e:
        return _err(e)


SUPPLIER_RECEIPT_PDF_TOKEN_QUERY = """
query ($documentId: Int!) {
  supplierReceiptGetPDFToken(documentId: $documentId) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_supplier_receipt_pdf_token(document_id: int) -> Any:
    """Gera um token temporário e seguro para descarregar o PDF de um recibo de compra.
    Devolve `token`, `path` e `filename`, que se combinam para construir o URL de download
    do PDF. Nota: ao contrário de outras operações, não recebe `companyId` — apenas o
    `documentId`.

    Args:
        document_id: ID do documento (recibo de compra) cujo PDF se pretende.
    """
    try:
        data = await _client.query(
            SUPPLIER_RECEIPT_PDF_TOKEN_QUERY, {"documentId": document_id}
        )
        return unwrap(data, "supplierReceiptGetPDFToken")
    except MolonionError as e:
        return _err(e)


SUPPLIER_RECEIPT_ZIP_TOKEN_QUERY = """
query ($companyId: Int!, $fullPath: String!) {
  supplierReceiptGetZIPToken(companyId: $companyId, fullPath: $fullPath) {
    errors { field msg }
    data {
      token
      path
      filename
    }
  }
}
"""


@mcp.tool()
async def get_supplier_receipt_zip_token(company_id: int, full_path: str) -> Any:
    """Gera um token temporário e seguro para descarregar vários recibos de compra como um
    arquivo ZIP. Devolve `token`, `path` e `filename`, que se combinam para construir o URL
    de download. O `full_path` identifica o ZIP a descarregar (caminho devolvido por uma
    operação de exportação em lote).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        full_path: caminho completo do arquivo ZIP a descarregar.
    """
    variables = {"companyId": company_id, "fullPath": full_path}
    try:
        data = await _client.query(SUPPLIER_RECEIPT_ZIP_TOKEN_QUERY, variables)
        return unwrap(data, "supplierReceiptGetZIPToken")
    except MolonionError as e:
        return _err(e)


SUPPLIER_RECEIPT_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  supplierReceiptLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_supplier_receipt_logs(
    company_id: int,
    document_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) aos recibos de compra de uma empresa: criações,
    modificações e remoções. Cada entrada indica a operação (`operation`), os valores
    antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`, `email`)
    e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: opcional; filtra os logs de um recibo de compra específico (corresponde
            a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if document_id is not None:
        options["relatedId"] = document_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SUPPLIER_RECEIPT_LOGS_QUERY, variables)
        return unwrap(data, "supplierReceiptLogs")
    except MolonionError as e:
        return _err(e)


SUPPLIER_RECEIPT_MAIL_RECIPIENTS_QUERY = """
query ($companyId: Int!, $deliveryId: String!, $options: RecipientOptions) {
  supplierReceiptMailRecipients(companyId: $companyId, deliveryId: $deliveryId, options: $options) {
    errors { field msg }
    data {
      recipientId
      email
      name
      internalStatus
      status
      mailServiceResponseId
    }
  }
}
"""


@mcp.tool()
async def get_supplier_receipt_mail_recipients(
    company_id: int,
    delivery_id: str,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os destinatários de um envio por email de recibos de compra e o estado de
    entrega de cada um (`status`, `internalStatus`, `mailServiceResponseId`). Útil para
    confirmar a quem foi enviado o documento e se a entrega teve sucesso. Os logs detalhados
    de cada destinatário não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        delivery_id: ID do envio de email cujos destinatários se pretendem (obtém-se
            via `get_supplier_receipt_mails_history`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "deliveryId": delivery_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SUPPLIER_RECEIPT_MAIL_RECIPIENTS_QUERY, variables
        )
        return unwrap(data, "supplierReceiptMailRecipients")
    except MolonionError as e:
        return _err(e)


SUPPLIER_RECEIPT_MAILS_HISTORY_QUERY = """
query ($companyId: Int!, $documentId: Int!, $options: DocumentMailOptions) {
  supplierReceiptMailsHistory(companyId: $companyId, documentId: $documentId, options: $options) {
    errors { field msg }
    data {
      documentMailId
      email
      content
      deliveryId
      createdAt
    }
  }
}
"""


@mcp.tool()
async def get_supplier_receipt_mails_history(
    company_id: int,
    document_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista o histórico de envios por email de um recibo de compra: cada registo indica o
    email de destino, o conteúdo, o `deliveryId` (que liga aos destinatários via
    `get_supplier_receipt_mail_recipients`) e a data de envio (`createdAt`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_id: ID do documento (recibo de compra) cujos envios se pretendem.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "documentId": document_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(
            SUPPLIER_RECEIPT_MAILS_HISTORY_QUERY, variables
        )
        return unwrap(data, "supplierReceiptMailsHistory")
    except MolonionError as e:
        return _err(e)


SUPPLIER_RECEIPT_NEXT_NUMBER_QUERY = """
query ($companyId: Int!, $documentSetId: Int!) {
  supplierReceiptNextNumber(companyId: $companyId, documentSetId: $documentSetId) {
    errors { field msg }
    data {
      number
      name
    }
  }
}
"""


@mcp.tool()
async def get_supplier_receipt_next_number(
    company_id: int, document_set_id: int
) -> Any:
    """Obtém o próximo número disponível para um recibo de compra numa dada série de
    documentos. Devolve `number` (o próximo número) e `name` (o nome da série). Útil antes
    de criar um novo recibo de compra, para saber o número que lhe será atribuído.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        document_set_id: ID da série de documentos.
    """
    variables = {"companyId": company_id, "documentSetId": document_set_id}
    try:
        data = await _client.query(SUPPLIER_RECEIPT_NEXT_NUMBER_QUERY, variables)
        return unwrap(data, "supplierReceiptNextNumber")
    except MolonionError as e:
        return _err(e)


SUPPLIER_RECEIPT_RELATABLE_QUERY = """
query ($companyId: Int!, $entityId: Int!, $options: SupplierReceiptOptions) {
  supplierReceiptRelatable(companyId: $companyId, entityId: $entityId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      totalValue
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def get_supplier_receipt_relatable(
    company_id: int,
    entity_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os recibos de compra de uma entidade (fornecedor) que podem ser
    relacionados/ligados a outro documento.

    DEPRECATED na API Moloni ON — preferir `documentRelatable` com os fragments
    adequados. Mantida por cobertura; usa a alternativa em código novo.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        entity_id: ID da entidade (fornecedor) cujos recibos relacionáveis se procuram.
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id, "entityId": entity_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SUPPLIER_RECEIPT_RELATABLE_QUERY, variables)
        return unwrap(data, "supplierReceiptRelatable")
    except MolonionError as e:
        return _err(e)


SUPPLIER_RECEIPTS_QUERY = """
query ($companyId: Int!, $options: SupplierReceiptOptions) {
  supplierReceipts(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      documentId
      number
      date
      documentSetName
      entityName
      entityVat
      totalValue
      reconciledValue
      reconciliationPercentage
      status
      nullified
    }
  }
}
"""


@mcp.tool()
async def list_supplier_receipts(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) os recibos de compra de uma empresa, com os campos principais de cada
    um: número, data, série, entidade/fornecedor, valor total, valor reconciliado
    (`reconciledValue`, `reconciliationPercentage`) e estado. Para obter o detalhe completo
    de um recibo de compra usa `get_supplier_receipt`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SUPPLIER_RECEIPTS_QUERY, variables)
        return unwrap(data, "supplierReceipts")
    except MolonionError as e:
        return _err(e)


SUPPLIERS_QUERY = """
query ($companyId: Int!, $options: SupplierOptions) {
  suppliers(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      supplierId
      number
      name
      vat
      email
      phone
      city
      countryId
      creditLimit
      visible
    }
  }
}
"""


@mcp.tool()
async def list_suppliers(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) os fornecedores de uma empresa, cada um com `supplierId`, `number`,
    `name`, `vat`, contactos (`email`, `phone`, `city`), o país (`countryId`), o limite de
    crédito (`creditLimit`) e `visible`. Para o detalhe completo de um fornecedor usa
    `get_supplier`.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(SUPPLIERS_QUERY, variables)
        return unwrap(data, "suppliers")
    except MolonionError as e:
        return _err(e)


# ===========================================================================
# Impostos / taxas de IVA (Tax)
# ===========================================================================

TAX_QUERY = """
query ($companyId: Int!, $taxId: Int!) {
  tax(companyId: $companyId, taxId: $taxId) {
    errors { field msg }
    data {
      taxId
      name
      value
      type
      fiscalZone
      fiscalZoneFinanceType
      fiscalZoneFinanceTypeMode
      exemptionReason
      isDefault
      countryId
      visible
      deletable
    }
  }
}
"""


@mcp.tool()
async def get_tax(company_id: int, tax_id: int) -> Any:
    """Obtém os detalhes de uma taxa de imposto (IVA) pelo seu ID: o nome (`name`), o valor
    em percentagem (`value`), o tipo (`type`), a zona fiscal (`fiscalZone`,
    `fiscalZoneFinanceType`, `fiscalZoneFinanceTypeMode`), a razão de isenção
    (`exemptionReason`, quando o valor é 0), se é a taxa por omissão (`isDefault`) e o país
    (`countryId`). As taxas aplicam-se às linhas dos documentos. O país, a empresa e o regime
    especial de imposto (`specialTaxScheme`) não são incluídos neste selection set.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        tax_id: ID da taxa de imposto a obter.
    """
    variables = {"companyId": company_id, "taxId": tax_id}
    try:
        data = await _client.query(TAX_QUERY, variables)
        return unwrap(data, "tax")
    except MolonionError as e:
        return _err(e)


TAXES_QUERY = """
query ($companyId: Int!, $options: TaxOptions) {
  taxes(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      taxId
      name
      value
      type
      fiscalZone
      exemptionReason
      isDefault
      countryId
      visible
    }
  }
}
"""


@mcp.tool()
async def list_taxes(
    company_id: int,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista (paginada) as taxas de imposto (IVA) de uma empresa, cada uma com `taxId`,
    `name`, o valor em percentagem (`value`), o tipo (`type`), a zona fiscal (`fiscalZone`),
    a razão de isenção (`exemptionReason`), se é a taxa por omissão (`isDefault`) e o país
    (`countryId`). Útil para escolher a taxa a aplicar a uma linha de documento.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(TAXES_QUERY, variables)
        return unwrap(data, "taxes")
    except MolonionError as e:
        return _err(e)


TAXES_MAP_QUERY = """
query ($companyId: Int!, $options: TaxesMapOptions!) {
  taxesMap(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      group
      taxes {
        taxId
        name
        fiscalZone
        value
        type
        incidence
        total
        incidencePositive
        totalPositive
        incidenceNegative
        totalNegative
      }
    }
  }
}
"""


@mcp.tool()
async def get_taxes_map(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
) -> Any:
    """Obtém o mapa de impostos (IVA) de uma empresa: os valores de incidência (base
    tributável) e de imposto, agrupados. Cada grupo (`group`) traz a lista de `taxes`, e
    cada taxa tem `taxId`, `name`, `fiscalZone`, `value` (%), a incidência e o total
    (`incidence`/`total`) e a separação por movimentos positivos/negativos
    (`incidencePositive`/`totalPositive`/`incidenceNegative`/`totalNegative`). Útil para o
    apuramento de IVA.

    DEPRECATED na API Moloni ON — preferir `taxesMap2`. Mantida por cobertura.

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON — passa uma lista de dicionários
    (ver `get_sales_analysis_by_date`). O `options` é obrigatório nesta operação.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: lista de filtros `{field, comparison, value}` (ex. intervalo de datas).
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    variables = {"companyId": company_id, "options": options}
    try:
        data = await _client.query(TAXES_MAP_QUERY, variables)
        return unwrap(data, "taxesMap")
    except MolonionError as e:
        return _err(e)


TAXES_MAP2_QUERY = """
query ($companyId: Int!, $options: TaxesMapOptions!) {
  taxesMap2(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      group
      totals {
        incidence
        total
        incidencePositive
        totalPositive
        incidenceNegative
        totalNegative
      }
      taxes {
        taxId
        name
        fiscalZone
        value
        type
        incidence
        total
        incidencePositive
        totalPositive
        incidenceNegative
        totalNegative
      }
    }
  }
}
"""


@mcp.tool()
async def get_taxes_map2(
    company_id: int,
    filters: list[dict[str, Any]] | None = None,
) -> Any:
    """Obtém o mapa de impostos (IVA) de uma empresa — versão atual (substitui o
    `get_taxes_map`, deprecado). Por grupo (`group`) devolve os `totals` (incidência/base
    e total de imposto, com separação positivos/negativos) e a lista de `taxes`, cada uma
    com `taxId`, `name`, `fiscalZone`, `value` (%), incidência e total e os valores
    positivos/negativos. Útil para o apuramento de IVA.

    Os filtros (incluindo o intervalo de datas) usam a estrutura genérica
    `field`/`comparison`/`value` da Moloni ON — passa uma lista de dicionários
    (ver `get_sales_analysis_by_date`). O `options` é obrigatório nesta operação.

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        filters: lista de filtros `{field, comparison, value}` (ex. intervalo de datas).
    """
    options: dict[str, Any] = {}
    if filters:
        options["filter"] = filters
    variables = {"companyId": company_id, "options": options}
    try:
        data = await _client.query(TAXES_MAP2_QUERY, variables)
        return unwrap(data, "taxesMap2")
    except MolonionError as e:
        return _err(e)


TAX_LOGS_QUERY = """
query ($companyId: Int!, $options: LogOptions) {
  taxLogs(companyId: $companyId, options: $options) {
    errors { field msg }
    data {
      logId
      relatedId
      operation
      oldValues
      newValues
      userId
      username
      email
      operationTime
    }
  }
}
"""


@mcp.tool()
async def get_tax_logs(
    company_id: int,
    tax_id: int | None = None,
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Obtém o histórico de alterações (logs) às taxas de imposto de uma empresa: criações,
    modificações e remoções. Cada entrada indica a operação (`operation`), os valores
    antigos/novos (`oldValues`/`newValues`), quem a fez (`userId`, `username`, `email`)
    e quando (`operationTime`).

    Args:
        company_id: ID da empresa (obtém-se via `me`).
        tax_id: opcional; filtra os logs de uma taxa específica (corresponde a `relatedId`).
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if tax_id is not None:
        options["relatedId"] = tax_id
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {"companyId": company_id}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(TAX_LOGS_QUERY, variables)
        return unwrap(data, "taxLogs")
    except MolonionError as e:
        return _err(e)


# ===========================================================================
# Fusos horários (Timezone)
# ===========================================================================

TIMEZONE_QUERY = """
query ($timezoneId: Int!) {
  timezone(timezoneId: $timezoneId) {
    errors { field msg }
    data {
      timezoneId
      name
      tzName
      offset
      ordering
      visible
    }
  }
}
"""


@mcp.tool()
async def get_timezone(timezone_id: int) -> Any:
    """Obtém um fuso horário (tabela de referência global da Moloni ON) pelo seu ID: o nome
    (`name`), o identificador IANA (`tzName`, ex. "Europe/Lisbon") e o desvio UTC em minutos
    (`offset`). Nota: ao contrário da maioria das operações, NÃO recebe `companyId` — é uma
    tabela global. O país associado não é incluído neste selection set.

    Args:
        timezone_id: ID do fuso horário a obter.
    """
    variables = {"timezoneId": timezone_id}
    try:
        data = await _client.query(TIMEZONE_QUERY, variables)
        return unwrap(data, "timezone")
    except MolonionError as e:
        return _err(e)


TIMEZONES_QUERY = """
query ($options: TimezoneOptions) {
  timezones(options: $options) {
    errors { field msg }
    data {
      timezoneId
      name
      tzName
      offset
      ordering
      visible
    }
  }
}
"""


@mcp.tool()
async def list_timezones(
    page: int | None = None,
    qty: int | None = None,
) -> Any:
    """Lista os fusos horários (tabela de referência global da Moloni ON), cada um com
    `timezoneId`, o nome (`name`), o identificador IANA (`tzName`) e o desvio UTC em minutos
    (`offset`). Nota: ao contrário da maioria das operações, NÃO recebe `companyId` — é uma
    tabela global.

    Args:
        page: opcional; página da paginação (começa em 1). Requer também `qty`.
        qty: opcional; número de registos por página. Requer também `page`.
    """
    options: dict[str, Any] = {}
    if page is not None and qty is not None:
        options["pagination"] = {"page": page, "qty": qty}
    variables: dict[str, Any] = {}
    if options:
        variables["options"] = options
    try:
        data = await _client.query(TIMEZONES_QUERY, variables)
        return unwrap(data, "timezones")
    except MolonionError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# As tools por operação são adicionadas aqui, uma a uma, a partir dos links de
# https://docs.molonion.pt/reference (ver CLAUDE.md para o padrão).
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    mcp.run()  # transport stdio por omissão