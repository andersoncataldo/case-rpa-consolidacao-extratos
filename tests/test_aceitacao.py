"""Testes de aceitação ponta a ponta contra tests/gabarito.csv."""

from __future__ import annotations

import csv
import os
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from dotenv import load_dotenv

from rpa_extratos.__main__ import executar_pipeline
from rpa_extratos.config import carregar_config

RAIZ = Path(__file__).resolve().parent.parent
GABARITO_PATH = RAIZ / "tests" / "gabarito.csv"
ENTRADA_DIR = RAIZ / "entrada"


def _carregar_gabarito() -> list[dict[str, str]]:
    with GABARITO_PATH.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _ler_linhas_planilha(planilha: Path) -> dict[str, dict[str, object]]:
    wb = openpyxl.load_workbook(planilha)
    try:
        ws = wb["Consolidado"]
        linhas: dict[str, dict[str, object]] = {}
        for row in ws.iter_rows(min_row=2, values_only=True):
            arquivo = row[0]
            if not arquivo:
                continue
            linhas[str(arquivo)] = {
                "arquivo": str(arquivo),
                "banco": str(row[1] or ""),
                "conta": str(row[2] or ""),
                "periodo": str(row[3] or ""),
                "saldo_final": Decimal(f"{row[4]:.2f}") if row[4] is not None else None,
                "formato": str(row[5] or ""),
                "status": str(row[6] or ""),
                "observacao": str(row[7] or ""),
            }
        return linhas
    finally:
        wb.close()


def _validar_linha_contra_gabarito(esp: dict[str, str], obt: dict[str, object]) -> None:
    assert obt["banco"] == esp["banco"], f"{esp['arquivo']}: banco divergente"
    assert obt["conta"] == esp["conta"], f"{esp['arquivo']}: conta divergente"
    assert obt["periodo"] == esp["periodo"], f"{esp['arquivo']}: período divergente"
    esp_saldo = Decimal(esp["saldo_final"]) if esp["saldo_final"] else None
    assert obt["saldo_final"] == esp_saldo, f"{esp['arquivo']}: saldo divergente"
    assert obt["formato"] == esp["formato"], f"{esp['arquivo']}: formato divergente"
    assert obt["status"] == esp["status"], f"{esp['arquivo']}: status divergente ({obt['observacao']})"


def test_aceitacao_deterministica_pdf_e_excel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Valida os 12 arquivos PDF e Excel contra o gabarito e garante 17 linhas sem derrubar o lote."""
    if not ENTRADA_DIR.exists():
        pytest.skip("Pasta entrada/ não encontrada; rode scripts/preparar_entrada.py")

    # Garante execução isolada sem depender de chamada de IA neste teste determinístico
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    cfg = carregar_config(RAIZ / "config.yaml")
    cfg.modelo_planilha = RAIZ / "modelo" / "modelo_consolidado_extratos.xlsx"

    saida_dir = tmp_path / "saida"
    logs_dir = tmp_path / "logs"
    resultados, planilha, log_path, json_path = executar_pipeline(ENTRADA_DIR, saida_dir, logs_dir, cfg)

    assert len(resultados) == 17
    assert planilha.exists()
    assert log_path.exists()
    assert json_path.exists()

    linhas = _ler_linhas_planilha(planilha)
    assert len(linhas) == 17

    gabarito = _carregar_gabarito()
    for esp in gabarito:
        arq = esp["arquivo"]
        assert arq in linhas
        obt = linhas[arq]
        if esp["formato"] in {"PDF", "Excel"}:
            _validar_linha_contra_gabarito(esp, obt)
            obs = str(obt["observacao"]).lower()
            if esp["status"] in {"revisar", "falhou"}:
                assert obs != "", f"{arq} deveria ter Observação"
            elif arq == "cajueiro_solar_extrato_10-2026.xlsx":
                assert "negativo" in obs
            else:
                assert obs == "", f"{arq} não deveria ter falso alarme: {obs}"
        else:
            # Sem chave de API, PNGs devem virar 'falhou' com observação clara, sem quebrar o lote
            assert obt["formato"] == "Imagem"
            assert obt["status"] == "falhou"
            assert "gemini_api_key" in str(obt["observacao"]).lower()

    assert "duplicata" in str(linhas["EXT_102026_LagoaAzul (1).pdf"]["observacao"]).lower()
    assert "1.080,00" in str(linhas["extrato_sol_do_sertao_I_out2026.pdf"]["observacao"])
    assert "não é um extrato" in str(linhas["aviso_agencia_horizonte.pdf"]["observacao"]).lower()


@pytest.mark.gemini
def test_aceitacao_completa_17_arquivos_com_gemini(tmp_path: Path) -> None:
    """Valida todos os 17 arquivos (incluindo os 5 PNGs via Gemini API real) contra o gabarito."""
    load_dotenv(RAIZ / ".env")
    if not os.getenv("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY não configurada para o teste ao vivo com Gemini")
    if not ENTRADA_DIR.exists():
        pytest.skip("Pasta entrada/ não encontrada; rode scripts/preparar_entrada.py")

    cfg = carregar_config(RAIZ / "config.yaml")
    cfg.modelo_planilha = RAIZ / "modelo" / "modelo_consolidado_extratos.xlsx"

    saida_dir = tmp_path / "saida"
    logs_dir = tmp_path / "logs"
    resultados, planilha, _, _ = executar_pipeline(ENTRADA_DIR, saida_dir, logs_dir, cfg)

    assert len(resultados) == 17
    linhas = _ler_linhas_planilha(planilha)
    assert len(linhas) == 17

    gabarito = _carregar_gabarito()
    for esp in gabarito:
        arq = esp["arquivo"]
        obt = linhas[arq]
        _validar_linha_contra_gabarito(esp, obt)
        obs = str(obt["observacao"]).lower()
        if esp["status"] in {"revisar", "falhou"}:
            assert obs != "", f"{arq} deveria ter Observação"
        elif arq == "cajueiro_solar_extrato_10-2026.xlsx":
            assert "negativo" in obs
        else:
            assert obs == "", f"{arq} deveria ter Observação vazia, obteve: {obs}"

    contagem = {s: sum(1 for r in resultados if r.status == s) for s in ("ok", "revisar", "falhou")}
    assert contagem == {"ok": 13, "revisar": 3, "falhou": 1}
