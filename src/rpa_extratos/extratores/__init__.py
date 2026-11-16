"""Despacho de extração por layout identificado no conteúdo."""

from __future__ import annotations

from .base import ExtratorBase
from ..classificador import TipoDocumento
from ..config import AppConfig
from ..descoberta import ArquivoDescoberto
from ..modelos import ResultadoExtracao


def extrair_documento(
    arquivo: ArquivoDescoberto,
    tipo: TipoDocumento,
    config: AppConfig,
) -> ResultadoExtracao:
    """Encaminha o arquivo para o extrator correspondente ao layout classificado."""
    if tipo.layout == "pdf_nao_extrato":
        res = ResultadoExtracao(
            arquivo=arquivo.nome,
            caminho=arquivo.caminho,
            hash_sha256=arquivo.hash_sha256,
            formato=tipo.formato,
            nao_e_extrato=True,
            metodo="pdfplumber:nao_extrato",
        )
        res.adicionar_observacao("falhou", "Documento não é um extrato bancário")
        return res

    if tipo.layout in {"pdf_corrompido", "excel_corrompido", "imagem_corrompida", "nao_suportado", "vazio", "inexistente"}:
        return ResultadoExtracao.falha(
            arquivo.caminho,
            tipo.detalhe or f"Arquivo inválido ({tipo.layout})",
            hash_sha256=arquivo.hash_sha256,
            formato=tipo.formato,
            metodo=f"classificador:{tipo.layout}",
        )

    extrator = _resolver_extrator(tipo.layout)
    if extrator is None:
        return ResultadoExtracao.falha(
            arquivo.caminho,
            f"Extrator ainda não implementado para layout '{tipo.layout}'",
            hash_sha256=arquivo.hash_sha256,
            formato=tipo.formato,
            metodo=f"pendente:{tipo.layout}",
        )

    return extrator(arquivo, tipo, config)


def _resolver_extrator(layout: str) -> ExtratorBase | None:
    if layout == "excel_aba_controle":
        from .excel_aba_controle import extrair
        return extrair
    if layout == "excel_cabecalho":
        from .excel_cabecalho import extrair
        return extrair
    if layout == "pdf_tipo_a":
        from .pdf_tipo_a import extrair
        return extrair
    if layout == "pdf_tipo_b":
        from .pdf_tipo_b import extrair
        return extrair
    return None
