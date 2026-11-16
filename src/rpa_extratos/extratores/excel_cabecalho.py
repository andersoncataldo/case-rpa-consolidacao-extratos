"""Extrator determinístico para planilhas Excel com cabeçalho na aba Extrato."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import openpyxl
from openpyxl.utils.datetime import from_excel

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
    if isinstance(valor, (int, float)) and 30000 <= float(valor) <= 80000:
        dt = from_excel(float(valor))
        if isinstance(dt, (datetime, date)):
            return dt.strftime("%d/%m/%Y")
    texto = str(valor).strip()
    return texto or None


def _selecionar_aba(wb: openpyxl.Workbook) -> openpyxl.worksheet.worksheet.Worksheet:
    for nome in wb.sheetnames:
        if nome.strip().lower() == "extrato":
            return wb[nome]
    return wb[wb.sheetnames[0]]


def _linha_expandida(ws: openpyxl.worksheet.worksheet.Worksheet) -> list[list[Any]]:
    """Lê a planilha resolvendo células mescladas quando existirem."""
    linhas: list[list[Any]] = []
    max_row = ws.max_row or 0
    max_col = ws.max_column or 0
    for r in range(1, max_row + 1):
        linhas.append([ws.cell(row=r, column=c).value for c in range(1, max_col + 1)])

    for rng in ws.merged_cells.ranges:
        valor_topo = ws.cell(row=rng.min_row, column=rng.min_col).value
        for r in range(rng.min_row, rng.max_row + 1):
            for c in range(rng.min_col, rng.max_col + 1):
                if r - 1 < len(linhas) and c - 1 < len(linhas[r - 1]):
                    if linhas[r - 1][c - 1] is None:
                        linhas[r - 1][c - 1] = valor_topo
    return linhas


def extrair(
    arquivo: ArquivoDescoberto,
    tipo: TipoDocumento,
    config: AppConfig,
) -> ResultadoExtracao:
    """Extrai cabeçalho, lançamentos e saldo final do layout de aba única/Extrato."""
    wb = openpyxl.load_workbook(arquivo.caminho, data_only=True)
    try:
        ws = _selecionar_aba(wb)
        linhas = _linha_expandida(ws)

        banco: str | None = None
        conta: str | None = None
        periodo: str | None = None
        saldo_inicial = None
        saldo_final = None
        movimentos: list[Movimento] = []

        # Localiza a linha de cabeçalho da tabela de lançamentos
        header_idx: int | None = None
        col_data: int | None = None
        col_desc: int | None = None
        col_valor: int | None = None
        col_saldo: int | None = None

        for idx, row in enumerate(linhas):
            norm_cells = [remover_acentos(str(c).strip().lower()) if c is not None else "" for c in row]
            has_data = any(c == "data" or c.startswith("data ") for c in norm_cells)
            has_desc = any("descricao" in c or "historico" in c or "lancamento" in c for c in norm_cells)
            has_saldo = any("saldo" in c for c in norm_cells)
            if has_data and (has_desc or has_saldo):
                header_idx = idx
                for c_idx, txt in enumerate(norm_cells):
                    if col_data is None and (txt == "data" or txt.startswith("data ")):
                        col_data = c_idx
                    elif col_desc is None and ("descricao" in txt or "historico" in txt or "lancamento" in txt):
                        col_desc = c_idx
                    elif col_valor is None and txt.startswith("valor"):
                        col_valor = c_idx
                    elif col_saldo is None and txt.startswith("saldo"):
                        col_saldo = c_idx
                break

        limite_cabecalho = header_idx if header_idx is not None else min(15, len(linhas))
        for idx in range(limite_cabecalho):
            row = linhas[idx]
            nao_vazios = [c for c in row if c is not None and str(c).strip() != ""]
            if not nao_vazios:
                continue
            primeiro = str(nao_vazios[0]).strip()
            primeiro_norm = remover_acentos(primeiro.lower())

            if idx == 0 and "banco" in primeiro_norm:
                banco = normalizar_banco(primeiro)
                continue
            if banco is None and "banco" in primeiro_norm and len(nao_vazios) == 1:
                banco = normalizar_banco(primeiro)
                continue

            if len(nao_vazios) >= 2:
                valor_meta = nao_vazios[1]
                if primeiro_norm in {"banco", "instituicao"}:
                    banco = normalizar_banco(str(valor_meta))
                elif primeiro_norm in {"conta", "conta corrente", "c/c"}:
                    conta = normalizar_conta(str(valor_meta))
                elif primeiro_norm == "periodo":
                    periodo = normalizar_periodo(valor_meta)

        rot_inicial = [remover_acentos(r.lower()) for r in config.rotulos_saldo_inicial]
        rot_final = [remover_acentos(r.lower()) for r in config.rotulos_saldo_final]

        if header_idx is not None:
            for row in linhas[header_idx + 1 :]:
                if not any(c is not None and str(c).strip() != "" for c in row):
                    continue

                desc_raw = row[col_desc] if col_desc is not None and col_desc < len(row) else None
                desc_str = str(desc_raw).strip() if desc_raw is not None else ""
                desc_norm = remover_acentos(desc_str.lower())

                valor_cell = row[col_valor] if col_valor is not None and col_valor < len(row) else None
                saldo_cell = row[col_saldo] if col_saldo is not None and col_saldo < len(row) else None
                valor_num = parse_valor(valor_cell)
                saldo_num = parse_valor(saldo_cell)

                # Linha de SALDO ANTERIOR / INICIAL
                if any(r in desc_norm for r in rot_inicial):
                    saldo_inicial = saldo_num if saldo_num is not None else valor_num
                    continue

                # Linha de SALDO FINAL
                if any(r in desc_norm for r in rot_final):
                    saldo_final = saldo_num if saldo_num is not None else valor_num
                    continue

                # Linha normal de lançamento
                if valor_num is not None:
                    data_cell = row[col_data] if col_data is not None and col_data < len(row) else None
                    movimentos.append(
                        Movimento(
                            data=_formatar_data_celula(data_cell),
                            descricao=desc_str,
                            valor=valor_num,
                            saldo=saldo_num,
                        )
                    )

        # Fallback genérico por sinônimos caso o saldo final esteja fora da coluna padrão
        if saldo_final is None:
            for row in linhas:
                for c_idx, cell in enumerate(row):
                    if cell is None:
                        continue
                    txt_norm = remover_acentos(str(cell).strip().lower())
                    if any(r in txt_norm for r in rot_final):
                        for cand in reversed(row[c_idx + 1 :]):
                            v = parse_valor(cand)
                            if v is not None:
                                saldo_final = v
                                break

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
            metodo="openpyxl:cabecalho",
        )
    finally:
        wb.close()
