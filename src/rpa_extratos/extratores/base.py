"""Interface comum para os extratores de extratos bancários."""

from __future__ import annotations

from typing import Protocol

from ..classificador import TipoDocumento
from ..config import AppConfig
from ..descoberta import ArquivoDescoberto
from ..modelos import ResultadoExtracao


class ExtratorBase(Protocol):
    """Contrato comum para extratores determinísticos e de visão."""

    def extrair(
        self,
        arquivo: ArquivoDescoberto,
        tipo: TipoDocumento,
        config: AppConfig,
    ) -> ResultadoExtracao:
        """Extrai cabeçalho, movimentos e saldo final do documento."""
        ...
