"""Extrator determinístico para PDFs Layout B (Horizonte, Cerrado)."""

from __future__ import annotations

import re
from decimal import Decimal

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
    remover_acentos,
)

RE_CONTA = re.compile(r"Conta\s+([\d]+-[\d\w]+)", re.IGNORECASE)
RE_PERIODO = re.compile(
    r"Per[íi]odo\s+consultado\s*:\s*(\d{2}/\d{2}/\d{4}\s*a\s*\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
RE_SALDO_EM = re.compile(r"Saldo\s+em\s+(\d{2}/\d{2}/\d{4})\s+([\d\.,]+)", re.IGNORECASE)
RE_TOTAL_CRED = re.compile(r"Total\s+de\s+cr[ée]ditos\s+([\d\.,]+)", re.IGNORECASE)
RE_TOTAL_DEB = re.compile(r"Total\s+de\s+d[ée]bitos\s+([\d\.,]+)", re.IGNORECASE)
RE_DATA_CURTA = re.compile(r"^\d{2}/\d{2}$")
RE_NUMERO_BR = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}$")


def _agrupar_linhas_por_y(words: list[dict], tolerancia_y: float = 3.0) -> list[list[dict]]:
    """Agrupa palavras da página na mesma linha visual (coordenada ``top``)."""
    if not words:
        return []
    ordenadas = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
    linhas: list[list[dict]] = []
    linha_atual: list[dict] = [ordenadas[0]]
    y_ref = ordenadas[0]["top"]

    for w in ordenadas[1:]:
        if abs(w["top"] - y_ref) <= tolerancia_y:
            linha_atual.append(w)
        else:
            linha_atual.sort(key=lambda item: item["x0"])
            linhas.append(linha_atual)
            linha_atual = [w]
            y_ref = w["top"]

    if linha_atual:
        linha_atual.sort(key=lambda item: item["x0"])
        linhas.append(linha_atual)
    return linhas


def _detectar_limites_colunas(linhas_palavras: list[list[dict]]) -> tuple[float, float] | None:
    """Encontra os divisores horizontais entre Crédito/Débito e Débito/Saldo pelo cabeçalho."""
    for linha in linhas_palavras:
        tokens = {remover_acentos(w["text"].lower()): w for w in linha}
        if "credito" in tokens and "debito" in tokens and "saldo" in tokens:
            x_cred = tokens["credito"]["x0"]
            x_deb = tokens["debito"]["x0"]
            x_saldo = tokens["saldo"]["x0"]
            limite_cred_deb = (x_cred + x_deb) / 2.0
            limite_deb_saldo = (x_deb + x_saldo) / 2.0
            return limite_cred_deb, limite_deb_saldo
    return None


def extrair(
    arquivo: ArquivoDescoberto,
    tipo: TipoDocumento,
    config: AppConfig,
) -> ResultadoExtracao:
    """Extrai cabeçalho, lançamentos por coluna e Resumo do período de PDFs Layout B."""
    textos_paginas: list[str] = []
    movimentos_brutos: list[tuple[str, str, Decimal, Decimal, str]] = []
    limites_globais: tuple[float, float] | None = None

    with pdfplumber.open(arquivo.caminho) as pdf:
        for page in pdf.pages:
            textos_paginas.append(page.extract_text() or "")
            linhas_words = _agrupar_linhas_por_y(page.extract_words())
            limites = _detectar_limites_colunas(linhas_words) or limites_globais
            if limites is not None:
                limites_globais = limites

            for linha in linhas_words:
                if not linha:
                    continue
                primeiro = linha[0]["text"].strip()
                if not RE_DATA_CURTA.match(primeiro):
                    continue

                numeros = [w for w in linha[1:] if RE_NUMERO_BR.match(w["text"].strip())]
                if len(numeros) < 2:
                    continue

                saldo_word = numeros[-1]
                valor_word = numeros[-2]
                saldo_val = parse_valor(saldo_word["text"])
                valor_abs = parse_valor(valor_word["text"])
                if saldo_val is None or valor_abs is None:
                    continue

                desc_palavras = [
                    w["text"]
                    for w in linha[1:]
                    if w["x0"] < valor_word["x0"] - 5 and not RE_NUMERO_BR.match(w["text"].strip())
                ]
                descricao = " ".join(desc_palavras).strip()

                x_centro = (valor_word["x0"] + valor_word["x1"]) / 2.0
                if limites_globais is not None:
                    lim_cd, _ = limites_globais
                    lado = "credito" if x_centro < lim_cd else "debito"
                else:
                    lado = "indefinido"

                movimentos_brutos.append((primeiro, descricao, abs(valor_abs), saldo_val, lado))

    texto_completo = "\n".join(textos_paginas)
    linhas_texto = [ln.strip() for ln in texto_completo.splitlines() if ln.strip()]

    banco: str | None = None
    for linha in linhas_texto[:5]:
        if "banco" in remover_acentos(linha.lower()):
            banco = normalizar_banco(linha)
            break

    m_conta = RE_CONTA.search(texto_completo)
    conta = normalizar_conta(m_conta.group(1)) if m_conta else None

    m_periodo = RE_PERIODO.search(texto_completo)
    periodo = normalizar_periodo(m_periodo.group(1)) if m_periodo else None

    saldos_resumo = RE_SALDO_EM.findall(texto_completo)
    saldo_inicial = parse_valor(saldos_resumo[0][1]) if saldos_resumo else None
    saldo_final = parse_valor(saldos_resumo[-1][1]) if len(saldos_resumo) >= 2 else (
        parse_valor(saldos_resumo[0][1]) if saldos_resumo else None
    )

    m_cred = RE_TOTAL_CRED.search(texto_completo)
    m_deb = RE_TOTAL_DEB.search(texto_completo)
    total_creditos = parse_valor(m_cred.group(1)) if m_cred else None
    total_debitos = parse_valor(m_deb.group(1)) if m_deb else None

    # Constrói movimentos definindo sinal pela coluna detectada (e fallback pelo delta do saldo)
    movimentos: list[Movimento] = []
    saldo_ref = saldo_inicial
    for data_str, desc, val_abs, saldo_val, lado in movimentos_brutos:
        if lado == "credito":
            valor = val_abs
        elif lado == "debito":
            valor = -val_abs
        elif saldo_ref is not None:
            valor = val_abs if saldo_val >= saldo_ref else -val_abs
        else:
            valor = val_abs

        movimentos.append(
            Movimento(
                data=data_str,
                descricao=desc,
                valor=valor,
                saldo=saldo_val,
            )
        )
        saldo_ref = saldo_val

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
        total_creditos_declarado=total_creditos,
        total_debitos_declarado=total_debitos,
        metodo="pdfplumber:tipo_b",
    )
