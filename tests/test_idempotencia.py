"""Teste de idempotência: duas execuções consecutivas produzem a mesma planilha."""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from rpa_extratos.__main__ import executar_pipeline
from rpa_extratos.config import carregar_config

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA_DIR = RAIZ / "entrada"


def _snapshot_workbook(caminho: Path) -> dict[str, list[list[tuple[object, str, str | None]]]]:
    wb = openpyxl.load_workbook(caminho)
    try:
        dados: dict[str, list[list[tuple[object, str, str | None]]]] = {}
        for aba in wb.sheetnames:
            ws = wb[aba]
            linhas = []
            for row in ws.iter_rows():
                linhas.append(
                    [
                        (cell.value, cell.number_format, cell.fill.start_color.rgb if cell.fill else None)
                        for cell in row
                    ]
                )
            dados[aba] = linhas
        return dados
    finally:
        wb.close()


def test_execucoes_consecutivas_sao_idempotentes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not ENTRADA_DIR.exists():
        pytest.skip("Pasta entrada/ não encontrada")

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    cfg = carregar_config(RAIZ / "config.yaml")
    cfg.modelo_planilha = RAIZ / "modelo" / "modelo_consolidado_extratos.xlsx"

    _, planilha_1, _, _ = executar_pipeline(ENTRADA_DIR, tmp_path / "saida1", tmp_path / "logs1", cfg)
    _, planilha_2, _, _ = executar_pipeline(ENTRADA_DIR, tmp_path / "saida2", tmp_path / "logs2", cfg)

    assert planilha_1.name == planilha_2.name
    assert _snapshot_workbook(planilha_1) == _snapshot_workbook(planilha_2)
