"""Motor instrumentado da automação para o painel Streamlit.

Reutiliza exatamente as mesmas funções do pacote ``rpa_extratos`` (descoberta,
classificação, extratores, validação, consolidação e logs), mas executa as
etapas uma de cada vez e emite eventos para que a interface consiga desenhar o
percurso da automação em tempo real.

Modos de execução:
- ``demo``:   Excel e PDF são processados de verdade; para imagens, a resposta
              do Gemini é reaproveitada de ``demo/cache_gemini.json`` (sem chave,
              sem custo). Validação, reconciliação e planilha rodam de verdade.
- ``ao_vivo``: pipeline 100% real, incluindo chamadas à API do Gemini. As
              respostas obtidas atualizam o cache do modo demonstração.
"""

from __future__ import annotations

import json
import sys
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rpa_extratos.classificador import TipoDocumento, classificar  # noqa: E402
from rpa_extratos.config import AppConfig, carregar_config  # noqa: E402
from rpa_extratos.consolidador import gerar_planilha  # noqa: E402
from rpa_extratos.descoberta import ArquivoDescoberto, listar_arquivos  # noqa: E402
from rpa_extratos.extratores import extrair_documento  # noqa: E402
from rpa_extratos.log import escrever_logs  # noqa: E402
from rpa_extratos.modelos import ResultadoExtracao  # noqa: E402
from rpa_extratos.validacao import validar_lote  # noqa: E402

CACHE_GEMINI = ROOT / "demo" / "cache_gemini.json"
ZIP_CASE = ROOT / "extratos_ufv_out2026.zip"
ENTRADA_CASE = ROOT / "entrada"

LAYOUTS_VISAO = {"imagem_visao", "pdf_escaneado"}

ETAPAS: list[tuple[str, str, str, str]] = [
    # chave, título, ícone, tecnologia
    ("descoberta", "Descoberta", "📂", "rglob + SHA-256"),
    ("classificacao", "Classificação", "🔎", "magic bytes + conteúdo"),
    ("extracao", "Extração", "⚙️", "openpyxl · pdfplumber · Gemini"),
    ("validacao", "Validação", "🧮", "reconciliação em Decimal"),
    ("consolidacao", "Consolidação", "📊", "planilha modelo + logs"),
]

DESCRICAO_LAYOUT: dict[str, tuple[str, str]] = {
    # layout: (motor, explicação)
    "excel_aba_controle": ("openpyxl", "Excel com abas 'Dados' + 'Controle'"),
    "excel_cabecalho": ("openpyxl", "Excel com aba 'Extrato' e cabeçalho"),
    "excel_desconhecido": ("—", "Estrutura de Excel não reconhecida"),
    "excel_corrompido": ("—", "Excel corrompido"),
    "pdf_tipo_a": ("pdfplumber", "PDF Tipo A (Saldo anterior / Saldo final)"),
    "pdf_tipo_b": ("pdfplumber", "PDF Tipo B (Resumo do período)"),
    "pdf_nao_extrato": ("pdfplumber", "PDF que não é extrato bancário"),
    "pdf_escaneado": ("Gemini Visão", "PDF escaneado (sem texto) → IA"),
    "pdf_desconhecido": ("—", "Layout de PDF não reconhecido"),
    "pdf_corrompido": ("—", "PDF corrompido"),
    "imagem_visao": ("Gemini Visão", "Print de aplicativo → IA + reconciliação"),
    "imagem_corrompida": ("—", "Imagem inválida"),
    "nao_suportado": ("—", "Formato não suportado"),
    "vazio": ("—", "Arquivo vazio"),
}


# ---------------------------------------------------------------------------
# Estruturas de rastreio
# ---------------------------------------------------------------------------


@dataclass
class RastroArquivo:
    """Jornada completa de um arquivo pelas 5 etapas."""

    nome: str
    caminho: Path
    tamanho_bytes: int
    hash_sha256: str
    magic_hex: str
    tipo: TipoDocumento | None = None
    resultado: ResultadoExtracao | None = None
    status_pos_extracao: str | None = None
    obs_pos_extracao: list[str] = field(default_factory=list)
    origem_ia: str | None = None  # "cache" | "ao_vivo" | None
    duracao_ia_original_s: float | None = None

    @property
    def motor(self) -> str:
        if self.tipo is None:
            return "—"
        return DESCRICAO_LAYOUT.get(self.tipo.layout, ("—", ""))[0]

    @property
    def descricao_layout(self) -> str:
        if self.tipo is None:
            return "—"
        return DESCRICAO_LAYOUT.get(self.tipo.layout, ("—", self.tipo.layout))[1]

    @property
    def obs_validacao(self) -> list[str]:
        """Observações acrescentadas pela etapa de validação."""
        if self.resultado is None:
            return []
        return [o for o in self.resultado.observacoes if o not in self.obs_pos_extracao]


