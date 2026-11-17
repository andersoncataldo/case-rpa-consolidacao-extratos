"""Testes do motor instrumentado e do painel Streamlit (modo Demonstração)."""

from __future__ import annotations

import csv
import sys
from decimal import Decimal
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ / "app") not in sys.path:
    sys.path.insert(0, str(RAIZ / "app"))

import motor  # noqa: E402


def _carregar_gabarito() -> list[dict[str, str]]:
    with (RAIZ / "tests" / "gabarito.csv").open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_motor_demo_sem_chave_bate_100_porcento_com_gabarito(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Garante que o modo Demonstração funciona sem GEMINI_API_KEY e bate com todos os 17 arquivos do gabarito."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    eventos: list[tuple[str, str]] = []
    entrada = motor.garantir_entrada_case()
    ex = motor.executar(
        entrada,
        tmp_path,
        modo="demo",
        origem="case",
        api_key=None,
        ritmo_s=0.0,
        on_evento=lambda etapa, msg, _d: eventos.append((etapa, msg)),
    )

    assert len(ex.arquivos) == 17
    assert ex.planilha.exists()
    assert ex.log_path.exists()
    assert ex.json_path.exists()
    assert {e for e, _ in eventos} == {"descoberta", "classificacao", "extracao", "validacao", "consolidacao"}

    por_nome = {a.nome: a.resultado for a in ex.arquivos if a.resultado is not None}
    for esp in _carregar_gabarito():
        arq = esp["arquivo"]
        obt = por_nome[arq]
        assert (obt.banco or "") == esp["banco"], f"{arq}: banco divergente"
        assert (obt.conta or "") == esp["conta"], f"{arq}: conta divergente"
        assert (obt.periodo or "") == esp["periodo"], f"{arq}: período divergente"
        esp_saldo = Decimal(esp["saldo_final"]) if esp["saldo_final"] else None
        assert obt.saldo_final == esp_saldo, f"{arq}: saldo divergente"
        assert obt.formato == esp["formato"], f"{arq}: formato divergente"
        assert obt.status == esp["status"], f"{arq}: status divergente ({obt.observacao_texto})"


def test_streamlit_app_executa_fluxo_completo_sem_excecoes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Executa o painel Streamlit em modo headless e verifica todos os arquivos no rastreio."""
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    at = AppTest.from_file(str(RAIZ / "app" / "streamlit_app.py"), default_timeout=120)
    at.run()
    assert not at.exception

    at.sidebar.select_slider[0].set_value("Instantâneo")
    at.sidebar.button[0].click().run()
    assert not at.exception

    metricas = {m.label: m.value for m in at.metric}
    assert metricas.get("Arquivos") == "17"
    assert metricas.get("✅ OK") == "13"
    assert metricas.get("⚠️ Revisar") == "3"
    assert metricas.get("❌ Falhou") == "1"

    seletor = at.selectbox[0]
    for nome in (
        "app_ipe_amarelo_1011.png",
        "aviso_agencia_horizonte.pdf",
        "cajueiro_solar_extrato_10-2026.xlsx",
        "extrato_sol_do_sertao_I_out2026.pdf",
        "JANDAIRA_extrato_outubro.xlsx",
    ):
        seletor.set_value(nome).run()
        assert not at.exception, f"Exceção ao inspecionar {nome}: {[e.value for e in at.exception]}"
