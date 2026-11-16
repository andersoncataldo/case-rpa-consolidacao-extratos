"""Testes unitários das rotinas de normalização."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from rpa_extratos.normalizacao import (
    formatar_moeda_br,
    normalizar_banco,
    normalizar_conta,
    normalizar_periodo,
    parse_valor,
)


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("1.234,56", Decimal("1234.56")),
        ("298.409,32 C", Decimal("298409.32")),
        ("17.464,49 D", Decimal("-17464.49")),
        ("1,234.56", Decimal("1234.56")),
        ("-1.234,56", Decimal("-1234.56")),
        ("−234,50", Decimal("-234.50")),
        ("(1.234,56)", Decimal("-1234.56")),
        ("R$ 45,00", Decimal("45.00")),
        ("R$ -987,65", Decimal("-987.65")),
        (87431.17999999999, Decimal("87431.18")),
        (100, Decimal("100")),
        ("", None),
        (None, None),
        ("sem valor", None),
    ],
)
def test_parse_valor(entrada: object, esperado: Decimal | None) -> None:
    assert parse_valor(entrada) == esperado


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("BANCO PLANALTO", "Banco Planalto"),
        ("banco   do   brasil", "Banco do Brasil"),
        ("BANCO LITORAL", "Banco Litoral"),
        ("  Banco Aurora ", "Banco Aurora"),
        ("", None),
        (None, None),
    ],
)
def test_normalizar_banco(entrada: str | None, esperado: str | None) -> None:
    assert normalizar_banco(entrada) == esperado


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Conta: 69294-8", "69294-8"),
        ("Conta 00123-4", "00123-4"),
        ("9913355-2", "9913355-2"),
        ("  C/C: 00045-9 ", "00045-9"),
        (None, None),
    ],
)
def test_normalizar_conta(entrada: str | None, esperado: str | None) -> None:
    assert normalizar_conta(entrada) == esperado


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("01/10/2026 a 31/10/2026", "2026-10"),
        ("01/09/2026 a 30/09/2026", "2026-09"),
        ("2026-10", "2026-10"),
        ("10/2026", "2026-10"),
        ("01 set a 30 set 2026", "2026-09"),
        ("outubro 2026", "2026-10"),
        (datetime(2026, 10, 31), "2026-10"),
        ("", None),
        (None, None),
    ],
)
def test_normalizar_periodo(entrada: object, esperado: str | None) -> None:
    assert normalizar_periodo(entrada) == esperado


def test_formatar_moeda_br() -> None:
    assert formatar_moeda_br(Decimal("1080.00")) == "1.080,00"
    assert formatar_moeda_br(Decimal("-46643.80")) == "-46.643,80"
