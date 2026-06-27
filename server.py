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
# As tools por operação são adicionadas aqui, uma a uma, a partir dos links de
# https://docs.molonion.pt/reference (ver CLAUDE.md para o padrão).
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    mcp.run()  # transport stdio por omissão