@dataclass
class Execucao:
    """Resultado completo de uma execução do painel."""

    modo: str
    origem: str
    pasta_entrada: Path
    pasta_trabalho: Path
    inicio: datetime
    fim: datetime
    arquivos: list[RastroArquivo]
    meta_validacao: dict[str, Any]
    planilha: Path
    log_path: Path
    json_path: Path
    duracao_etapas: dict[str, float]
    config: AppConfig

    @property
    def resultados(self) -> list[ResultadoExtracao]:
        return [a.resultado for a in self.arquivos if a.resultado is not None]


Evento = Callable[[str, str, dict[str, Any]], None]


# ---------------------------------------------------------------------------
# Preparação de dados
# ---------------------------------------------------------------------------


def garantir_entrada_case() -> Path:
    """Garante que ``entrada/`` exista (descompacta o zip do case se necessário)."""
    if ENTRADA_CASE.exists() and any(ENTRADA_CASE.iterdir()):
        return ENTRADA_CASE
    if not ZIP_CASE.exists():
        raise FileNotFoundError(f"Pasta entrada/ vazia e zip do case não encontrado: {ZIP_CASE}")
    ENTRADA_CASE.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP_CASE) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = Path(info.filename)
            if rel.parts and rel.parts[0] == "extratos":
                rel = Path(*rel.parts[1:])
            if not str(rel) or rel.name.startswith((".", "~$")):
                continue
            destino = ENTRADA_CASE / rel
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(zf.read(info.filename))
    return ENTRADA_CASE


def carregar_config_app(*, carregar_env: bool = True) -> AppConfig:
    """Carrega a configuração do projeto com caminhos absolutos."""
    config = carregar_config(ROOT / "config.yaml", carregar_env=carregar_env)
    modelo = config.modelo_planilha
    if not modelo.is_absolute():
        config.modelo_planilha = ROOT / modelo
    return config


def ler_cache() -> dict[str, Any]:
    if CACHE_GEMINI.exists():
        try:
            return json.loads(CACHE_GEMINI.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _salvar_cache(novos: dict[str, Any]) -> None:
    try:
        cache = ler_cache()
        cache.update(novos)
        CACHE_GEMINI.parent.mkdir(parents=True, exist_ok=True)
        CACHE_GEMINI.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass  # ambiente somente leitura: o cache é opcional


# ---------------------------------------------------------------------------
# Clientes Gemini: replay do cache (demo) e gravador (ao vivo)
# ---------------------------------------------------------------------------


class _ModelsCache:
    def __init__(self, entrada: dict[str, Any], modelos: list[str]) -> None:
        self._entrada = entrada
        self._modelos = modelos

    def list(self):  # noqa: A003
        return iter(SimpleNamespace(name=f"models/{m}") for m in self._modelos)

    def generate_content(self, **_: Any) -> Any:
        u = self._entrada.get("usage", {})
        return SimpleNamespace(
            text=self._entrada["resposta_json"],
            usage_metadata=SimpleNamespace(
                prompt_token_count=u.get("prompt_token_count", 0),
                candidates_token_count=u.get("candidates_token_count", 0),
                thoughts_token_count=u.get("thoughts_token_count", 0),
                total_token_count=u.get("total_token_count", 0),
            ),
        )


class _ModelsGravador:
    def __init__(self, models: Any, registro: dict[str, Any]) -> None:
        self._models = models
        self._registro = registro

    def list(self):  # noqa: A003
        return self._models.list()

    def generate_content(self, **kwargs: Any) -> Any:
        resp = self._models.generate_content(**kwargs)
        usage = getattr(resp, "usage_metadata", None)
        self._registro.update(
            modelo=kwargs.get("model"),
            resposta_json=getattr(resp, "text", "") or "",
            usage={
                k: int(getattr(usage, k, 0) or 0)
                for k in (
                    "prompt_token_count",
                    "candidates_token_count",
                    "thoughts_token_count",
                    "total_token_count",
                )
            },
        )
        return resp


def _extrair_visao(
    arq: ArquivoDescoberto,
    tipo: TipoDocumento,
    config: AppConfig,
    modo: str,
    api_key: str | None,
    cache: dict[str, Any],
    novos_cache: dict[str, Any],
) -> tuple[ResultadoExtracao, str, float | None]:
    from rpa_extratos.extratores import visao_gemini

    visao_gemini.limpar_cache_modelos()
    modelos = [config.gemini.modelo, *config.gemini.modelos_fallback]

    if modo == "demo":
        entrada = cache.get(arq.hash_sha256)
        if not entrada:
            res = ResultadoExtracao.falha(
                arq.caminho,
                "Imagem sem resposta em cache para o modo Demonstração — execute no modo Ao vivo",
                hash_sha256=arq.hash_sha256,
                formato=tipo.formato,
                metodo="gemini-visao:cache",
            )
            return res, "cache", None
        res = visao_gemini.extrair(
            arq, tipo, config, client_factory=lambda _k, _t: SimpleNamespace(models=_ModelsCache(entrada, modelos))
        )
        if res.metodo.startswith("gemini-visao") and entrada.get("modelo"):
            res.metodo = f"gemini-visao:{entrada['modelo']}"
        return res, "cache", entrada.get("duracao_s")

    # Ao vivo
    if not api_key:
        res = ResultadoExtracao.falha(
            arq.caminho,
            "GEMINI_API_KEY ausente: informe a chave na barra lateral para o modo Ao vivo",
            hash_sha256=arq.hash_sha256,
            formato=tipo.formato,
            metodo="gemini-visao",
        )
        return res, "ao_vivo", None

    from google import genai
    from google.genai import types

    registro: dict[str, Any] = {}

    def _fabrica(_key: str, timeout_ms: int) -> Any:
        real = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=timeout_ms, retry_options=types.HttpRetryOptions(attempts=1)),
        )
        # Mantém a referência ao cliente real: se ele for coletado, a conexão HTTP é fechada.
        return SimpleNamespace(models=_ModelsGravador(real.models, registro), _cliente_real=real)

    t0 = time.perf_counter()
    res = visao_gemini.extrair(arq, tipo, config, client_factory=_fabrica)
    dur = time.perf_counter() - t0
    if registro.get("resposta_json") and res.status != "falhou":
        registro.update(arquivo=arq.nome, duracao_s=round(dur, 3), gravado_em=datetime.now().isoformat())
        novos_cache[arq.hash_sha256] = registro
    return res, "ao_vivo", dur


