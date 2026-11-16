"""Extrator de visão via Google Gemini API (SDK google-genai) para PNG e PDF escaneado."""

from __future__ import annotations

import os
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Literal

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from ..classificador import TipoDocumento
from ..config import AppConfig
from ..descoberta import ArquivoDescoberto
from ..modelos import Movimento, ResultadoExtracao
from ..normalizacao import (
    normalizar_banco,
    normalizar_conta,
    normalizar_periodo,
    parse_valor,
)

PROMPT_EXTRACAO_IMAGEM = """Você é um especialista em leitura precisa de extratos bancários brasileiros em captura de tela de aplicativo.

Analise a imagem do extrato bancário em resolução original e extraia os dados estruturados com rigor absoluto:
1. "banco": nome do banco exibido no topo da tela.
2. "conta": número completo da conta exatamente como aparece, preservando todos os dígitos e o hífen (ex.: "12345-6" ou "9913355-2").
3. "periodo": período de referência do extrato no formato "AAAA-MM" (ex.: "2026-10" ou "2026-09"). Observe o cabeçalho de período e os meses abreviados dos lançamentos (ex.: "set" = 09, "out" = 10).
4. "saldo_inicial": o saldo inicial/anterior exibido no topo ou canto do extrato, em texto numérico exato (ex.: "105634.26" ou "105.634,26").
5. "saldo_final": o SALDO FINAL exibido no cartão principal do topo ("Saldo final R$ ..."), NUNCA o saldo de um lançamento isolado da lista.
6. "moeda": código ISO da moeda (padrão "BRL").
7. "lancamentos": TODOS os lançamentos visíveis na lista, na ordem em que aparecem de cima para baixo, informando para cada linha:
   - "data": data exibida na linha (ex.: "05 out")
   - "descricao": texto da descrição
   - "valor": valor com sinal explícito ("+" para crédito/entrada, "-" para débito/saída; atenção ao sinal "−" Unicode antes do valor)
   - "saldo": saldo corrente após aquele lançamento, quando exibido na linha
8. "confianca": "alta", "media" ou "baixa".
9. "observacoes": breve nota técnica apenas se houver algo ilegível, cortado ou duvidoso; caso contrário null.

Regras inegociáveis:
- Se qualquer campo ou dígito estiver ilegível ou ausente, retorne null. NUNCA invente ou adivinhe valores.
- Não decida status de aprovação; apenas transcreva exatamente o que está visível na imagem."""

_CACHE_MODELOS: dict[str, set[str]] = {}


class LancamentoImagemSchema(BaseModel):
    """Schema estruturado de um lançamento bancário lido de imagem."""

    data: str | None = Field(default=None, description="Data do lançamento exibida na linha.")
    descricao: str = Field(description="Descrição do lançamento.")
    valor: str = Field(description="Valor do lançamento com sinal '+' ou '-' (ex: '-1234.56' ou '+500.00').")
    saldo: str | None = Field(default=None, description="Saldo após o lançamento, ou null.")


class ExtratoImagemSchema(BaseModel):
    """Schema estruturado de resposta do Gemini para leitura de extrato em imagem."""

    banco: str | None = Field(default=None, description="Nome do banco.")
    conta: str | None = Field(default=None, description="Número da conta com hífen.")
    periodo: str | None = Field(default=None, description="Período no formato AAAA-MM.")
    saldo_inicial: str | None = Field(default=None, description="Saldo inicial do período.")
    saldo_final: str | None = Field(default=None, description="Saldo final do cartão de topo.")
    moeda: str = Field(default="BRL", description="Código ISO da moeda.")
    lancamentos: list[LancamentoImagemSchema] = Field(
        default_factory=list,
        description="Lista completa dos lançamentos do extrato em ordem.",
    )
    confianca: Literal["alta", "media", "baixa"] = Field(
        description="Nível de confiança visual na leitura dos dígitos."
    )
    observacoes: str | None = Field(default=None, description="Observações de legibilidade.")


def limpar_cache_modelos() -> None:
    """Limpa o cache em memória de modelos listados (útil em testes)."""
    _CACHE_MODELOS.clear()


def _normalizar_nome_modelo(nome: str) -> str:
    return nome.removeprefix("models/").strip()


def _eh_erro_cota_diaria(exc: BaseException) -> bool:
    if isinstance(exc, errors.APIError) and exc.code == 429:
        msg = str(exc)
        return "PerDay" in msg or "RESOURCE_EXHAUSTED" in msg
    return False


def _eh_erro_transitorio(exc: BaseException) -> bool:
    if _eh_erro_cota_diaria(exc):
        return False
    if isinstance(exc, errors.APIError):
        return exc.code in {408, 429, 500, 502, 503, 504}
    return isinstance(exc, (TimeoutError, ConnectionError, OSError))


