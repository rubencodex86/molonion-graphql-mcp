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
# As tools por operação são adicionadas aqui, uma a uma, a partir dos links de
# https://docs.molonion.pt/reference (ver CLAUDE.md para o padrão).
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    mcp.run()  # transport stdio por omissão