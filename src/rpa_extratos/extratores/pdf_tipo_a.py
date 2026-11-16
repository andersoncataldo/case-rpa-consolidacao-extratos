"""Extrator determinístico para PDFs Layout A (colunas Valor/Saldo com sufixo C/D)."""

from __future__ import annotations

import re

import pdfplumber

from ..classificador import TipoDocumento
from ..config import AppConfig
from ..descoberta import ArquivoDescoberto
from ..modelos import Movimento, ResultadoExtracao
from ..normalizacao import (
    normalizar_banco,
    normalizar_conta,
    normalizar_periodo,
    parse_valor,
)

RE_BANCO = re.compile(r"^(BANCO\s+[A-ZÀ-Ú0-9 ]+?)(?:\s+EXTRATO\b|$)", re.IGNORECASE)
RE_CONTA = re.compile(r"Conta\s*:\s*([\d]+-[\d\w]+)", re.IGNORECASE)
RE_PERIODO = re.compile(
    r"Per[íi]odo\s*:\s*(\d{2}/\d{2}/\d{4}\s*a\s*\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
RE_SALDO_ANTERIOR = re.compile(
    r"^\d{2}/\d{2}/\d{4}\s+SALDO\s+ANTERIOR\s+([\d\.,]+\s*[CD])\s*$",
    re.IGNORECASE,
)
RE_SALDO_FINAL = re.compile(
    r"^\d{2}/\d{2}/\d{4}\s+SALDO\s+FINAL\s+([\d\.,]+\s*[CD])\s*$",
    re.IGNORECASE,
)
RE_MOVIMENTO = re.compile(
    r"^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+[A-Z]{2,5}\d+\s+([\d\.,]+\s*[CD])\s+([\d\.,]+\s*[CD])\s*$"
)
RE_MOVIMENTO_SEM_DOC = re.compile(
    r"^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+([\d\.,]+\s*[CD])\s+([\d\.,]+\s*[CD])\s*$"
)


def extrair(
    arquivo: ArquivoDescoberto,
    tipo: TipoDocumento,
    config: AppConfig,
) -> ResultadoExtracao:
    """Extrai dados de PDFs Layout A com valores e saldos marcados com C/D."""
    linhas: list[str] = []
    with pdfplumber.open(arquivo.caminho) as pdf:
        for page in pdf.pages:
            texto = page.extract_text() or ""
            linhas.extend(line.strip() for line in texto.splitlines() if line.strip())

    texto_completo = "\n".join(linhas)

    banco: str | None = None
    for linha in linhas[:5]:
        m_banco = RE_BANCO.match(linha)
        if m_banco:
            banco = normalizar_banco(m_banco.group(1))
            break

    m_conta = RE_CONTA.search(texto_completo)
    conta = normalizar_conta(m_conta.group(1)) if m_conta else None

    m_periodo = RE_PERIODO.search(texto_completo)
    periodo = normalizar_periodo(m_periodo.group(1)) if m_periodo else None

    saldo_inicial = None
    saldo_final = None
    movimentos: list[Movimento] = []

    for linha in linhas:
        m_ini = RE_SALDO_ANTERIOR.match(linha)
        if m_ini:
            if saldo_inicial is None:
                saldo_inicial = parse_valor(m_ini.group(1))
            continue

        m_fim = RE_SALDO_FINAL.match(linha)
        if m_fim:
            # Preferir a última ocorrência em caso de múltiplas páginas
            saldo_final = parse_valor(m_fim.group(1))
            continue

        m_mov = RE_MOVIMENTO.match(linha) or RE_MOVIMENTO_SEM_DOC.match(linha)
        if m_mov:
            data_str, desc, val_str, saldo_str = m_mov.groups()
            val = parse_valor(val_str)
            saldo = parse_valor(saldo_str)
            if val is not None:
                movimentos.append(
                    Movimento(
                        data=data_str,
                        descricao=desc.strip(),
                        valor=val,
                        saldo=saldo,
                    )
                )

    return ResultadoExtracao(
        arquivo=arquivo.nome,
        caminho=arquivo.caminho,
        hash_sha256=arquivo.hash_sha256,
        formato=tipo.formato,
        banco=banco,
        conta=conta,
        periodo=periodo,
        saldo_inicial=saldo_inicial,
        saldo_final=saldo_final,
        movimentos=movimentos,
        metodo="pdfplumber:tipo_a",
    )
