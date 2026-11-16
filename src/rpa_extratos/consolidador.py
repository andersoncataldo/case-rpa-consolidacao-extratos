"""Geração da planilha consolidada preservando layout e formatação do modelo."""

from __future__ import annotations

import shutil
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

from .modelos import ResultadoExtracao

CORES_STATUS: dict[str, tuple[PatternFill, Font]] = {
    "ok": (
        PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid"),
        Font(name="Calibri", size=11, bold=True, color="006100"),
    ),
    "revisar": (
        PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid"),
        Font(name="Calibri", size=11, bold=True, color="9C6500"),
    ),
    "falhou": (
        PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"),
        Font(name="Calibri", size=11, bold=True, color="9C0006"),
    ),
}


def _resolver_modelo(modelo_path: Path) -> Path:
    if modelo_path.exists():
        return modelo_path
    alternativo = Path("modelo_consolidado_extratos.xlsx")
    if alternativo.exists():
        return alternativo
    raise FileNotFoundError(f"Modelo de planilha não encontrado: {modelo_path}")


def gerar_planilha(
    resultados: list[ResultadoExtracao],
    pasta_saida: Path,
    modelo_path: Path,
    periodo_lote: str | None,
) -> Path:
    """Preenche a aba ``Consolidado`` a partir do modelo e salva em ``pasta_saida``."""
    pasta_saida.mkdir(parents=True, exist_ok=True)
    modelo = _resolver_modelo(modelo_path)
    sufixo_periodo = periodo_lote or "sem_periodo"
    destino = pasta_saida / f"consolidado_{sufixo_periodo}.xlsx"

    shutil.copy2(modelo, destino)

    wb = openpyxl.load_workbook(destino)
    try:
        ws = wb["Consolidado"]
        # Remove todas as linhas abaixo do cabeçalho (incluindo a linha de exemplo)
        if ws.max_row > 1:
            ws.delete_rows(2, ws.max_row - 1)

        ordenados = sorted(resultados, key=lambda r: (r.arquivo.lower(), r.arquivo))
        fonte_padrao = Font(name="Calibri", size=11)

        for idx, res in enumerate(ordenados, start=2):
            c_arq = ws.cell(row=idx, column=1, value=res.arquivo)
            c_banco = ws.cell(row=idx, column=2, value=res.banco or "")
            c_conta = ws.cell(row=idx, column=3, value=str(res.conta) if res.conta else "")
            c_conta.number_format = "@"
            c_periodo = ws.cell(row=idx, column=4, value=res.periodo or "")
            c_periodo.number_format = "@"

            saldo_num = float(res.saldo_final) if res.saldo_final is not None else None
            c_saldo = ws.cell(row=idx, column=5, value=saldo_num)
            c_saldo.number_format = "#,##0.00"

            c_formato = ws.cell(row=idx, column=6, value=res.formato)
            c_status = ws.cell(row=idx, column=7, value=res.status)
            c_obs = ws.cell(row=idx, column=8, value=res.observacao_texto)

            for cell in (c_arq, c_banco, c_conta, c_periodo, c_saldo, c_formato, c_obs):
                cell.font = fonte_padrao

            c_conta.alignment = Alignment(horizontal="left", vertical="center")
            c_periodo.alignment = Alignment(horizontal="center", vertical="center")
            c_saldo.alignment = Alignment(horizontal="right", vertical="center")
            c_formato.alignment = Alignment(horizontal="center", vertical="center")
            c_obs.alignment = Alignment(wrap_text=True, vertical="center")

            fill_status, font_status = CORES_STATUS.get(
                res.status,
                (PatternFill(fill_type=None), fonte_padrao),
            )
            c_status.fill = fill_status
            c_status.font = font_status
            c_status.alignment = Alignment(horizontal="center", vertical="center")

        ws.freeze_panes = "A2"
        ultima_linha = max(len(ordenados) + 1, 1)
        ws.auto_filter.ref = f"A1:H{ultima_linha}"
        if wb.properties.created is not None:
            wb.properties.modified = wb.properties.created

        wb.save(destino)
    finally:
        wb.close()

    return destino
