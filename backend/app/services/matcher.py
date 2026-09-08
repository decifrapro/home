"""Associação entre o anexo citado no TXT e o arquivo físico do ZIP.

Regra: é melhor mostrar "arquivo não associado" do que colocar o conteúdo de
uma mídia dentro da mensagem errada. Por isso não existe associação aproximada
agressiva aqui — só correspondências que dão certeza.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from app.models.schemas import CatalogFile
from app.parsers.whatsapp import strip_invisible


def _basename(name: str) -> str:
    return name.replace("\\", "/").rsplit("/", 1)[-1]


def _nfc(name: str) -> str:
    return unicodedata.normalize("NFC", name)


def _conservative(name: str) -> str:
    """Espaços colapsados e marcas invisíveis fora — sem mexer em letras."""
    return " ".join(strip_invisible(_nfc(name)).split())


def _casefold(name: str) -> str:
    return _conservative(name).casefold()


@dataclass
class MatchOutcome:
    file: CatalogFile | None
    strategy: str | None
    ambiguous: bool = False


class AttachmentMatcher:
    """Índices de busca construídos uma vez por job, do mais estrito ao mais tolerante."""

    STRATEGIES = ("exact", "basename_nfc", "conservative", "casefold")

    def __init__(self, files: list[CatalogFile]) -> None:
        self._files = files
        self._used: set[str] = set()
        self._index: dict[str, dict[str, list[CatalogFile]]] = {
            strategy: {} for strategy in self.STRATEGIES
        }
        for item in files:
            original = item.original_name or item.name
            self._add("exact", item.original_path or item.relative_path, item)
            self._add("exact", original, item)
            self._add("basename_nfc", _nfc(_basename(original)), item)
            self._add("conservative", _conservative(_basename(original)), item)
            self._add("casefold", _casefold(_basename(original)), item)

    def _add(self, strategy: str, key: str, item: CatalogFile) -> None:
        if not key:
            return
        self._index[strategy].setdefault(key, []).append(item)

    def _lookup(self, strategy: str, key: str) -> list[CatalogFile]:
        return self._index[strategy].get(key, [])

    def match(self, attachment_name: str) -> MatchOutcome:
        raw = attachment_name.strip()
        if not raw:
            return MatchOutcome(None, None)

        probes = {
            "exact": [raw, _basename(raw)],
            "basename_nfc": [_nfc(_basename(raw))],
            "conservative": [_conservative(_basename(raw))],
            "casefold": [_casefold(_basename(raw))],
        }

        for strategy in self.STRATEGIES:
            for probe in probes[strategy]:
                candidates = self._lookup(strategy, probe)
                if not candidates:
                    continue
                unique_paths = {item.relative_path for item in candidates}
                if len(unique_paths) > 1:
                    # Dois arquivos diferentes com o mesmo nome: sem certeza, não associa.
                    return MatchOutcome(None, strategy, ambiguous=True)
                chosen = next(
                    (item for item in candidates if item.relative_path not in self._used),
                    candidates[0],
                )
                self._used.add(chosen.relative_path)
                return MatchOutcome(chosen, strategy)
        return MatchOutcome(None, None)

    @property
    def used_paths(self) -> set[str]:
        return set(self._used)

    def orphans(self, main_txt_path: str | None = None) -> list[CatalogFile]:
        """Arquivos presentes no ZIP que nenhum evento citou."""
        return [
            item
            for item in self._files
            if item.relative_path not in self._used and item.relative_path != main_txt_path
        ]
