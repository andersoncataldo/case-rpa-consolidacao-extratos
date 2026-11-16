"""Extrator determinístico para planilhas Excel com abas 'dados' e 'controle'."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import openpyxl

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


def _formatar_data_celula(valor: Any) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, (datetime, date)):
        return valor.strftime("%d/%m/%Y")
    texto = str(valor).strip()
    return texto or None


def _achar_aba(wb: openpyxl.Workbook, nome_alvo: str) -> str | None:
    alvo = nome_alvo.lower()
    for nome in wb.sheetnames:
        if nome.strip().lower() == alvo:
            return nome
    return None


def extrair(
    arquivo: ArquivoDescoberto,
    tipo: TipoDocumento,
    config: AppConfig,
) -> ResultadoExtracao:
    """Extrai cabeçalho da aba ``controle`` e lançamentos da aba ``dados``."""
    wb = openpyxl.load_workbook(arquivo.caminho, data_only=True, read_only=True)
    try:
        aba_controle_nome = _achar_aba(wb, "controle")
        aba_dados_nome = _achar_aba(wb, "dados")
        if not aba_controle_nome or not aba_dados_nome:
            return ResultadoExtracao.falha(
                arquivo.caminho,
                "Abas 'controle' e 'dados' não encontradas no Excel",
                hash_sha256=arquivo.hash_sha256,
                formato=tipo.formato,
                metodo="openpyxl:aba_controle",
            )

        ws_ctrl = wb[aba_controle_nome]
        meta: dict[str, Any] = {}
        for row in ws_ctrl.iter_rows(values_only=True):
            celulas = [c for c in row if c is not None and str(c).strip() != ""]
            if len(celulas) >= 2:
                chave = remover_acentos(str(celulas[0]).strip().lower())
                meta[chave] = celulas[1]

        banco = normalizar_banco(str(meta.get("banco"))) if meta.get("banco") is not None else None
        conta = normalizar_conta(str(meta.get("conta"))) if meta.get("conta") is not None else None
        periodo = normalizar_periodo(meta.get("periodo"))
        saldo_inicial = parse_valor(meta.get("saldo_inicial"))
        saldo_final = parse_valor(meta.get("saldo_final"))

        ws_dados = wb[aba_dados_nome]
        linhas_dados = list(ws_dados.iter_rows(values_only=True))
        movimentos: list[Movimento] = []

        if linhas_dados:
            header_idx = None
            col_map: dict[str, int] = {}
            for idx, row in enumerate(linhas_dados[:10]):
                mapa_cand: dict[str, int] = {}
                for c_idx, val in enumerate(row):
                    if val is None:
                        continue
                    norm_col = remover_acentos(str(val).strip().lower())
                    mapa_cand[norm_col] = c_idx
                if "valor" in mapa_cand and ("tipo" in mapa_cand or "descricao" in mapa_cand):
                    header_idx = idx
                    col_map = mapa_cand
                    break

            if header_idx is not None:
                idx_data = col_map.get("data")
                idx_tipo = col_map.get("tipo")
                idx_desc = col_map.get("descricao")
                idx_valor = col_map.get("valor")
                idx_saldo = col_map.get("saldo")

                for row in linhas_dados[header_idx + 1 :]:
                    if not row or all(c is None or str(c).strip() == "" for c in row):
                        continue
                    valor_bruto = parse_valor(row[idx_valor]) if idx_valor is not None and idx_valor < len(row) else None
                    if valor_bruto is None:
                        continue

                    tipo_mov = ""
                    if idx_tipo is not None and idx_tipo < len(row) and row[idx_tipo] is not None:
                        tipo_mov = remover_acentos(str(row[idx_tipo]).strip().upper())

                    if "DEBITO" in tipo_mov:
                        valor_mov = -abs(valor_bruto)
                    elif "CREDITO" in tipo_mov:
                        valor_mov = abs(valor_bruto)
                    else:
                        valor_mov = valor_bruto

                    saldo_mov = (
                        parse_valor(row[idx_saldo])
                        if idx_saldo is not None and idx_saldo < len(row)
                        else None
                    )
                    desc_mov = (
                        str(row[idx_desc]).strip()
                        if idx_desc is not None and idx_desc < len(row) and row[idx_desc] is not None
                        else ""
                    )
                    data_mov = (
                        _formatar_data_celula(row[idx_data])
                        if idx_data is not None and idx_data < len(row)
                        else None
                    )
                    movimentos.append(
                        Movimento(
                            data=data_mov,
                            descricao=desc_mov,
                            valor=valor_mov,
                            saldo=saldo_mov,
                        )
                    )

        if saldo_final is None and movimentos and movimentos[-1].saldo is not None:
            saldo_final = movimentos[-1].saldo

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
            metodo="openpyxl:aba_controle",
        )
    finally:
        wb.close()
