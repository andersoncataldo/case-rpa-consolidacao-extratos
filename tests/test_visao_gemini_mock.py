"""Testes do extrator Gemini Vision com cliente simulado (sem custo de API)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import errors

from rpa_extratos.classificador import TipoDocumento
from rpa_extratos.config import AppConfig
from rpa_extratos.descoberta import ArquivoDescoberto
from rpa_extratos.extratores.visao_gemini import extrair, limpar_cache_modelos
from rpa_extratos.validacao import validar_lote


class _FakeModels:
    def __init__(self, modelos: list[str], respostas: list[object]) -> None:
        self._modelos = [SimpleNamespace(name=f"models/{m}") for m in modelos]
        self._respostas = list(respostas)
        self.chamadas = 0

    def list(self):  # type: ignore[no-untyped-def]
        return iter(self._modelos)

    def generate_content(self, **kwargs):  # type: ignore[no-untyped-def]
        self.chamadas += 1
        item = self._respostas.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _fake_response(payload: dict[str, object], tin: int = 1200, tout: int = 350) -> object:
    return SimpleNamespace(
        text=json.dumps(payload),
        usage_metadata=SimpleNamespace(
            prompt_token_count=tin,
            candidates_token_count=tout,
            total_token_count=tin + tout,
        ),
    )


def test_visao_gemini_sem_chave_retorna_falhou(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    limpar_cache_modelos()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    img = tmp_path / "extrato.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    res = extrair(
        ArquivoDescoberto(img, img.name, "hash1"),
        TipoDocumento("Imagem", "imagem_visao"),
        AppConfig(),
    )
    assert res.status == "falhou"
    assert "GEMINI_API_KEY" in res.observacao_texto


def test_visao_gemini_modelo_inexistente_falha_isoladamente(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    limpar_cache_modelos()
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    img = tmp_path / "extrato.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    fake_models = _FakeModels(["gemini-3.5-flash-lite"], [])
    cfg = AppConfig()
    cfg.gemini.modelo = "gemini-modelo-inexistente"

    res = extrair(
        ArquivoDescoberto(img, img.name, "hash2"),
        TipoDocumento("Imagem", "imagem_visao"),
        cfg,
        client_factory=lambda _k, _t: SimpleNamespace(models=fake_models),
    )
    assert res.status == "falhou"
    assert "não está disponível" in res.observacao_texto


def test_visao_gemini_extrai_reconcilia_e_registra_tokens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    limpar_cache_modelos()
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    img = tmp_path / "app_ipe.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    payload = {
        "banco": "Banco Aurora",
        "conta": "34930-3",
        "periodo": "2026-10",
        "saldo_inicial": "200000.00",
        "saldo_final": "271350.74",
        "moeda": "BRL",
        "lancamentos": [
            {"data": "02 out", "descricao": "BOLETOS", "valor": "+71350.74", "saldo": "271350.74"}
        ],
        "confianca": "alta",
        "observacoes": None,
    }
    fake_models = _FakeModels(
        ["gemini-3.8-flash"],
        [
            errors.APIError(429, {"error": {"message": "rate limit"}}),
            _fake_response(payload, tin=1500, tout=400),
        ],
    )

    cfg = AppConfig()
    cfg.gemini.modelo = "gemini-3.8-flash"
    cfg.gemini.max_tentativas = 2

    res = extrair(
        ArquivoDescoberto(img, img.name, "hash3"),
        TipoDocumento("Imagem", "imagem_visao"),
        cfg,
        client_factory=lambda _k, _t: SimpleNamespace(models=fake_models),
    )
    validar_lote([res], cfg)

    assert fake_models.chamadas == 2
    assert res.status == "ok"
    assert res.banco == "Banco Aurora"
    assert res.conta == "34930-3"
    assert res.saldo_final == Decimal("271350.74")
    assert res.chamadas_ia == 1
    assert res.tokens_entrada == 1500
    assert res.tokens_saida == 400
    assert res.tokens_total == 1900


def test_lote_png_fora_do_periodo_e_conta_fora_do_padrao_vira_revisar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    limpar_cache_modelos()
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    img_ok = tmp_path / "out.png"
    img_ok.write_bytes(b"\x89PNG\r\n\x1a\nfake1")
    img_set = tmp_path / "set.png"
    img_set.write_bytes(b"\x89PNG\r\n\x1a\nfake2")

    payload_ok = {
        "banco": "Banco Aurora",
        "conta": "34930-3",
        "periodo": "2026-10",
        "saldo_inicial": "100.00",
        "saldo_final": "150.00",
        "moeda": "BRL",
        "lancamentos": [{"data": "02 out", "descricao": "PIX", "valor": "+50.00", "saldo": "150.00"}],
        "confianca": "alta",
        "observacoes": None,
    }
    payload_set = {
        "banco": "Banco Litoral",
        "conta": "9913355-2",
        "periodo": "2026-09",
        "saldo_inicial": "200.00",
        "saldo_final": "250.00",
        "moeda": "BRL",
        "lancamentos": [{"data": "04 set", "descricao": "PIX", "valor": "+50.00", "saldo": "250.00"}],
        "confianca": "alta",
        "observacoes": None,
    }

    fake_models = _FakeModels(
        ["gemini-3.8-flash"],
        [_fake_response(payload_ok), _fake_response(payload_set)],
    )
    cfg = AppConfig()
    cfg.gemini.modelo = "gemini-3.8-flash"

    r_ok = extrair(
        ArquivoDescoberto(img_ok, img_ok.name, "h1"),
        TipoDocumento("Imagem", "imagem_visao"),
        cfg,
        client_factory=lambda _k, _t: SimpleNamespace(models=fake_models),
    )
    r_set = extrair(
        ArquivoDescoberto(img_set, img_set.name, "h2"),
        TipoDocumento("Imagem", "imagem_visao"),
        cfg,
        client_factory=lambda _k, _t: SimpleNamespace(models=fake_models),
    )

    from rpa_extratos.modelos import ResultadoExtracao

    r_extra = ResultadoExtracao(
        arquivo="ref.pdf",
        caminho=tmp_path / "ref.pdf",
        hash_sha256="h3",
        formato="PDF",
        banco="Banco Planalto",
        conta="11111-1",
        periodo="2026-10",
        saldo_inicial=Decimal("10.00"),
        saldo_final=Decimal("10.00"),
    )
    meta = validar_lote([r_ok, r_set, r_extra], cfg)
    assert meta["periodo_lote"] == "2026-10"
    assert r_ok.status == "ok"
    assert r_set.status == "revisar"
    assert "2026-09" in r_set.observacao_texto
    assert "9913355-2" in r_set.observacao_texto


def test_visao_gemini_resposta_json_invalida_retorna_falhou(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    limpar_cache_modelos()
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    img = tmp_path / "corrompida.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    bad_response = SimpleNamespace(
        text="{invalido",
        usage_metadata=SimpleNamespace(prompt_token_count=100, candidates_token_count=10, total_token_count=110),
    )
    fake_models = _FakeModels(["gemini-3.8-flash"], [bad_response])
    cfg = AppConfig()
    cfg.gemini.modelo = "gemini-3.8-flash"

    res = extrair(
        ArquivoDescoberto(img, img.name, "h_bad"),
        TipoDocumento("Imagem", "imagem_visao"),
        cfg,
        client_factory=lambda _k, _t: SimpleNamespace(models=fake_models),
    )
    assert res.status == "falhou"
    assert "schema" in res.observacao_texto.lower()
    assert res.chamadas_ia == 1
    assert res.tokens_total == 110
