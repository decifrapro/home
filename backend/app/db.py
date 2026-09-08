"""Porta de entrada da guarda de dados.

O resto do programa chama `db.get_job(...)`, `db.update_event(...)` e não
precisa saber onde as coisas estão guardadas. Quem decide é a configuração:

- sem Supabase configurado  → SQLite no disco (servidor próprio, Docker, testes);
- com Supabase configurado  → banco do Supabase (Vercel, sem disco).

Os dois módulos têm exatamente as mesmas funções.
"""

from __future__ import annotations

import logging

from app import config
from app.repositorios import sqlite as _sqlite

logger = logging.getLogger(__name__)

_supabase = None


def _modulo():
    """Módulo que está valendo agora — decidido pela configuração, a cada chamada.

    Ser decidido na hora (e não na importação) permite trocar de modo dentro de
    um mesmo processo, o que os testes usam para exercitar os dois caminhos.
    """
    global _supabase
    if config.settings.storage_mode == "supabase":
        if _supabase is None:
            from app.repositorios import supabase as modulo

            _supabase = modulo
        return _supabase
    return _sqlite


# As funções disponíveis são as mesmas dos dois repositórios: create_job,
# update_job, get_job, list_jobs, delete_job, jobs_in_status, expired_jobs,
# replace_events, get_events, get_event, update_event, lease_event, lease_link,
# release_stale_leases, replace_links, get_links, update_link, replace_files,
# get_files, merge_job_metadata, count_events_by_status, connect e
# reset_connection.
def __getattr__(nome: str):
    """Encaminha `db.qualquer_funcao` para o repositório que está valendo."""
    if nome == "backend":
        return config.settings.storage_mode
    try:
        return getattr(_modulo(), nome)
    except AttributeError as exc:
        raise AttributeError(f"module 'app.db' has no attribute {nome!r}") from exc


