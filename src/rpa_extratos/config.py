"""Carregamento de configurações externas (config.yaml e variáveis de ambiente)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


def _carregar_yaml(texto: str) -> dict[str, Any]:
    """Carrega texto YAML usando ruamel.yaml (ou PyYAML como fallback)."""
    try:
        from ruamel.yaml import YAML

        parser = YAML(typ="safe")
        return parser.load(texto) or {}
    except ImportError:
        import yaml

        return yaml.safe_load(texto) or {}


@dataclass
class GeminiConfig:
    """Parâmetros de chamada da API Google Gemini."""

    modelo: str = "gemini-3.8-flash"
    modelos_fallback: list[str] = field(
        default_factory=lambda: ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    )
    temperatura: float = 0.0
    timeout_segundos: int = 60
    max_tentativas: int = 3
    custo_por_1m_entrada_usd: float = 0.30
    custo_por_1m_saida_usd: float = 2.50


@dataclass
class ValidacaoConfig:
    """Parâmetros de validação e reconciliação."""

    tolerancia_reconciliacao: Decimal = Decimal("0.01")
    padrao_conta_regex: str = r"^\d{5}-\d$"
    multiplicador_lancamento_atipico: float = 10.0


@dataclass
class AppConfig:
    """Configuração global da aplicação."""

    entrada: Path = Path("entrada")
    saida: Path = Path("saida")
    logs: Path = Path("logs")
    modelo_planilha: Path = Path("modelo/modelo_consolidado_extratos.xlsx")
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
    validacao: ValidacaoConfig = field(default_factory=ValidacaoConfig)
    codigo_saida_erro_em_falha: bool = False
    rotulos_saldo_final: list[str] = field(
        default_factory=lambda: ["saldo final", "saldo em 31/", "saldo em 30/", "saldo atual"]
    )
    rotulos_saldo_inicial: list[str] = field(
        default_factory=lambda: ["saldo anterior", "saldo inicial", "saldo_inicial"]
    )
    contas_esperadas: list[str] = field(default_factory=list)


def carregar_config(caminho_yaml: Path | None = None) -> AppConfig:
    """Carrega ``.env`` e ``config.yaml`` com valores padrão seguros."""
    load_dotenv()
    raiz = Path.cwd()
    yaml_path = caminho_yaml or (raiz / "config.yaml")
    dados: dict[str, Any] = {}
    if yaml_path.exists():
        dados = _carregar_yaml(yaml_path.read_text(encoding="utf-8"))

    pastas = dados.get("pastas", {})
    gem = dados.get("gemini", {})
    val = dados.get("validacao", {})
    exe = dados.get("execucao", {})
    rot = dados.get("rotulos", {})

    gemini_cfg = GeminiConfig(
        modelo=str(gem.get("modelo", "gemini-3.8-flash")),
        modelos_fallback=list(gem.get("modelos_fallback", ["gemini-3.8-flash", "gemini-3.5-flash-lite"])),
        temperatura=float(gem.get("temperatura", 0.0)),
        timeout_segundos=int(gem.get("timeout_segundos", 60)),
        max_tentativas=int(gem.get("max_tentativas", 3)),
        custo_por_1m_entrada_usd=float(gem.get("custo_por_1m_entrada_usd", 0.30)),
        custo_por_1m_saida_usd=float(gem.get("custo_por_1m_saida_usd", 2.50)),
    )

    val_cfg = ValidacaoConfig(
        tolerancia_reconciliacao=Decimal(str(val.get("tolerancia_reconciliacao", "0.01"))),
        padrao_conta_regex=str(val.get("padrao_conta_regex", r"^\d{5}-\d$")),
        multiplicador_lancamento_atipico=float(val.get("multiplicador_lancamento_atipico", 10.0)),
    )

    return AppConfig(
        entrada=Path(pastas.get("entrada", "entrada")),
        saida=Path(pastas.get("saida", "saida")),
        logs=Path(pastas.get("logs", "logs")),
        modelo_planilha=Path(pastas.get("modelo_planilha", "modelo/modelo_consolidado_extratos.xlsx")),
        gemini=gemini_cfg,
        validacao=val_cfg,
        codigo_saida_erro_em_falha=bool(exe.get("codigo_saida_erro_em_falha", False)),
        rotulos_saldo_final=list(
            rot.get("saldo_final", ["saldo final", "saldo em 31/", "saldo em 30/", "saldo atual"])
        ),
        rotulos_saldo_inicial=list(
            rot.get("saldo_inicial", ["saldo anterior", "saldo inicial", "saldo_inicial"])
        ),
        contas_esperadas=list(val.get("contas_esperadas", [])),
    )
