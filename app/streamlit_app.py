"""Painel Streamlit: percurso visual da automação de consolidação de extratos.

Execute com:  streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import html
import io
import os
import shutil
import sys
import tempfile
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import motor  # noqa: E402
from motor import ETAPAS, ROOT, Execucao, RastroArquivo  # noqa: E402
from rpa_extratos.normalizacao import formatar_moeda_br  # noqa: E402

os.chdir(ROOT)

st.set_page_config(
    page_title="RPA Extratos · Percurso da Automação",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Estilo
# ---------------------------------------------------------------------------

CSS = """
<style>
.block-container {padding-top: 2rem; max-width: 1400px;}
.hero h1 {font-size: 2rem; margin-bottom: 0;}
.hero p {color:#475569; margin-top:.2rem;}
.fluxo {display:flex; flex-wrap:wrap; gap:.35rem; align-items:stretch; margin:.6rem 0 1rem;}
.no {flex:1 1 120px; background:#fff; border:2px solid #e2e8f0; border-radius:14px; padding:.75rem .5rem;
     text-align:center; min-width:115px; transition:all .35s ease;}
.no .ic {font-size:1.7rem; line-height:1.2;}
.no .tt {font-weight:700; font-size:.92rem; color:#1e293b;}
.no .tc {font-size:.7rem; color:#64748b; min-height:1.9em;}
.no .mt {margin-top:.35rem; font-size:.8rem; font-weight:700; color:#334155; min-height:1.2em;}
.no.pendente {opacity:.5; filter:grayscale(1);}
.no.ativo {border-color:#2563eb; background:#eff6ff; box-shadow:0 0 0 5px rgba(37,99,235,.15);
           animation:pulso 1.1s ease-in-out infinite;}
.no.feito {border-color:#16a34a; background:#f0fdf4;}
.no.feito .tt::after {content:" ✓"; color:#16a34a;}
.no.io {background:#f1f5f9; border-style:dashed;}
.no.io.feito {background:#ecfdf5; border-style:solid;}
.seta {display:flex; align-items:center; padding:0 .25rem; color:#cbd5e1; font-size:1.3rem; font-weight:700;}
.seta.feito {color:#16a34a;} .seta.ativo {color:#2563eb;}
@keyframes pulso {0%,100% {transform:scale(1);} 50% {transform:scale(1.045);}}
.feed {font-family:ui-monospace,Consolas,monospace; font-size:.76rem; background:#0f172a; color:#e2e8f0;
       border-radius:10px; padding:.7rem .9rem; height:250px; overflow:hidden; line-height:1.5;}
.feed .t {color:#64748b;} .feed .k-descoberta {color:#93c5fd;} .feed .k-classificacao {color:#c4b5fd;}
.feed .k-extracao {color:#fcd34d;} .feed .k-validacao {color:#86efac;} .feed .k-consolidacao {color:#f9a8d4;}
.badge {display:inline-block; padding:.1rem .6rem; border-radius:999px; font-size:.75rem; font-weight:700;}
.b-ok {background:#C6EFCE; color:#006100;} .b-revisar {background:#FFEB9C; color:#9C6500;}
.b-falhou {background:#FFC7CE; color:#9C0006;}
.jornada {display:flex; flex-wrap:wrap; gap:.35rem; align-items:stretch; margin:.4rem 0 1rem;}
.passo {flex:1 1 140px; background:#fff; border:1px solid #e2e8f0; border-left:5px solid #16a34a; border-radius:10px;
        padding:.55rem .7rem; font-size:.8rem; color:#334155; min-width:130px;}
.passo b {display:block; font-size:.85rem; color:#0f172a; margin-bottom:.15rem;}
.passo.revisar {border-left-color:#d97706;} .passo.falhou {border-left-color:#dc2626;}
.recon {background:#fff; border:1px solid #e2e8f0; border-radius:12px; padding:.8rem 1rem; font-size:.92rem;}
.recon table {width:100%;} .recon td {padding:.15rem .3rem;} .recon td.v {text-align:right; font-family:ui-monospace,Consolas,monospace;}
.recon tr.tot td {border-top:1px solid #cbd5e1; font-weight:700;}
.dica {background:#eff6ff; border:1px solid #bfdbfe; border-radius:10px; padding:.6rem .9rem; color:#1e3a8a; font-size:.88rem;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

RITMOS = {"Apresentação (pausado)": 0.30, "Normal": 0.10, "Instantâneo": 0.0}
CORES_STATUS = {
    "ok": "background-color:#C6EFCE; color:#006100; font-weight:700",
    "revisar": "background-color:#FFEB9C; color:#9C6500; font-weight:700",
    "falhou": "background-color:#FFC7CE; color:#9C0006; font-weight:700",
}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def brl(valor: Decimal | None) -> str:
    return f"R$ {formatar_moeda_br(valor)}" if valor is not None else "—"


def badge(status: str | None) -> str:
    s = status or "—"
    return f'<span class="badge b-{s}">{s.upper()}</span>'


def estilizar_status(df: pd.DataFrame, coluna: str = "Status") -> Any:
    return df.style.map(lambda v: CORES_STATUS.get(str(v), ""), subset=[coluna])


def obter_chave() -> tuple[str, str]:
    """Retorna (chave, origem) para o modo Ao vivo."""
    manual = (st.session_state.get("chave_manual") or "").strip()
    if manual:
        return manual, "informada na barra lateral"
    try:
        segredo = str(st.secrets.get("GEMINI_API_KEY", "")).strip()
    except Exception:
        segredo = ""
    if segredo:
        return segredo, "Streamlit secrets"
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    env = os.getenv("GEMINI_API_KEY", "").strip()
    if env and env != "sua_chave_aqui":
        return env, "arquivo .env"
    return "", ""


def classificar_regra(obs: str) -> str:
    o = obs.lower()
    if "não é um extrato" in o:
        return "Documento não-extrato"
    if "duplicata" in o or "duplicados" in o:
        return "Duplicidade"
    if "período" in o and "diferente" in o:
        return "Período do lote"
    if "fora do padrão" in o:
        return "Padrão de conta"
    if "reconcilia" in o or "saldo corrente" in o or "total de" in o:
        return "Reconciliação aritmética"
    if "negativo" in o:
        return "Saldo negativo intradia (informativo)"
    if "confiança baixa" in o:
        return "Confiança da IA"
    if "ausentes" in o:
        return "Campos obrigatórios"
    return "Outros"


# ---------------------------------------------------------------------------
# Diagrama do fluxo
# ---------------------------------------------------------------------------


def estado_inicial() -> dict[str, Any]:
    return {
        "status": {k: "pendente" for k in ["entrada", *[e[0] for e in ETAPAS], "entrega"]},
        "metrica": {k: "" for k in ["entrada", *[e[0] for e in ETAPAS], "entrega"]},
    }


def html_fluxo(estado: dict[str, Any]) -> str:
    nos = [("entrada", "Entrada", "📥", "PDF · Excel · PNG", True)]
    nos += [(k, t, i, tc, False) for k, t, i, tc in ETAPAS]
    nos += [("entrega", "Entrega", "📤", "extrato calculado", True)]
    partes = ['<div class="fluxo">']
    for idx, (k, titulo, icone, tecno, io_no) in enumerate(nos):
        st_no = estado["status"][k]
        if idx > 0:
            anterior = estado["status"][nos[idx - 1][0]]
            cls_seta = "feito" if anterior == "feito" and st_no != "pendente" else ("ativo" if st_no == "ativo" else "")
            partes.append(f'<div class="seta {cls_seta}">➜</div>')
        partes.append(
            f'<div class="no {st_no} {"io" if io_no else ""}"><div class="ic">{icone}</div>'
            f'<div class="tt">{titulo}</div><div class="tc">{html.escape(tecno)}</div>'
            f'<div class="mt">{html.escape(estado["metrica"][k])}</div></div>'
        )
    partes.append("</div>")
    return "".join(partes)


def html_feed(eventos: list[tuple[str, str, str]], limite: int = 13) -> str:
    linhas = []
    for hora, etapa, msg in eventos[-limite:]:
        linhas.append(
            f'<div><span class="t">{hora}</span> <span class="k-{etapa}">[{etapa}]</span> {html.escape(msg)}</div>'
        )
    return '<div class="feed">' + "".join(linhas) + "</div>"


def estado_final(ex: Execucao) -> dict[str, Any]:
    est = estado_inicial()
    for k in est["status"]:
        est["status"][k] = "feito"
    res = ex.resultados
    cont = Counter(r.status for r in res)
    n_ia = sum(1 for a in ex.arquivos if a.motor == "Gemini Visão")
    layouts = {a.tipo.layout for a in ex.arquivos if a.tipo}
    est["metrica"].update(
        entrada=f"{len(ex.arquivos)} arquivos",
        descoberta=f"{len({a.hash_sha256 for a in ex.arquivos})} hashes únicos",
        classificacao=f"{len(layouts)} layouts",
        extracao=f"{len(res) - n_ia} determ. · {n_ia} IA",
        validacao=f"{cont.get('revisar', 0) + cont.get('falhou', 0)} alertas",
        consolidacao=f"{len(res)} linhas",
        entrega=ex.planilha.name,
    )
    return est


# ---------------------------------------------------------------------------
# Execução com animação
# ---------------------------------------------------------------------------


def preparar_entrada(origem: str, uploads: list[Any]) -> tuple[Path, Path]:
    anterior: Execucao | None = st.session_state.get("execucao")
    if anterior is not None and anterior.pasta_trabalho.exists():
        shutil.rmtree(anterior.pasta_trabalho, ignore_errors=True)
    trabalho = Path(tempfile.mkdtemp(prefix="rpa_painel_"))
    if origem == "case":
        return motor.garantir_entrada_case(), trabalho
    entrada = trabalho / "entrada"
    entrada.mkdir(parents=True, exist_ok=True)
    for idx, up in enumerate(uploads, start=1):
        nome_base = Path(up.name).name
        destino = entrada / nome_base
        if destino.exists():
            destino = entrada / f"{destino.stem} ({idx}){destino.suffix}"
        destino.write_bytes(up.getbuffer())
    return entrada, trabalho


def rodar(modo: str, origem: str, uploads: list[Any], ritmo: float, chave: str) -> None:
    entrada, trabalho = preparar_entrada(origem, uploads)
    estado = estado_inicial()
    estado["status"]["entrada"] = "feito"
    total = len([p for p in entrada.rglob("*") if p.is_file()])
    estado["metrica"]["entrada"] = f"{total} arquivos"
    cont = {"desc": 0, "cls": 0, "ext": 0, "ia": 0, "alertas": 0}
    eventos: list[tuple[str, str, str]] = []

    ph_fluxo = st.empty()
    ph_prog = st.empty()
    ph_feed = st.empty()
    pesos = {"descoberta": 0.1, "classificacao": 0.2, "extracao": 0.5, "validacao": 0.1, "consolidacao": 0.1}
    base = {"descoberta": 0.0, "classificacao": 0.1, "extracao": 0.3, "validacao": 0.8, "consolidacao": 0.9}

    def on_evento(etapa: str, msg: str, dados: dict[str, Any]) -> None:
        from datetime import datetime

        if dados.get("inicio"):
            estado["status"][etapa] = "ativo"
        frac = 0.0
        if dados.get("arquivo"):
            if etapa == "descoberta":
                cont["desc"] += 1
                estado["metrica"][etapa] = f"{cont['desc']} arquivos"
                frac = cont["desc"] / max(total, 1)
            elif etapa == "classificacao":
                cont["cls"] += 1
                estado["metrica"][etapa] = f"{cont['cls']}/{cont['desc']}"
                frac = cont["cls"] / max(cont["desc"], 1)
            elif etapa == "extracao" and not dados.get("ia"):
                cont["ext"] += 1
                estado["metrica"][etapa] = f"{cont['ext']}/{cont['desc']} · {cont['ia']} IA"
                frac = cont["ext"] / max(cont["desc"], 1)
            elif etapa == "extracao" and dados.get("ia"):
                cont["ia"] += 1
            elif etapa == "validacao":
                if dados.get("status") in {"revisar", "falhou"}:
                    cont["alertas"] += 1
                estado["metrica"][etapa] = f"{cont['alertas']} alertas"
        if dados.get("fim"):
            estado["status"][etapa] = "feito"
            frac = 1.0
            if etapa == "consolidacao":
                estado["status"]["entrega"] = "feito"
                estado["metrica"]["entrega"] = msg.replace("Entregue: ", "").split(" +")[0]
                estado["metrica"][etapa] = "planilha + log"
        eventos.append((datetime.now().strftime("%H:%M:%S"), etapa, msg))
        ph_fluxo.markdown(html_fluxo(estado), unsafe_allow_html=True)
        titulo = next(t for k, t, _, _ in ETAPAS if k == etapa)
        ph_prog.progress(min(1.0, base[etapa] + pesos[etapa] * frac), text=f"Etapa atual: {titulo} — {msg}")
        ph_feed.markdown(html_feed(eventos), unsafe_allow_html=True)

    ph_fluxo.markdown(html_fluxo(estado), unsafe_allow_html=True)
    try:
        ex = motor.executar(
            entrada,
            trabalho,
            modo=modo,
            origem=origem,
            api_key=chave or None,
            ritmo_s=ritmo,
            on_evento=on_evento,
        )
    except Exception as exc:  # erro de lote (ex.: pasta vazia)
        st.error(f"Não foi possível executar a automação: {type(exc).__name__}: {exc}")
        return
    st.session_state["execucao"] = ex
    st.session_state["eventos"] = eventos
    ph_fluxo.empty()
    ph_prog.empty()
    ph_feed.empty()


# ---------------------------------------------------------------------------
# Pré-visualização de documentos
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def renderizar_pdf(caminho: str, _sha: str, max_paginas: int = 3) -> list[bytes]:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(caminho)
    imgs: list[bytes] = []
    try:
        for i in range(min(len(doc), max_paginas)):
            pil = doc[i].render(scale=1.6).to_pil()
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            imgs.append(buf.getvalue())
    finally:
        doc.close()
    return imgs


@st.cache_data(show_spinner=False)
def ler_excel(caminho: str, _sha: str) -> dict[str, list[list[str]]]:
    import openpyxl

    wb = openpyxl.load_workbook(caminho, data_only=True, read_only=True)
    try:
        abas = {}
        for ws in wb.worksheets:
            abas[ws.title] = [["" if c is None else str(c) for c in row] for row in ws.iter_rows(values_only=True)]
        return abas
    finally:
        wb.close()


def mostrar_documento(rastro: RastroArquivo) -> None:
    formato = rastro.tipo.formato if rastro.tipo else ""
    caminho = str(rastro.caminho)
    try:
        if formato == "Imagem":
            st.image(caminho, width="stretch")
        elif formato == "PDF":
            for img in renderizar_pdf(caminho, rastro.hash_sha256):
                st.image(img, width="stretch")
        elif formato == "Excel":
            abas = ler_excel(caminho, rastro.hash_sha256)
            tabs = st.tabs([f"🗂️ {n}" for n in abas])
            for tab, (nome, linhas) in zip(tabs, abas.items()):
                with tab:
                    largura = max((len(r) for r in linhas), default=0)
                    df = pd.DataFrame([r + [""] * (largura - len(r)) for r in linhas])
                    st.dataframe(df, hide_index=True, width="stretch", height=420)
        else:
            st.info("Pré-visualização indisponível para este formato.")
    except Exception as exc:
        st.warning(f"Não foi possível pré-visualizar o arquivo: {exc}")


# ---------------------------------------------------------------------------
# Seções de detalhe
# ---------------------------------------------------------------------------


def secao_descoberta(ex: Execucao) -> None:
    hashes = Counter(a.hash_sha256 for a in ex.arquivos)
    c = st.columns(4)
    c[0].metric("Arquivos encontrados", len(ex.arquivos))
    c[1].metric("Hashes únicos (SHA-256)", len(hashes))
    c[2].metric("Cópias idênticas", sum(n - 1 for n in hashes.values() if n > 1))
    c[3].metric("Tempo da etapa", f"{ex.duracao_etapas['descoberta']:.2f}s")
    st.markdown(
        '<div class="dica">A pasta de entrada é varrida recursivamente (temporários <code>~$*</code> e ocultos são '
        "ignorados). Cada arquivo recebe uma <b>impressão digital SHA-256</b>, usada depois para detectar "
        "duplicatas e garantir trilha de auditoria.</div>",
        unsafe_allow_html=True,
    )
    df = pd.DataFrame(
        [
            {
                "Arquivo": a.nome,
                "Tamanho (KB)": round(a.tamanho_bytes / 1024, 1),
                "SHA-256 (12)": a.hash_sha256[:12],
                "Duplicado": "⚠️ sim" if hashes[a.hash_sha256] > 1 else "",
            }
            for a in ex.arquivos
        ]
    )
    st.dataframe(df, hide_index=True, width="stretch")


def secao_classificacao(ex: Execucao) -> None:
    st.markdown(
        '<div class="dica">O <b>nome do arquivo nunca é usado</b> para decidir o tratamento. A automação lê os '
        "<i>magic bytes</i> (assinatura binária) e o conteúdo — abas do Excel, rótulos do PDF — para escolher "
        "entre 6 layouts e o motor de extração adequado.</div>",
        unsafe_allow_html=True,
    )
    col1, col2 = st.columns([2, 3])
    with col1:
        cont = Counter(a.descricao_layout for a in ex.arquivos)
        df_c = pd.DataFrame({"Layout": list(cont), "Arquivos": list(cont.values())}).set_index("Layout")
        st.bar_chart(df_c, horizontal=True, height=300)
    with col2:
        df = pd.DataFrame(
            [
                {
                    "Arquivo": a.nome,
                    "Assinatura (bytes)": a.magic_hex[:23],
                    "Formato": a.tipo.formato if a.tipo else "—",
                    "Layout detectado": a.descricao_layout,
                    "Motor": a.motor,
                }
                for a in ex.arquivos
            ]
        )
        st.dataframe(df, hide_index=True, width="stretch", height=300)


def secao_extracao(ex: Execucao) -> None:
    res = ex.resultados
    n_ia = sum(1 for a in ex.arquivos if a.motor == "Gemini Visão")
    tokens = sum(r.tokens_total for r in res)
    cfg = ex.config.gemini
    custo = sum(r.tokens_entrada for r in res) / 1e6 * cfg.custo_por_1m_entrada_usd + sum(
        r.tokens_saida for r in res
    ) / 1e6 * cfg.custo_por_1m_saida_usd
    c = st.columns(4)
    c[0].metric("Determinísticos (Excel/PDF)", len(res) - n_ia)
    c[1].metric("Via IA (Gemini Visão)", n_ia)
    c[2].metric("Tokens de IA", f"{tokens:,}".replace(",", "."))
    c[3].metric("Custo de IA do lote", f"US$ {custo:.4f}")
    st.markdown(
        '<div class="dica"><b>Determinístico primeiro, IA só onde é necessário:</b> Excel (openpyxl) e PDF com texto '
        "(pdfplumber) são lidos por regras, sem custo. Apenas os prints de aplicativo vão ao Gemini "
        "(<code>temperature=0</code>, saída em JSON Schema validada por Pydantic) — e mesmo assim o resultado passa "
        "pela reconciliação aritmética na etapa seguinte.</div>",
        unsafe_allow_html=True,
    )
    if ex.modo == "demo" and n_ia:
        st.caption(
            "🎬 Modo Demonstração: as respostas do Gemini para as imagens vêm do cache de uma execução real "
            "(`demo/cache_gemini.json`). Todo o restante foi processado agora."
        )
    df = pd.DataFrame(
        [
            {
                "Arquivo": a.nome,
                "Método": a.resultado.metodo,
                "Banco": a.resultado.banco or "—",
                "Conta": a.resultado.conta or "—",
                "Período": a.resultado.periodo or "—",
                "Saldo inicial": brl(a.resultado.saldo_inicial),
                "Saldo final": brl(a.resultado.saldo_final),
                "Lançamentos": len(a.resultado.movimentos),
                "Duração (s)": round(a.resultado.duracao_s, 3),
                "Status": a.status_pos_extracao,
            }
            for a in ex.arquivos
            if a.resultado
        ]
    )
    st.dataframe(estilizar_status(df), hide_index=True, width="stretch")


REGRAS = [
    ("Reconciliação aritmética", "saldo inicial + Σ lançamentos = saldo final (tolerância R$ 0,01), saldos linha a linha e totais declarados"),
    ("Período do lote", "período diferente da moda do lote (calculada dinamicamente)"),
    ("Padrão de conta", "conta no formato 5 dígitos + DV"),
    ("Duplicidade", "mesmo SHA-256 ou mesma conta/período em arquivos diferentes"),
    ("Documento não-extrato", "comunicados e documentos sem conta/saldo"),
    ("Saldo negativo intradia (informativo)", "saldo ficou negativo no mês, mas fechou positivo (mantém OK)"),
    ("Confiança da IA", "leitura por IA com confiança baixa"),
    ("Campos obrigatórios", "banco, conta ou período ausentes"),
]


def secao_validacao(ex: Execucao) -> None:
    res = ex.resultados
    cont = Counter(r.status for r in res)
    c = st.columns(4)
    c[0].metric("Período do lote (moda)", ex.meta_validacao.get("periodo_lote") or "—")
    c[1].metric("✅ OK", cont.get("ok", 0))
    c[2].metric("⚠️ Revisar", cont.get("revisar", 0))
    c[3].metric("❌ Falhou", cont.get("falhou", 0))
    st.markdown(
        '<div class="dica">Valores monetários em <code>Decimal</code> (sem erro de ponto flutuante). Precedência de '
        "status: <b>falhou &gt; revisar &gt; ok</b>. Um erro em um arquivo nunca interrompe o lote: ele vira uma "
        "linha com o motivo na Observação.</div>",
        unsafe_allow_html=True,
    )
    alertas = []
    for a in ex.arquivos:
        if not a.resultado:
            continue
        for o in a.resultado.observacoes:
            alertas.append(
                {
                    "Arquivo": a.nome,
                    "Status": a.resultado.status,
                    "Regra": classificar_regra(o),
                    "Detectado em": "Extração" if o in a.obs_pos_extracao else "Validação",
                    "Observação": o,
                }
            )
    ocorr = Counter(al["Regra"] for al in alertas)
    col1, col2 = st.columns([2, 3])
    with col1:
        st.markdown("**Regras aplicadas ao lote**")
        st.dataframe(
            pd.DataFrame(
                [{"Regra": r, "O que verifica": d, "Ocorrências": ocorr.get(r, 0)} for r, d in REGRAS]
            ),
            hide_index=True,
            width="stretch",
        )
    with col2:
        st.markdown("**Ocorrências encontradas**")
        if alertas:
            st.dataframe(estilizar_status(pd.DataFrame(alertas)), hide_index=True, width="stretch")
        else:
            st.success("Nenhuma ocorrência: todos os extratos reconciliaram.")
        if ex.meta_validacao.get("duplicidades"):
            st.caption("Duplicidades: " + "; ".join(ex.meta_validacao["duplicidades"]))


def ler_planilha(caminho: Path) -> pd.DataFrame:
    import openpyxl

    wb = openpyxl.load_workbook(caminho, data_only=True)
    try:
        ws = wb["Consolidado"]
        linhas = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    cab = [str(c) for c in linhas[0]]
    df = pd.DataFrame(linhas[1:], columns=cab)
    col_saldo = next((c for c in cab if "saldo" in c.lower()), None)
    if col_saldo:
        df[col_saldo] = df[col_saldo].map(
            lambda v: "—" if pd.isna(v) or str(v).strip() == "" else brl(Decimal(str(v)).quantize(Decimal("0.01")))
        )
    return df.fillna("")


def secao_consolidacao(ex: Execucao) -> None:
    st.markdown(
        '<div class="dica">A planilha é gerada a partir do <b>modelo oficial</b> (mesmo layout e formatação), uma '
        "linha por arquivo, Conta gravada como texto e Status colorido. Junto dela, um log legível (.log) e um log "
        "estruturado (.json) com hash, método, duração, tokens e custo de cada arquivo.</div>",
        unsafe_allow_html=True,
    )
    df = ler_planilha(ex.planilha)
    col_status = next((c for c in df.columns if c.lower() == "status"), None)
    st.dataframe(
        estilizar_status(df, col_status) if col_status else df, hide_index=True, width="stretch", height=460
    )
    c = st.columns(3)
    c[0].download_button(
        f"⬇️ Baixar {ex.planilha.name}",
        ex.planilha.read_bytes(),
        file_name=ex.planilha.name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        type="primary",
    )
    c[1].download_button(
        "⬇️ Log de auditoria (.log)", ex.log_path.read_bytes(), file_name=ex.log_path.name, width="stretch"
    )
    c[2].download_button(
        "⬇️ Log estruturado (.json)",
        ex.json_path.read_bytes(),
        file_name=ex.json_path.name,
        mime="application/json",
        width="stretch",
    )
    with st.expander("Ver log de auditoria gerado"):
        st.code(ex.log_path.read_text(encoding="utf-8"), language="text")


# ---------------------------------------------------------------------------
# Rastreio individual
# ---------------------------------------------------------------------------


def html_jornada(a: RastroArquivo, linha: int) -> str:
    r = a.resultado
    st_final = r.status if r else "falhou"
    passos = [
        ("📂 Descoberta", f"{a.tamanho_bytes / 1024:.1f} KB<br>sha256 {a.hash_sha256[:12]}", "ok"),
        (
            "🔎 Classificação",
            f"{a.tipo.formato if a.tipo else '—'} · {html.escape(a.descricao_layout)}",
            "falhou" if a.tipo and a.tipo.layout.endswith(("corrompido", "corrompida", "nao_suportado")) else "ok",
        ),
        (
            "⚙️ Extração",
            f"{html.escape(r.metodo if r else '—')}<br>saldo final {brl(r.saldo_final) if r else '—'} · "
            f"{len(r.movimentos) if r else 0} lançamentos",
            a.status_pos_extracao or "ok",
        ),
        (
            "🧮 Validação",
            f"{badge(st_final)} {len(a.obs_validacao)} alerta(s) adicionados",
            st_final,
        ),
        ("📊 Consolidação", f"linha {linha} da planilha<br>registrado no log", "ok"),
    ]
    out = ['<div class="jornada">']
    for i, (t, d, s) in enumerate(passos):
        if i:
            out.append('<div class="seta feito">➜</div>')
        out.append(f'<div class="passo {s}"><b>{t}</b>{d}</div>')
    out.append("</div>")
    return "".join(out)


def mostrar_reconciliacao(r: Any, tolerancia: Decimal) -> None:
    movs = r.movimentos
    cred = sum((m.valor for m in movs if m.valor > 0), Decimal("0.00"))
    deb = sum((-m.valor for m in movs if m.valor < 0), Decimal("0.00"))
    if r.saldo_inicial is None or r.saldo_final is None:
        st.info("Sem saldo inicial/final para reconciliar este arquivo.")
        return
    calculado = r.saldo_inicial + cred - deb
    dif = r.saldo_final - calculado
    ok = abs(dif) <= tolerancia
    icone = "✅ Reconciliado" if ok else "⚠️ Divergente"
    if not movs:
        icone = "ℹ️ Sem lançamentos para reconciliar"
    st.markdown(
        f"""<div class="recon"><table>
        <tr><td>Saldo inicial</td><td class="v">{brl(r.saldo_inicial)}</td></tr>
        <tr><td>(+) Créditos ({sum(1 for m in movs if m.valor > 0)})</td><td class="v">{brl(cred)}</td></tr>
        <tr><td>(−) Débitos ({sum(1 for m in movs if m.valor < 0)})</td><td class="v">{brl(deb)}</td></tr>
        <tr class="tot"><td>= Saldo calculado pela automação</td><td class="v">{brl(calculado)}</td></tr>
        <tr><td>Saldo final declarado no extrato</td><td class="v">{brl(r.saldo_final)}</td></tr>
        <tr class="tot"><td>Diferença · {icone}</td><td class="v">{brl(dif)}</td></tr>
        </table></div>""",
        unsafe_allow_html=True,
    )


def tabela_movimentos(r: Any, tolerancia: Decimal) -> None:
    if not r.movimentos:
        return
    corrente = r.saldo_inicial or Decimal("0")
    linhas = []
    status_linhas: list[str] = []
    serie = [{"Lançamento": 0, "Saldo": float(corrente)}]
    for i, m in enumerate(r.movimentos, start=1):
        corrente += m.valor
        divergente = m.saldo is not None and abs(corrente - m.saldo) > tolerancia
        negativo = corrente < Decimal("0")
        if divergente:
            confere = "⚠️ Divergente"
            status_linhas.append("divergente")
        elif negativo:
            confere = "🔻 Saldo negativo"
            status_linhas.append("negativo")
        else:
            confere = "✓"
            status_linhas.append("ok")
        linhas.append(
            {
                "#": i,
                "Data": m.data or "",
                "Descrição": m.descricao,
                "Valor": brl(m.valor),
                "Saldo calculado": brl(corrente),
                "Saldo no extrato": brl(m.saldo) if m.saldo is not None else "—",
                "Status": confere,
            }
        )
        serie.append({"Lançamento": i, "Saldo": float(corrente)})
    df_mov = pd.DataFrame(linhas)

    def _estilo_linha(row: pd.Series) -> list[str]:
        idx = int(row["#"]) - 1
        tipo_l = status_linhas[idx] if 0 <= idx < len(status_linhas) else "ok"
        if tipo_l == "divergente":
            return ["background-color:#FFC7CE; color:#9C0006; font-weight:700"] * len(row)
        if tipo_l == "negativo":
            return ["background-color:#FFEB9C; color:#9C6500; font-weight:600"] * len(row)
        return [""] * len(row)

    t1, t2 = st.tabs(["📋 Lançamentos", "📈 Evolução do saldo"])
    with t1:
        st.dataframe(df_mov.style.apply(_estilo_linha, axis=1), hide_index=True, width="stretch", height=320)
    with t2:
        st.line_chart(pd.DataFrame(serie).set_index("Lançamento"), height=300)
        if min(s["Saldo"] for s in serie) < 0:
            st.caption("🔻 As linhas destacadas em amarelo indicam quando o saldo ficou negativo durante o período.")


CASOS_DESTAQUE: list[tuple[str, str, str]] = [
    ("🧮 Divergência R$ 1.080", "extrato_sol_do_sertao_I_out2026.pdf", "Saldo declarado difere da soma dos lançamentos"),
    ("📉 Saldo negativo intradia", "cajueiro_solar_extrato_10-2026.xlsx", "Pagamento atípico de inversores deixou saldo negativo no mês"),
    ("🗂️ Duplicata SHA-256", "EXT_102026_LagoaAzul (1).pdf", "Cópia idêntica detectada pelo hash SHA-256"),
    ("📱 Print IA · Período/Conta", "print_serra_dourada_II.png", "Lido via Gemini Visão; período 2026-09 e conta de 7 dígitos"),
    ("🚫 Não-extrato isolado", "aviso_agencia_horizonte.pdf", "Comunicado bancário isolado como 'falhou' sem parar o lote"),
]


def secao_rastreio(ex: Execucao) -> None:
    nomes = [a.nome for a in ex.arquivos]
    ordenados = sorted(nomes, key=str.lower)
    padrao_nome = next(
        (a.nome for a in ex.arquivos if a.resultado and a.resultado.status == "revisar"),
        nomes[0],
    )
    if st.session_state.get("arquivo_rastreio") not in nomes:
        st.session_state["arquivo_rastreio"] = padrao_nome

    casos_disponiveis = [(rot, arq, desc) for rot, arq, desc in CASOS_DESTAQUE if arq in nomes]
    if casos_disponiveis:
        st.caption("⚡ **Atalhos para casos de destaque do lote** (clique para inspecionar):")
        cols_atalho = st.columns(len(casos_disponiveis))
        for col, (rot_caso, arq_caso, desc_caso) in zip(cols_atalho, casos_disponiveis):
            ativo = st.session_state.get("arquivo_rastreio") == arq_caso
            if col.button(
                rot_caso,
                key=f"atalho_{arq_caso}",
                help=f"{arq_caso} — {desc_caso}",
                type="primary" if ativo else "secondary",
                width="stretch",
            ):
                st.session_state["arquivo_rastreio"] = arq_caso
                st.rerun()

    def rotulo(n: str) -> str:
        a = next(x for x in ex.arquivos if x.nome == n)
        emoji = {"ok": "🟢", "revisar": "🟡", "falhou": "🔴"}.get(a.resultado.status if a.resultado else "", "⚪")
        return f"{emoji} {n}"

    escolhido = st.selectbox(
        "Escolha um extrato para acompanhar sua jornada",
        nomes,
        key="arquivo_rastreio",
        format_func=rotulo,
    )
    a = next(x for x in ex.arquivos if x.nome == escolhido)
    r = a.resultado
    st.markdown(html_jornada(a, ordenados.index(escolhido) + 2), unsafe_allow_html=True)

    col_doc, col_dados = st.columns([1, 1], gap="large")
    with col_doc:
        st.markdown("##### 📄 Documento original")
        mostrar_documento(a)
    with col_dados:
        st.markdown("##### 🧾 O que a automação extraiu")
        if r is None:
            st.error("Sem resultado.")
            return
        dados = {
            "Banco": r.banco or "—",
            "Conta": r.conta or "—",
            "Período": r.periodo or "—",
            "Saldo inicial": brl(r.saldo_inicial),
            "Saldo final": brl(r.saldo_final),
            "Método": r.metodo,
            "Status final": r.status.upper(),
        }
        if r.confianca_ia:
            dados["Confiança da IA"] = r.confianca_ia
        if r.chamadas_ia:
            dados["Tokens de IA"] = str(r.tokens_total)
        st.dataframe(
            pd.DataFrame({"Campo": list(dados), "Valor": list(dados.values())}), hide_index=True, width="stretch"
        )
        st.markdown("##### 🧮 Reconciliação aritmética")
        tol = ex.config.validacao.tolerancia_reconciliacao
        mostrar_reconciliacao(r, tol)
        if r.observacoes:
            st.markdown("##### 📝 Observações")
            for o in r.observacoes:
                origem = "Extração" if o in a.obs_pos_extracao else "Validação"
                st.markdown(f"- **[{origem}]** {o}")
    if r and r.movimentos:
        tabela_movimentos(r, ex.config.validacao.tolerancia_reconciliacao)


# ---------------------------------------------------------------------------
# Ganho de negócio
# ---------------------------------------------------------------------------


def secao_roi(ex: Execucao) -> None:
    res = ex.resultados
    formatos = Counter(r.formato for r in res)
    n_doc = formatos.get("PDF", 0) + formatos.get("Imagem", 0)
    n_xlsx = formatos.get("Excel", 0)
    n_alertas = sum(1 for r in res if r.status in {"revisar", "falhou"})
    n = max(len(res), 1)

    st.markdown("Premissas do processo manual (editáveis):")
    c = st.columns(5)
    min_doc = c[0].number_input("min por PDF/PNG", 1, 60, 8)
    min_xlsx = c[1].number_input("min por Excel", 1, 60, 4)
    min_fmt = c[2].number_input("min formatação/conferência", 0, 240, 30)
    min_retrab = c[3].number_input("min retrabalho manual", 0, 240, 20)
    min_alerta = c[4].number_input("min revisão por alerta", 1, 60, 5)

    manual = n_doc * min_doc + n_xlsx * min_xlsx + min_fmt + min_retrab
    exec_min = sum(r.duracao_s for r in res) / 60
    revisao = n_alertas * min_alerta
    auto = exec_min + revisao
    ganho = manual - auto

    k = st.columns(4)
    k[0].metric("Processo manual", f"{manual:.0f} min")
    k[1].metric("Com a automação", f"{auto:.1f} min", help=f"execução {exec_min:.1f} min + revisão de {n_alertas} alertas")
    k[2].metric("Ganho por lote", f"{ganho:.0f} min", f"-{ganho / manual:.0%} de tempo" if manual else None)
    tokens_in = sum(r.tokens_entrada for r in res)
    tokens_out = sum(r.tokens_saida for r in res)
    cfg = ex.config.gemini
    custo = tokens_in / 1e6 * cfg.custo_por_1m_entrada_usd + tokens_out / 1e6 * cfg.custo_por_1m_saida_usd
    k[3].metric("Custo de IA do lote", f"US$ {custo:.3f}")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Composição do tempo neste lote (min)**")
        df = pd.DataFrame(
            {
                "Leitura/digitação": [n_doc * min_doc + n_xlsx * min_xlsx, exec_min],
                "Formatação": [min_fmt, 0],
                "Retrabalho/revisão": [min_retrab, revisao],
            },
            index=["Manual", "Automação"],
        )
        st.bar_chart(df, height=300)
    with col2:
        st.markdown("**Projeção conforme o portfólio de usinas cresce**")
        taxa_alerta = n_alertas / n
        media_manual = (n_doc * min_doc + n_xlsx * min_xlsx) / n
        media_exec = exec_min / n
        pontos = []
        for contas in range(10, 210, 10):
            pontos.append(
                {
                    "Contas/mês": contas,
                    "Manual (h)": (contas * media_manual + min_fmt + min_retrab * contas / n) / 60,
                    "Automação (h)": (contas * media_exec + contas * taxa_alerta * min_alerta) / 60,
                }
            )
        st.line_chart(pd.DataFrame(pontos).set_index("Contas/mês"), height=300)
    st.caption(
        "O tempo de execução soma a duração real de cada arquivo"
        + (" (para imagens no modo Demonstração, a duração da chamada original ao Gemini)." if ex.modo == "demo" else ".")
    )


# ---------------------------------------------------------------------------
# Layout principal
# ---------------------------------------------------------------------------


def sidebar() -> tuple[str, str, list[Any], float, str, bool]:
    with st.sidebar:
        st.markdown("## ⚙️ Execução")
        modo_label = st.radio(
            "Modo",
            ["🎬 Demonstração", "⚡ Ao vivo"],
            help=(
                "Demonstração: Excel e PDF são processados de verdade; para as imagens, reaproveita a resposta do "
                "Gemini de uma execução real (instantâneo, sem chave e sem custo).\n\n"
                "Ao vivo: pipeline 100% real, com chamadas à API do Gemini."
            ),
        )
        modo = "demo" if modo_label.startswith("🎬") else "ao_vivo"
        chave = ""
        if modo == "ao_vivo":
            st.text_input("GEMINI_API_KEY (opcional)", type="password", key="chave_manual",
                          help="Usada apenas nesta sessão. Se vazio, usa Streamlit secrets ou o .env local.")
            chave, origem_chave = obter_chave()
            if chave:
                st.success(f"Chave encontrada ({origem_chave}).")
            else:
                st.warning("Sem chave do Gemini: as imagens ficarão como 'falhou'.")

        st.markdown("---")
        origem_label = st.radio("Arquivos de entrada", ["📁 Lote do case (outubro/2026)", "⬆️ Enviar meus arquivos"])
        origem = "case" if origem_label.startswith("📁") else "upload"
        uploads: list[Any] = []
        if origem == "upload":
            uploads = st.file_uploader(
                "Extratos (PDF, Excel, PNG/JPG)",
                type=["pdf", "xlsx", "xlsm", "png", "jpg", "jpeg"],
                accept_multiple_files=True,
            ) or []
            if modo == "demo":
                st.caption("No modo Demonstração, imagens novas (fora do lote do case) exigem o modo Ao vivo.")

        st.markdown("---")
        ritmo_label = st.select_slider("Ritmo da animação", options=list(RITMOS), value="Normal")
        pode = origem == "case" or bool(uploads)
        clicou = st.button("▶ Executar automação", type="primary", width="stretch", disabled=not pode)
        st.markdown("---")
        st.caption(
            "Mesmo código da CLI `python -m rpa_extratos`: descoberta, classificação, extratores, validação e "
            "consolidação são importados do pacote `rpa_extratos`. As saídas desta tela vão para uma pasta "
            "temporária e não alteram `saida/` nem `logs/`."
        )
    return modo, origem, uploads, RITMOS[ritmo_label], chave, clicou


def cabecalho(ex: Execucao | None) -> None:
    st.markdown(
        '<div class="hero"><h1>🤖 RPA · Consolidação de Saldos Bancários</h1>'
        "<p>Do extrato bruto (PDF, Excel ou print de aplicativo) à planilha consolidada e auditável — "
        "acompanhe cada etapa da automação.</p></div>",
        unsafe_allow_html=True,
    )
    if ex is None:
        return
    res = ex.resultados
    cont = Counter(r.status for r in res)
    c = st.columns(6)
    c[0].metric("Arquivos", len(res))
    c[1].metric("✅ OK", cont.get("ok", 0))
    c[2].metric("⚠️ Revisar", cont.get("revisar", 0))
    c[3].metric("❌ Falhou", cont.get("falhou", 0))
    c[4].metric("Período", ex.meta_validacao.get("periodo_lote") or "—")
    c[5].metric("Modo", "Demonstração" if ex.modo == "demo" else "Ao vivo")


def inicializar_demo_padrao() -> None:
    """Pré-carrega o lote do case na primeira abertura para experiência imediata (zero-click)."""
    if "execucao" in st.session_state:
        return
    entrada, trabalho = preparar_entrada("case", [])
    eventos: list[tuple[str, str, str]] = []

    def _registrar(etapa: str, msg: str, _dados: dict[str, Any]) -> None:
        from datetime import datetime

        eventos.append((datetime.now().strftime("%H:%M:%S"), etapa, msg))

    st.session_state["execucao"] = motor.executar(
        entrada,
        trabalho,
        modo="demo",
        origem="case",
        api_key=None,
        ritmo_s=0.0,
        on_evento=_registrar,
    )
    st.session_state["eventos"] = eventos


def main() -> None:
    modo, origem, uploads, ritmo, chave, clicou = sidebar()

    if clicou:
        cabecalho(None)
        st.markdown("### 🛤️ Percurso da automação")
        with st.container(border=True):
            rodar(modo, origem, uploads, ritmo, chave)
        st.rerun()

    if "execucao" not in st.session_state:
        with st.spinner("Carregando demonstração inicial do lote de extratos…"):
            inicializar_demo_padrao()

    ex: Execucao | None = st.session_state.get("execucao")
    cabecalho(ex)

    col_tit, col_btn = st.columns([3, 1])
    col_tit.markdown("### 🛤️ Percurso da automação")
    pode_animar = origem == "case" or bool(uploads)
    if col_btn.button(
        "🎬 Reproduzir animação passo a passo",
        width="stretch",
        disabled=not pode_animar,
        help="Executa novamente o pipeline acendendo cada etapa do diagrama em tempo real.",
    ):
        ritmo_anim = ritmo if ritmo > 0 else 0.12
        with st.container(border=True):
            rodar(modo, origem, uploads, ritmo_anim, chave)
        st.rerun()

    if ex is None:
        st.markdown(html_fluxo(estado_inicial()), unsafe_allow_html=True)
        return

    st.markdown(html_fluxo(estado_final(ex)), unsafe_allow_html=True)
    eventos = st.session_state.get("eventos", [])
    with st.expander(f"🖥️ Log em tempo real da execução ({len(eventos)} eventos)"):
        st.code("\n".join(f"{h} [{e}] {m}" for h, e, m in eventos), language="text")

    st.markdown("### 🔍 O que aconteceu em cada etapa")
    expandir = st.toggle("Expandir todas as etapas", value=False)
    secoes = {
        "descoberta": secao_descoberta,
        "classificacao": secao_classificacao,
        "extracao": secao_extracao,
        "validacao": secao_validacao,
        "consolidacao": secao_consolidacao,
    }
    for i, (k, titulo, icone, tecno) in enumerate(ETAPAS, start=1):
        dur = ex.duracao_etapas.get(k, 0)
        with st.expander(f"{icone} **{i}. {titulo}** — {tecno} · {dur:.2f}s", expanded=expandir or k == "consolidacao"):
            secoes[k](ex)

    st.markdown("### 🔬 Rastreio individual: a jornada de um extrato")
    with st.container(border=True):
        secao_rastreio(ex)

    st.markdown("### 💰 Ganho para o negócio")
    with st.container(border=True):
        secao_roi(ex)


main()
