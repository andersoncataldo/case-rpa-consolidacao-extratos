"""Testes unitários das regras de validação, reconciliação e duplicidade."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from rpa_extratos.config import AppConfig
from rpa_extratos.modelos import Movimento, ResultadoExtracao
from rpa_extratos.validacao import validar_lote


def _resultado_base(
    arquivo: str,
    *,
    hash_sha256: str = "hash_unico",
    periodo: str = "2026-10",
    conta: str = "12345-6",
    saldo_inicial: Decimal = Decimal("100.00"),
    saldo_final: Decimal = Decimal("150.00"),
) -> ResultadoExtracao:
    return ResultadoExtracao(
        arquivo=arquivo,
        caminho=Path("entrada") / arquivo,
        hash_sha256=hash_sha256,
        formato="PDF",
        banco="Banco Planalto",
        conta=conta,
        periodo=periodo,
        saldo_inicial=saldo_inicial,
        saldo_final=saldo_final,
        movimentos=[
            Movimento("05/10/2026", "PIX RECEBIDO", Decimal("50.00"), Decimal("150.00")),
        ],
    )


def test_precedencia_status() -> None:
    r = _resultado_base("teste.pdf")
    r.adicionar_observacao("ok", "Nota informativa")
    assert r.status == "ok"
    r.adicionar_observacao("revisar", "Alerta de período")
    assert r.status == "revisar"
    r.adicionar_observacao("falhou", "Erro fatal")
    assert r.status == "falhou"
    r.adicionar_observacao("ok", "Não deve rebaixar")
    assert r.status == "falhou"


def test_duplicidade_por_hash_marca_copia_como_revisar() -> None:
    orig = _resultado_base("EXT_LagoaAzul.pdf", hash_sha256="abc123")
    copia = _resultado_base("EXT_LagoaAzul (1).pdf", hash_sha256="abc123")
    meta = validar_lote([copia, orig], AppConfig())

    assert orig.status == "ok"
    assert orig.observacoes == []
    assert copia.status == "revisar"
    assert "duplicata" in copia.observacao_texto.lower()
    assert orig.arquivo in copia.observacao_texto
    assert len(meta["duplicidades"]) == 1  # type: ignore[arg-type]


def test_periodo_fora_da_moda_e_conta_fora_do_padrao() -> None:
    a = _resultado_base("a.pdf", hash_sha256="h1", periodo="2026-10")
    b = _resultado_base("b.pdf", hash_sha256="h2", periodo="2026-10")
    fora = _resultado_base("c.png", hash_sha256="h3", periodo="2026-09", conta="9913355-2")

    meta = validar_lote([a, b, fora], AppConfig())
    assert meta["periodo_lote"] == "2026-10"
    assert fora.status == "revisar"
    assert "2026-09" in fora.observacao_texto
    assert "9913355-2" in fora.observacao_texto


def test_reconciliacao_detecta_divergencia_em_centavos() -> None:
    r = _resultado_base(
        "sol.pdf",
        saldo_inicial=Decimal("100.00"),
        saldo_final=Decimal("1180.00"),
    )
    r.movimentos = [
        Movimento("05/10/2026", "CREDITO", Decimal("50.00"), Decimal("150.00")),
        Movimento("10/10/2026", "DEBITO", Decimal("-50.00"), Decimal("100.00")),
    ]
    validar_lote([r], AppConfig())
    assert r.status == "revisar"
    assert "1.080,00" in r.observacao_texto


def test_saldo_negativo_intradia_com_pagamento_atipico_mantem_ok() -> None:
    r = _resultado_base(
        "cajueiro.xlsx",
        saldo_inicial=Decimal("1000.00"),
        saldo_final=Decimal("500.00"),
    )
    r.movimentos = [
        Movimento("01/10/2026", "PAGTO FORNECEDOR - INVERSORES", Decimal("-2000.00"), Decimal("-1000.00")),
        Movimento("02/10/2026", "PIX A", Decimal("100.00"), Decimal("-900.00")),
        Movimento("03/10/2026", "PIX B", Decimal("100.00"), Decimal("-800.00")),
        Movimento("04/10/2026", "PIX C", Decimal("100.00"), Decimal("-700.00")),
        Movimento("05/10/2026", "BOLETOS", Decimal("1200.00"), Decimal("500.00")),
    ]
    validar_lote([r], AppConfig())
    assert r.status == "ok"
    assert "negativo" in r.observacao_texto.lower()
    assert "atípico" in r.observacao_texto.lower()


def test_nao_extrato_vira_falhou() -> None:
    r = ResultadoExtracao(
        arquivo="aviso.pdf",
        caminho=Path("entrada/aviso.pdf"),
        hash_sha256="h_aviso",
        formato="PDF",
        nao_e_extrato=True,
    )
    validar_lote([r], AppConfig())
    assert r.status == "falhou"
    assert "não é um extrato bancário" in r.observacao_texto.lower()
