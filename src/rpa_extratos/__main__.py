"""Ponto de entrada CLI e orquestração ponta a ponta da automação."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from .classificador import classificar
from .config import AppConfig, carregar_config
from .consolidador import gerar_planilha
from .descoberta import listar_arquivos
from .extratores import extrair_documento
from .log import escrever_logs
from .modelos import ResultadoExtracao
from .validacao import validar_lote


def executar_pipeline(
    entrada: Path,
    saida: Path,
    logs: Path,
    config: AppConfig,
) -> tuple[list[ResultadoExtracao], Path, Path, Path]:
    """Executa o pipeline completo: Descoberta -> Classificação -> Extração -> Validação -> Consolidação."""
    inicio = datetime.now()
    arquivos = listar_arquivos(entrada)
    resultados: list[ResultadoExtracao] = []

    for arq in arquivos:
        t0 = time.perf_counter()
        try:
            tipo = classificar(arq.caminho)
            resultado = extrair_documento(arq, tipo, config)
            resultado.duracao_s = time.perf_counter() - t0
        except Exception as exc:
            resultado = ResultadoExtracao.falha(
                arq.caminho,
                f"Erro inesperado no processamento: {type(exc).__name__}: {exc}",
                hash_sha256=arq.hash_sha256,
                duracao_s=time.perf_counter() - t0,
            )
        resultados.append(resultado)

    meta_validacao = validar_lote(resultados, config)
    planilha = gerar_planilha(
        resultados,
        pasta_saida=saida,
        modelo_path=config.modelo_planilha,
        periodo_lote=meta_validacao.get("periodo_lote"),  # type: ignore[arg-type]
    )
    fim = datetime.now()
    log_path, json_path = escrever_logs(
        pasta_logs=logs,
        pasta_entrada=entrada,
        resultados=resultados,
        meta_validacao=meta_validacao,
        saida_planilha=planilha,
        inicio=inicio,
        fim=fim,
        config=config,
    )
    return resultados, planilha, log_path, json_path


def build_parser() -> argparse.ArgumentParser:
    """Constrói o parser de argumentos da CLI."""
    parser = argparse.ArgumentParser(
        prog="rpa_extratos",
        description="Consolidação automática de saldos finais de extratos bancários.",
    )
    parser.add_argument("--entrada", type=Path, default=None, help="Pasta com extratos de entrada")
    parser.add_argument("--saida", type=Path, default=None, help="Pasta para salvar a planilha consolidada")
    parser.add_argument("--logs", type=Path, default=None, help="Pasta para salvar os logs de execução")
    parser.add_argument("--config", type=Path, default=None, help="Caminho para config.yaml")
    parser.add_argument(
        "--falhar-em-erro",
        dest="falhar_em_erro",
        action="store_true",
        default=None,
        help="Retorna código de saída 1 se houver arquivos com status 'falhou'",
    )
    parser.add_argument(
        "--nao-falhar-em-erro",
        dest="falhar_em_erro",
        action="store_false",
        help="Retorna código de saída 0 mesmo se houver arquivos com status 'falhou'",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Executa a CLI da automação."""
    parser = build_parser()
    args = parser.parse_args(argv)
    config = carregar_config(args.config)

    entrada = args.entrada or config.entrada
    saida = args.saida or config.saida
    logs = args.logs or config.logs
    falhar_em_erro = (
        args.falhar_em_erro
        if args.falhar_em_erro is not None
        else config.codigo_saida_erro_em_falha
    )

    resultados, planilha, log_path, _ = executar_pipeline(entrada, saida, logs, config)

    ok_n = sum(1 for r in resultados if r.status == "ok")
    rev_n = sum(1 for r in resultados if r.status == "revisar")
    fal_n = sum(1 for r in resultados if r.status == "falhou")
    print(f"Concluído: {len(resultados)} arquivos | ok={ok_n} revisar={rev_n} falhou={fal_n}")
    print(f"Planilha: {planilha}")
    print(f"Log:      {log_path}")

    if falhar_em_erro and fal_n > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