# ---------------------------------------------------------------------------
# Execução instrumentada
# ---------------------------------------------------------------------------


def _nada(_etapa: str, _msg: str, _dados: dict[str, Any]) -> None:
    return None


def executar(
    entrada: Path,
    pasta_trabalho: Path,
    *,
    modo: str = "demo",
    origem: str = "case",
    api_key: str | None = None,
    ritmo_s: float = 0.0,
    on_evento: Evento | None = None,
) -> Execucao:
    """Executa o pipeline etapa por etapa emitindo eventos para a interface."""
    emitir = on_evento or _nada
    config = carregar_config_app(carregar_env=(modo != "demo"))
    saida = pasta_trabalho / "saida"
    logs = pasta_trabalho / "logs"
    cache = ler_cache()
    novos_cache: dict[str, Any] = {}
    duracoes: dict[str, float] = {}
    inicio = datetime.now()

    def pausa() -> None:
        if ritmo_s > 0:
            time.sleep(ritmo_s)

    # 1. Descoberta -------------------------------------------------------
    emitir("descoberta", "Varrendo a pasta de entrada recursivamente…", {"inicio": True})
    t0 = time.perf_counter()
    descobertos = listar_arquivos(entrada)
    rastros: list[RastroArquivo] = []
    for arq in descobertos:
        with arq.caminho.open("rb") as f:
            magic = f.read(8)
        rastro = RastroArquivo(
            nome=arq.nome,
            caminho=arq.caminho,
            tamanho_bytes=arq.caminho.stat().st_size,
            hash_sha256=arq.hash_sha256,
            magic_hex=magic.hex(" ").upper(),
        )
        rastros.append(rastro)
        emitir("descoberta", f"{arq.nome} · sha256 {arq.hash_sha256[:12]}", {"arquivo": arq.nome})
        pausa()
    duracoes["descoberta"] = time.perf_counter() - t0
    emitir("descoberta", f"{len(rastros)} arquivos encontrados", {"fim": True, "total": len(rastros)})

    # 2. Classificação ---------------------------------------------------
    emitir("classificacao", "Identificando formato e layout pelo conteúdo…", {"inicio": True})
    t0 = time.perf_counter()
    for rastro in rastros:
        try:
            rastro.tipo = classificar(rastro.caminho)
        except Exception as exc:  # isolamento por arquivo
            rastro.tipo = TipoDocumento("Desconhecido", "erro_classificacao", f"{type(exc).__name__}: {exc}")
        emitir(
            "classificacao",
            f"{rastro.nome} → {rastro.tipo.formato} / {rastro.tipo.layout}",
            {"arquivo": rastro.nome},
        )
        pausa()
    duracoes["classificacao"] = time.perf_counter() - t0
    emitir("classificacao", "Classificação concluída", {"fim": True})

    # 3. Extração --------------------------------------------------------
    emitir("extracao", "Extraindo cabeçalho, lançamentos e saldos…", {"inicio": True})
    t0 = time.perf_counter()
    for rastro, arq in zip(rastros, descobertos):
        tipo = rastro.tipo
        t_arq = time.perf_counter()
        try:
            if tipo is not None and tipo.layout in LAYOUTS_VISAO:
                emitir("extracao", f"{rastro.nome} → enviando ao Gemini Visão…", {"arquivo": rastro.nome, "ia": True})
                res, origem_ia, dur_ia = _extrair_visao(arq, tipo, config, modo, api_key, cache, novos_cache)
                rastro.origem_ia = origem_ia
                rastro.duracao_ia_original_s = dur_ia
            elif tipo is not None:
                res = extrair_documento(arq, tipo, config)
            else:
                raise RuntimeError("Arquivo não classificado")
            res.duracao_s = time.perf_counter() - t_arq
            if rastro.origem_ia == "cache" and rastro.duracao_ia_original_s:
                res.duracao_s = float(rastro.duracao_ia_original_s)
        except Exception as exc:
            res = ResultadoExtracao.falha(
                arq.caminho,
                f"Erro inesperado no processamento: {type(exc).__name__}: {exc}",
                hash_sha256=arq.hash_sha256,
                duracao_s=time.perf_counter() - t_arq,
            )
        rastro.resultado = res
        rastro.status_pos_extracao = res.status
        rastro.obs_pos_extracao = list(res.observacoes)
        emitir(
            "extracao",
            f"{rastro.nome} → saldo final {res.saldo_final if res.saldo_final is not None else '—'} ({res.metodo})",
            {"arquivo": rastro.nome, "status": res.status},
        )
        pausa()
    duracoes["extracao"] = time.perf_counter() - t0
    emitir("extracao", "Extração concluída", {"fim": True})

    # 4. Validação -------------------------------------------------------
    emitir("validacao", "Reconciliando saldos e aplicando regras de lote…", {"inicio": True})
    t0 = time.perf_counter()
    resultados = [r.resultado for r in rastros if r.resultado is not None]
    meta = validar_lote(resultados, config)
    duracoes["validacao"] = time.perf_counter() - t0
    for rastro in rastros:
        if rastro.resultado is not None and rastro.obs_validacao:
            emitir(
                "validacao",
                f"{rastro.nome} → {rastro.resultado.status.upper()}: {rastro.obs_validacao[0]}",
                {"arquivo": rastro.nome, "status": rastro.resultado.status},
            )
            pausa()
    emitir("validacao", f"Período do lote (moda): {meta.get('periodo_lote')}", {"fim": True})

    # 5. Consolidação ----------------------------------------------------
    emitir("consolidacao", "Gerando planilha no layout do modelo oficial…", {"inicio": True})
    t0 = time.perf_counter()
    planilha = gerar_planilha(
        resultados,
        pasta_saida=saida,
        modelo_path=config.modelo_planilha,
        periodo_lote=meta.get("periodo_lote"),  # type: ignore[arg-type]
    )
    pausa()
    fim = datetime.now()
    log_path, json_path = escrever_logs(
        pasta_logs=logs,
        pasta_entrada=entrada,
        resultados=resultados,
        meta_validacao=meta,
        saida_planilha=planilha,
        inicio=inicio,
        fim=fim,
        config=config,
    )
    duracoes["consolidacao"] = time.perf_counter() - t0
    emitir("consolidacao", f"Entregue: {planilha.name} + log de auditoria", {"fim": True})

    if novos_cache:
        _salvar_cache(novos_cache)

    return Execucao(
        modo=modo,
        origem=origem,
        pasta_entrada=entrada,
        pasta_trabalho=pasta_trabalho,
        inicio=inicio,
        fim=fim,
        arquivos=rastros,
        meta_validacao=meta,
        planilha=planilha,
        log_path=log_path,
        json_path=json_path,
        duracao_etapas=duracoes,
        config=config,
    )
