"""Conversão de nomes de campo para o formato que a API e os exports usam."""

from __future__ import annotations

from typing import Any


def to_camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


def camelize(data: Any) -> Any:
    """Converte recursivamente as chaves de dicionários para camelCase."""
    if isinstance(data, dict):
        return {to_camel(str(key)): camelize(value) for key, value in data.items()}
    if isinstance(data, list):
        return [camelize(item) for item in data]
    return data