def listar_modelos_disponiveis(client: genai.Client, chave_cache: str = "default") -> set[str]:
    """Lista os modelos disponíveis para a chave usando ``client.models.list()`` com cache."""
    if chave_cache in _CACHE_MODELOS:
        return _CACHE_MODELOS[chave_cache]

    nomes: set[str] = set()
    for modelo in client.models.list():
        nome = getattr(modelo, "name", None)
        if nome:
            nomes.add(_normalizar_nome_modelo(str(nome)))
    _CACHE_MODELOS[chave_cache] = nomes
    return nomes


def _mime_type_imagem(caminho: Path) -> str:
    ext = caminho.suffix.lower()
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".webp":
        return "image/webp"
    return "image/png"


def _rasterizar_pdf_para_pngs(caminho_pdf: Path) -> list[bytes]:
    """Rasteriza páginas de PDF escaneado em PNGs (~200 DPI) usando pypdfium2."""
    import pypdfium2 as pdfium

    imagens: list[bytes] = []
    doc = pdfium.PdfDocument(str(caminho_pdf))
    try:
        escala = 200 / 72
        for page in doc:
            bitmap = page.render(scale=escala)
            pil_img = bitmap.to_pil()
            buf = BytesIO()
            pil_img.save(buf, format="PNG")
            imagens.append(buf.getvalue())
            bitmap.close()
    finally:
        doc.close()
    return imagens


def _chamar_gemini_com_retry(
    client: genai.Client,
    modelo: str,
    partes_imagem: list[types.Part],
    config: AppConfig,
) -> types.GenerateContentResponse:
    thinking_cfg = None
    nivel = getattr(config.gemini, "thinking_level", "").strip().upper()
    if nivel and hasattr(types.ThinkingLevel, nivel):
        thinking_cfg = types.ThinkingConfig(thinking_level=getattr(types.ThinkingLevel, nivel))

    cfg = types.GenerateContentConfig(
        temperature=config.gemini.temperatura,
        response_mime_type="application/json",
        response_json_schema=ExtratoImagemSchema.model_json_schema(),
        thinking_config=thinking_cfg,
    )

    @retry(
        reraise=True,
        stop=stop_after_attempt(max(1, config.gemini.max_tentativas)),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        retry=retry_if_exception(_eh_erro_transitorio),
    )
    def _executar() -> types.GenerateContentResponse:
        return client.models.generate_content(
            model=modelo,
            contents=[*partes_imagem, PROMPT_EXTRACAO_IMAGEM],
            config=cfg,
        )

    return _executar()


