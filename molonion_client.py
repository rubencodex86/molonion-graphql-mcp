"""Cliente GraphQL da Moloni ON.

A API tem um único endpoint (POST https://api.molonion.pt/v1) e autentica por
Bearer token (uma API Key de serviço). Cada operação devolve um envelope próprio
`{ errors { field msg }, data { ... } }` — ver `unwrap()`.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_URL = "https://api.molonion.pt/v1"


class MolonionError(Exception):
    """Erro de transporte (HTTP), de GraphQL (top-level) ou de operação (envelope)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        errors: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.errors = errors or []


class MolonionClient:
    """Cliente assíncrono mínimo sobre httpx. Lê config do ambiente."""

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.url = url or os.getenv("MOLONION_API_URL", DEFAULT_URL)
        self.api_key = api_key if api_key is not None else os.getenv("MOLONION_API_KEY", "")
        self.timeout = timeout

    @property
    def headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Executa uma query/mutation e devolve o objeto `data` (por nome de operação).

        Levanta MolonionError em erro HTTP ou em erros GraphQL de topo. Os erros ao
        nível da operação (envelope `{errors, data}`) são tratados por `unwrap()`.
        """
        if not self.api_key:
            raise MolonionError(
                "MOLONION_API_KEY não está definida. Configura o .env "
                "(Conta → API → API Keys na Moloni ON)."
            )

        payload = {"query": query, "variables": variables or {}}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.url, json=payload, headers=self.headers)

        if resp.status_code >= 400:
            raise MolonionError(
                f"HTTP {resp.status_code} ao chamar a API Moloni ON.",
                status_code=resp.status_code,
                errors=_safe_json(resp),
            )

        body = resp.json()
        if body.get("errors"):
            # Erros GraphQL de topo (sintaxe, auth, etc.) — não confundir com o
            # envelope de operação.
            raise MolonionError(
                "A API devolveu erros GraphQL de topo.",
                status_code=resp.status_code,
                errors=body["errors"],
            )
        return body.get("data") or {}


def unwrap(data: dict[str, Any], operation: str) -> Any:
    """Desembrulha o envelope `{ errors, data }` de uma operação Moloni ON.

    Devolve o `data` interno da operação. Levanta MolonionError se a operação
    reportar erros (atenção: estes vêm com HTTP 200, no array `errors`).
    """
    node = (data or {}).get(operation) or {}
    op_errors = node.get("errors")
    if op_errors:
        raise MolonionError(
            f"A operação '{operation}' devolveu erros.",
            errors=op_errors,
        )
    return node.get("data")


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return resp.text[:1000]