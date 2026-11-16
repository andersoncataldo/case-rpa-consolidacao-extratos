"""Geração de logs legível (.log) e estruturado (.json) por execução."""

from __future__ import annotations

import json
import socket
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from . import __version__
from .config import AppConfig
from .modelos import ResultadoExtracao
from .normalizacao import formatar_moeda_br


def _formatar_duracao(segundos: float) -> str:
    total = max(0, int(round(segundos)))
    horas, resto = divmod(total, 3600)
    minutos, segs = divmod(resto, 60)
    return f"{horas:02d}:{minutos:02d}:{segs:02d}"


def _estimar_custo_usd(resultados: list[ResultadoExtracao], config: AppConfig) -> float:
    tokens_in = sum(r.tokens_entrada for r in resultados)
    tokens_out = sum(r.tokens_saida for r in resultados)
    custo_in = (tokens_in / 1_000_000) * config.gemini.custo_por_1m_entrada_usd
    custo_out = (tokens_out / 1_000_000) * config.gemini.custo_por_1m_saida_usd
    return round(custo_in + custo_out, 6)


def escrever_logs(
    pasta_logs: Path,
    pasta_entrada: Path,
    resultados: list[ResultadoExtracao],
    meta_validacao: dict[str, Any],
    saida_planilha: Path,
    inicio: datetime,
    fim: datetime,
    config: AppConfig,
) -> tuple[Path, Path]:
    """Grava os arquivos ``.log`` e ``.json`` com auditoria completa da execução."""
    pasta_logs.mkdir(parents=True, exist_ok=True)
    carimbo = inicio.strftime("%Y%m%d_%H%M%S")
    log_path = pasta_logs / f"execucao_{carimbo}.log"
    json_path = pasta_logs / f"execucao_{carimbo}.json"

    duracao_s = (fim - inicio).total_seconds()
    periodo_lote = meta_validacao.get("periodo_lote") or "indefinido"
    duplicidades = list(meta_validacao.get("duplicidades") or [])
    contas_ausentes = list(meta_validacao.get("contas_ausentes") or [])

    contagem_formato = Counter(r.formato for r in resultados)
    contagem_status = Counter(r.status for r in resultados)
    chamadas_ia = sum(r.chamadas_ia for r in resultados)
    tokens_in = sum(r.tokens_entrada for r in resultados)
    tokens_out = sum(r.tokens_saida for r in resultados)
    tokens_total = sum(r.tokens_total for r in resultados)
    custo_usd = _estimar_custo_usd(resultados, config)

    ordenados = sorted(resultados, key=lambda r: (r.arquivo.lower(), r.arquivo))
    host = socket.gethostname()

    linhas = [
        "=== EXECUÇÃO RPA EXTRATOS ===",
        f"Início: {inicio.strftime('%Y-%m-%d %H:%M:%S')}   Versão: {__version__}   Host: {host}",
        f"Pasta de entrada: {pasta_entrada}   Período do lote: {periodo_lote}",
        (
            f"Arquivos encontrados: {len(resultados)} "
            f"(PDF {contagem_formato.get('PDF', 0)} | "
            f"Imagem {contagem_formato.get('Imagem', 0)} | "
            f"Excel {contagem_formato.get('Excel', 0)}"
            + (
                f" | Outro {contagem_formato.get('Desconhecido', 0)}"
                if contagem_formato.get("Desconhecido", 0)
                else ""
            )
            + ")"
        ),
        "",
    ]

    for r in ordenados:
        tag = f"[{r.status.upper()}]".ljust(10)
        banco = (r.banco or "—").ljust(16)
        conta = (r.conta or "—").ljust(11)
        periodo = (r.periodo or "—").ljust(9)
        saldo = (f"R$ {formatar_moeda_br(r.saldo_final)}" if r.saldo_final is not None else "—").ljust(16)
        hash_curto = r.hash_sha256[:12] if r.hash_sha256 else "—"
        linhas.append(
            f"{tag} {r.arquivo:<36} {banco} {conta} {periodo} {saldo} "
            f"({r.metodo}, {r.duracao_s:.2f}s, sha256:{hash_curto})"
        )
        if r.observacoes:
            linhas.append(f"           ↳ {r.observacao_texto}")

    linhas.extend(
        [
            "",
            "=== RESUMO ===",
            (
                f"Processados: {len(resultados)} | "
                f"ok: {contagem_status.get('ok', 0)} | "
                f"revisar: {contagem_status.get('revisar', 0)} | "
                f"falhou: {contagem_status.get('falhou', 0)}"
            ),
            f"Contas esperadas ausentes: {', '.join(contas_ausentes) if contas_ausentes else 'nenhuma configurada/ausente'}",
            f"Duplicidades: {'; '.join(duplicidades) if duplicidades else 'nenhuma'}",
            (
                f"Chamadas de IA: {chamadas_ia} | "
                f"Tokens: {tokens_total} (entrada={tokens_in}, saída={tokens_out}) | "
                f"Custo estimado: US$ {custo_usd:.6f}"
            ),
            f"Duração total: {_formatar_duracao(duracao_s)} ({duracao_s:.2f}s)",
            f"Saída: {saida_planilha}",
        ]
    )

    texto_log = "\n".join(linhas) + "\n"
    log_path.write_text(texto_log, encoding="utf-8")
    (pasta_logs / "ultima_execucao.log").write_text(texto_log, encoding="utf-8")

    payload = {
        "versao": __version__,
        "host": host,
        "inicio": inicio.isoformat(),
        "fim": fim.isoformat(),
        "duracao_segundos": round(duracao_s, 3),
        "pasta_entrada": str(pasta_entrada),
        "periodo_lote": periodo_lote,
        "modelo_gemini": config.gemini.modelo,
        "contagem_por_formato": dict(contagem_formato),
        "resumo_status": {
            "total": len(resultados),
            "ok": contagem_status.get("ok", 0),
            "revisar": contagem_status.get("revisar", 0),
            "falhou": contagem_status.get("falhou", 0),
        },
        "duplicidades": duplicidades,
        "contas_ausentes": contas_ausentes,
        "ia": {
            "chamadas": chamadas_ia,
            "tokens_entrada": tokens_in,
            "tokens_saida": tokens_out,
            "tokens_total": tokens_total,
            "custo_estimado_usd": custo_usd,
        },
        "saida_planilha": str(saida_planilha),
        "arquivos": [
            {
                "arquivo": r.arquivo,
                "formato": r.formato,
                "banco": r.banco,
                "conta": r.conta,
                "periodo": r.periodo,
                "saldo_inicial": str(r.saldo_inicial) if r.saldo_inicial is not None else None,
                "saldo_final": str(r.saldo_final) if r.saldo_final is not None else None,
                "status": r.status,
                "observacoes": r.observacoes,
                "metodo": r.metodo,
                "hash_sha256": r.hash_sha256,
                "hash_curto": r.hash_sha256[:12] if r.hash_sha256 else "",
                "duracao_segundos": round(r.duracao_s, 3),
                "chamadas_ia": r.chamadas_ia,
                "tokens_total": r.tokens_total,
            }
            for r in ordenados
        ],
    }

    texto_json = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    json_path.write_text(texto_json, encoding="utf-8")
    (pasta_logs / "ultima_execucao.json").write_text(texto_json, encoding="utf-8")

    return log_path, json_path
