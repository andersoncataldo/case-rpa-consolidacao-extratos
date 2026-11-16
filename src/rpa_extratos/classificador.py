"""Classificação de arquivos pelo conteúdo (magic bytes, estrutura e texto)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .normalizacao import remover_acentos

ASSINATURA_PDF = b"%PDF"
ASSINATURA_PNG = b"\x89PNG\r\n\x1a\n"
ASSINATURA_JPEG = b"\xff\xd8\xff"
ASSINATURA_ZIP = b"PK\x03\x04"

EXTENSOES_IMAGEM = {".png", ".jpg", ".jpeg", ".webp"}
EXTENSOES_EXCEL = {".xlsx", ".xlsm"}


@dataclass(frozen=True)
class TipoDocumento:
    """Resultado da classificação de um arquivo de entrada."""

    formato: str  # "PDF" | "Excel" | "Imagem" | "Desconhecido"
    layout: str   # ex.: "pdf_tipo_a", "pdf_tipo_b", "pdf_nao_extrato", "excel_aba_controle", ...
    detalhe: str = ""


def _ler_cabecalho_bytes(caminho: Path, tamanho: int = 16) -> bytes:
    with caminho.open("rb") as f:
        return f.read(tamanho)


def _classificar_pdf(caminho: Path) -> TipoDocumento:
    import pdfplumber

    try:
        with pdfplumber.open(caminho) as pdf:
            if not pdf.pages:
                return TipoDocumento(formato="PDF", layout="pdf_corrompido", detalhe="PDF sem páginas")
            textos = [page.extract_text() or "" for page in pdf.pages]
    except Exception as exc:
        return TipoDocumento(
            formato="PDF",
            layout="pdf_corrompido",
            detalhe=f"Erro ao abrir PDF: {type(exc).__name__}: {exc}",
        )

    texto_completo = "\n".join(textos).strip()
    if len(texto_completo) < 20:
        return TipoDocumento(formato="PDF", layout="pdf_escaneado", detalhe="PDF sem texto selecionável")

    norm = remover_acentos(texto_completo.lower())

    if "nao e um extrato bancario" in norm:
        return TipoDocumento(formato="PDF", layout="pdf_nao_extrato", detalhe="Comunicado explícito de não-extrato")

    if "saldo anterior" in norm and "saldo final" in norm:
        return TipoDocumento(formato="PDF", layout="pdf_tipo_a")

    if "resumo do periodo" in norm or ("total de creditos" in norm and "total de debitos" in norm):
        return TipoDocumento(formato="PDF", layout="pdf_tipo_b")

    tem_conta = "conta" in norm
    tem_saldo = "saldo" in norm
    if not tem_conta and not tem_saldo:
        return TipoDocumento(formato="PDF", layout="pdf_nao_extrato", detalhe="Ausência de conta e saldo")

    return TipoDocumento(formato="PDF", layout="pdf_desconhecido", detalhe="Layout de PDF não reconhecido")


def _classificar_excel(caminho: Path) -> TipoDocumento:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    except Exception as exc:
        return TipoDocumento(
            formato="Excel",
            layout="excel_corrompido",
            detalhe=f"Erro ao abrir planilha Excel: {type(exc).__name__}: {exc}",
        )

    try:
        abas = [s.strip().lower() for s in wb.sheetnames]
        if "dados" in abas and "controle" in abas:
            return TipoDocumento(formato="Excel", layout="excel_aba_controle")
        if "extrato" in abas:
            return TipoDocumento(formato="Excel", layout="excel_cabecalho")

        # Fallback por conteúdo da primeira aba
        ws = wb[wb.sheetnames[0]]
        amostra = []
        for row in ws.iter_rows(min_row=1, max_row=12, max_col=8, values_only=True):
            for cell in row:
                if cell is not None:
                    amostra.append(str(cell).lower())
        texto = remover_acentos(" ".join(amostra))
        if "saldo final" in texto or "saldo anterior" in texto or "conta" in texto:
            return TipoDocumento(formato="Excel", layout="excel_cabecalho")
        return TipoDocumento(formato="Excel", layout="excel_desconhecido", detalhe="Estrutura Excel não reconhecida")
    finally:
        wb.close()


def classificar(caminho: Path) -> TipoDocumento:
    """Classifica o arquivo inspecionando magic bytes e conteúdo."""
    if not caminho.exists() or not caminho.is_file():
        return TipoDocumento(formato="Desconhecido", layout="inexistente", detalhe="Arquivo não encontrado")

    if caminho.stat().st_size == 0:
        return TipoDocumento(formato="Desconhecido", layout="vazio", detalhe="Arquivo vazio (0 bytes)")

    magic = _ler_cabecalho_bytes(caminho)
    ext = caminho.suffix.lower()

    if magic.startswith(ASSINATURA_PDF) or ext == ".pdf":
        if not magic.startswith(ASSINATURA_PDF):
            return TipoDocumento(formato="PDF", layout="pdf_corrompido", detalhe="Cabeçalho %PDF ausente")
        return _classificar_pdf(caminho)

    if magic.startswith(ASSINATURA_PNG) or magic.startswith(ASSINATURA_JPEG) or ext in EXTENSOES_IMAGEM:
        if magic.startswith(ASSINATURA_PNG) or magic.startswith(ASSINATURA_JPEG):
            return TipoDocumento(formato="Imagem", layout="imagem_visao")
        return TipoDocumento(formato="Imagem", layout="imagem_corrompida", detalhe="Arquivo de imagem inválido")

    if ext in EXTENSOES_EXCEL or magic.startswith(ASSINATURA_ZIP):
        if ext in EXTENSOES_EXCEL:
            return _classificar_excel(caminho)

    return TipoDocumento(
        formato="Desconhecido",
        layout="nao_suportado",
        detalhe=f"Extensão ou formato não suportado ({ext or 'sem extensão'})",
    )
