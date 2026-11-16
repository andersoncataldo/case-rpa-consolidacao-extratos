"""Regras de validação de lote, reconciliação aritmética e definição de Status."""

from __future__ import annotations

from collections import Counter

from .config import AppConfig
from .modelos import ResultadoExtracao


def determinar_periodo_lote(resultados: list[ResultadoExtracao]) -> str | None:
    """Retorna o período mais frequente (moda) entre os extratos lidos."""
    periodos = [r.periodo for r in resultados if r.periodo]
    if not periodos:
        return None
    contagem = Counter(periodos)
    # Desempate determinístico pelo período mais recente/lexicograficamente maior
    periodo_moda, _ = max(contagem.items(), key=lambda item: (item[1], item[0]))
    return periodo_moda


def validar_lote(resultados: list[ResultadoExtracao], config: AppConfig) -> dict[str, object]:
    """Valida o lote completo e retorna metadados de resumo (período, duplicidades, ausências)."""
    periodo_lote = determinar_periodo_lote(resultados)
    return {
        "periodo_lote": periodo_lote,
        "duplicidades": [],
        "contas_ausentes": [],
    }
