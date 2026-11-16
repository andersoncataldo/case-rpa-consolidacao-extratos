"""Funções de normalização de valores monetários, bancos, contas e períodos."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

MESES_PT: dict[str, int] = {
    "jan": 1,
    "janeiro": 1,
    "fev": 2,
    "fevereiro": 2,
    "mar": 3,
    "marco": 3,
    "abr": 4,
    "abril": 4,
    "mai": 5,
    "maio": 5,
    "jun": 6,
    "junho": 6,
    "jul": 7,
    "julho": 7,
    "ago": 8,
    "agosto": 8,
    "set": 9,
    "setembro": 9,
    "out": 10,
    "outubro": 10,
    "nov": 11,
    "novembro": 11,
    "dez": 12,
    "dezembro": 12,
}

PREPOSICOES_MINUSCULA = {"da", "das", "de", "do", "dos", "e"}


def remover_acentos(texto: str) -> str:
    """Remove acentos mantendo apenas caracteres ASCII equivalentes."""
    norm = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in norm if not unicodedata.combining(c))


def parse_valor(val: Any) -> Decimal | None:
    """Converte strings BR/US, números e sufixos C/D/parênteses em ``Decimal``."""
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, Decimal):
        return val
    if isinstance(val, int):
        return Decimal(val)
    if isinstance(val, float):
        return Decimal(f"{val:.2f}")

    s = str(val).strip()
    if not s:
        return None

    # Normaliza sinal menos Unicode (U+2212, U+2013) para '-'
    s = s.replace("\u2212", "-").replace("\u2013", "-")
    s = re.sub(r"R\$|\s+", "", s, flags=re.IGNORECASE)
    if not s:
        return None

    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    if s.startswith("-"):
        neg = True
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]

    ultimo = s[-1:].upper()
    if ultimo == "D":
        neg = True
        s = s[:-1]
    elif ultimo == "C":
        s = s[:-1]

    # Caso tenha sobrado sinal após remover C/D ou R$
    if s.startswith("-"):
        neg = True
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]

    if not s or not re.search(r"\d", s):
        return None

    # Se contiver apenas dígitos, pontos e vírgulas
    if not re.fullmatch(r"[\d.,]+", s):
        return None

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            # Formato BR: 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:
            # Formato US: 1,234.56
            s = s.replace(",", "")
    elif "," in s:
        partes = s.split(",")
        if len(partes) == 2 and len(partes[1]) <= 2:
            s = s.replace(",", ".")
        elif all(len(p) == 3 for p in partes[1:]):
            # Separador de milhar US sem decimais: 1,234
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif "." in s:
        partes = s.split(".")
        if len(partes) > 2 or (len(partes) == 2 and len(partes[1]) == 3 and len(partes[0]) <= 3):
            # Separador de milhar BR sem decimais: 1.234 ou 1.234.567
            if len(partes) > 2:
                s = s.replace(".", "")

    try:
        resultado = Decimal(s)
    except InvalidOperation:
        return None

    if neg and resultado != Decimal("0"):
        resultado = -resultado
    return resultado


def normalizar_banco(nome: str | None) -> str | None:
    """Normaliza o nome do banco para Title Case preservando preposições."""
    if not nome:
        return None
    limpo = re.sub(r"\s+", " ", nome).strip()
    if not limpo:
        return None
    palavras = limpo.split(" ")
    saida: list[str] = []
    for i, palavra in enumerate(palavras):
        low = palavra.lower()
        if i > 0 and low in PREPOSICOES_MINUSCULA:
            saida.append(low)
        else:
            saida.append(low.capitalize())
    return " ".join(saida)


def normalizar_conta(conta: str | None) -> str | None:
    """Remove prefixos comuns da conta mantendo dígitos, zeros à esquerda e hífen."""
    if not conta:
        return None
    limpo = re.sub(r"^(?:conta(?:\s*corrente)?|c/c)\s*:?\s*", "", str(conta).strip(), flags=re.IGNORECASE)
    limpo = limpo.strip()
    if not limpo:
        return None
    m = re.search(r"(\d+(?:-\d+)?)", limpo)
    return m.group(1) if m else limpo


def normalizar_periodo(texto: Any) -> str | None:
    """Converte diversas representações de data/intervalo para ``AAAA-MM``."""
    if texto is None:
        return None
    if isinstance(texto, (datetime, date)):
        return f"{texto.year:04d}-{texto.month:02d}"

    s = re.sub(r"\s+", " ", str(texto).strip())
    if not s:
        return None

    # Já no formato AAAA-MM ou AAAA/MM
    m = re.fullmatch(r"(20\d{2})[-/](\d{1,2})", s)
    if m:
        mes = int(m.group(2))
        if 1 <= mes <= 12:
            return f"{int(m.group(1)):04d}-{mes:02d}"

    # Data ISO completa AAAA-MM-DD
    m = re.search(r"\b(20\d{2})-(\d{2})-\d{2}\b", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"

    # Intervalos ou datas DD/MM/AAAA (pega a última data ou a data de referência)
    datas_br = re.findall(r"(\d{2})/(\d{2})/(20\d{2})", s)
    if datas_br:
        _, mes_str, ano_str = datas_br[-1]
        mes = int(mes_str)
        if 1 <= mes <= 12:
            return f"{ano_str}-{mes:02d}"

    # MM/AAAA ou MM-AAAA
    m = re.search(r"\b(\d{1,2})[-/](20\d{2})\b", s)
    if m:
        mes = int(m.group(1))
        if 1 <= mes <= 12:
            return f"{m.group(2)}-{mes:02d}"

    # Mês por extenso ou abreviado com ano (ex.: "outubro de 2025", "01 set a 30 set 2025", "out/2025")
    sem_acento = remover_acentos(s.lower())
    m_ano = re.search(r"\b(20\d{2})\b", sem_acento)
    if m_ano:
        ano = m_ano.group(1)
        tokens = re.findall(r"[a-z]+", sem_acento)
        for tok in reversed(tokens):
            if tok in MESES_PT:
                return f"{ano}-{MESES_PT[tok]:02d}"

    return None


def formatar_moeda_br(valor: Decimal) -> str:
    """Formata um Decimal no padrão brasileiro ``1.234,56``."""
    neg = valor < 0
    absoluto = abs(valor).quantize(Decimal("0.01"))
    inteiro, frac = f"{absoluto:.2f}".split(".")
    inteiro_fmt = f"{int(inteiro):,}".replace(",", ".")
    prefixo = "-" if neg else ""
    return f"{prefixo}{inteiro_fmt},{frac}"