def extrair(
    arquivo: ArquivoDescoberto,
    tipo: TipoDocumento,
    config: AppConfig,
    *,
    client_factory: Callable[[str, int], Any] | None = None,
) -> ResultadoExtracao:
    """Extrai dados de PNG (em resolução original) ou PDF escaneado via Gemini API."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key and client_factory is None:
        return ResultadoExtracao.falha(
            arquivo.caminho,
            "GEMINI_API_KEY ausente no ambiente/.env: não foi possível ler a imagem via IA",
            hash_sha256=arquivo.hash_sha256,
            formato=tipo.formato,
            metodo="gemini-visao",
        )

    timeout_ms = max(1000, int(config.gemini.timeout_segundos * 1000))
    if client_factory is not None:
        client = client_factory(api_key, timeout_ms)
    else:
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=timeout_ms,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    modelo_cfg = _normalizar_nome_modelo(config.gemini.modelo)
    chave_cache = api_key[-8:] if api_key else "mock"

    try:
        modelos_disponiveis = listar_modelos_disponiveis(client, chave_cache=chave_cache)
    except Exception as exc:
        return ResultadoExtracao.falha(
            arquivo.caminho,
            f"Falha ao consultar modelos disponíveis no Gemini: {type(exc).__name__}: {exc}",
            hash_sha256=arquivo.hash_sha256,
            formato=tipo.formato,
            metodo=f"gemini-visao:{modelo_cfg}",
        )

    if modelos_disponiveis and modelo_cfg not in modelos_disponiveis:
        sugestoes = ", ".join(sorted(m for m in modelos_disponiveis if "flash" in m)[:5]) or ", ".join(
            sorted(modelos_disponiveis)[:5]
        )
        return ResultadoExtracao.falha(
            arquivo.caminho,
            (
                f"Modelo Gemini '{modelo_cfg}' configurado em config.yaml não está disponível "
                f"para a chave informada (disponíveis: {sugestoes})"
            ),
            hash_sha256=arquivo.hash_sha256,
            formato=tipo.formato,
            metodo=f"gemini-visao:{modelo_cfg}",
        )

    modelos_candidatos = [modelo_cfg]
    for fb in config.gemini.modelos_fallback:
        fb_norm = _normalizar_nome_modelo(fb)
        if fb_norm and fb_norm not in modelos_candidatos:
            if not modelos_disponiveis or fb_norm in modelos_disponiveis:
                modelos_candidatos.append(fb_norm)

    if tipo.layout == "pdf_escaneado":
        imagens_bytes = _rasterizar_pdf_para_pngs(arquivo.caminho)
        partes = [types.Part.from_bytes(data=img, mime_type="image/png") for img in imagens_bytes]
    else:
        partes = [
            types.Part.from_bytes(
                data=arquivo.caminho.read_bytes(),
                mime_type=_mime_type_imagem(arquivo.caminho),
            )
        ]

    response = None
    modelo_usado = modelo_cfg
    ultimo_erro: Exception | None = None
    for idx_mod, candidato in enumerate(modelos_candidatos):
        try:
            response = _chamar_gemini_com_retry(client, candidato, partes, config)
            modelo_usado = candidato
            break
        except Exception as exc:
            ultimo_erro = exc
            # Só tenta modelo fallback se o erro for cota/timeout/servidor no modelo anterior
            eh_elegivel_fallback = (
                _eh_erro_cota_diaria(exc)
                or _eh_erro_transitorio(exc)
                or "Timeout" in type(exc).__name__
            )
            if not eh_elegivel_fallback or idx_mod == len(modelos_candidatos) - 1:
                return ResultadoExtracao.falha(
                    arquivo.caminho,
                    f"Falha na chamada à API Gemini após retries: {type(exc).__name__}: {exc}",
                    hash_sha256=arquivo.hash_sha256,
                    formato=tipo.formato,
                    metodo=f"gemini-visao:{candidato}",
                )

    if response is None:
        return ResultadoExtracao.falha(
            arquivo.caminho,
            f"Falha na chamada à API Gemini: {ultimo_erro}",
            hash_sha256=arquivo.hash_sha256,
            formato=tipo.formato,
            metodo=f"gemini-visao:{modelo_usado}",
        )

    usage = getattr(response, "usage_metadata", None)
    tokens_in = int(getattr(usage, "prompt_token_count", 0) or 0)
    tokens_cand = int(getattr(usage, "candidates_token_count", 0) or 0)
    tokens_think = int(getattr(usage, "thoughts_token_count", 0) or 0)
    tokens_out = tokens_cand + tokens_think
    tokens_tot = int(getattr(usage, "total_token_count", 0) or (tokens_in + tokens_out))

    texto_json = getattr(response, "text", None) or ""
    try:
        dados = ExtratoImagemSchema.model_validate_json(texto_json)
    except Exception as exc:
        res_err = ResultadoExtracao.falha(
            arquivo.caminho,
            f"Resposta inválida da API Gemini fora do schema esperado: {type(exc).__name__}: {exc}",
            hash_sha256=arquivo.hash_sha256,
            formato=tipo.formato,
            metodo=f"gemini-visao:{modelo_usado}",
        )
        res_err.chamadas_ia = 1
        res_err.tokens_entrada = tokens_in
        res_err.tokens_saida = tokens_out
        res_err.tokens_total = tokens_tot
        return res_err

    movimentos: list[Movimento] = []
    for lanc in dados.lancamentos:
        val = parse_valor(lanc.valor)
        if val is None:
            continue
        saldo_lanc = parse_valor(lanc.saldo) if lanc.saldo is not None else None
        movimentos.append(
            Movimento(
                data=lanc.data,
                descricao=lanc.descricao.strip(),
                valor=val,
                saldo=saldo_lanc,
            )
        )

    periodo_norm = normalizar_periodo(dados.periodo) if dados.periodo else None
    resultado = ResultadoExtracao(
        arquivo=arquivo.nome,
        caminho=arquivo.caminho,
        hash_sha256=arquivo.hash_sha256,
        formato=tipo.formato,
        banco=normalizar_banco(dados.banco),
        conta=normalizar_conta(dados.conta),
        periodo=periodo_norm,
        saldo_inicial=parse_valor(dados.saldo_inicial),
        saldo_final=parse_valor(dados.saldo_final),
        movimentos=movimentos,
        moeda=(dados.moeda or "BRL").strip().upper(),
        confianca_ia=dados.confianca,
        metodo=f"gemini-visao:{modelo_usado}",
        chamadas_ia=1,
        tokens_entrada=tokens_in,
        tokens_saida=tokens_out,
        tokens_total=tokens_tot,
    )

    if dados.confianca == "baixa":
        resultado.adicionar_observacao("revisar", "Leitura por IA com confiança baixa")

    return resultado
