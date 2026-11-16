"""Regras de validação de lote, reconciliação aritmética e definição de Status."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from decimal import Decimal
from statistics import median

from .config import AppConfig
from .modelos import ResultadoExtracao
from .normalizacao import formatar_moeda_br


def determinar_periodo_lote(resultados: list[ResultadoExtracao]) -> str | None:
    """Retorna o período mais frequente (moda) entre os extratos válidos lidos."""
    periodos = [r.periodo for r in resultados if r.periodo and not r.nao_e_extrato]
    if not periodos:
        return None
    contagem = Counter(periodos)
    periodo_moda, _ = max(contagem.items(), key=lambda item: (item[1], item[0]))
    return periodo_moda


def _chave_prioridade_original(resultado: ResultadoExtracao) -> tuple[bool, int, str, str]:
    """Ordena cópias duplicadas para manter o arquivo original como primeiro."""
    nome = resultado.arquivo
    parece_copia = bool(re.search(r"\(\d+\)|c[oó]pia|copy", nome, flags=re.IGNORECASE))
    return (parece_copia, len(nome), nome.lower(), nome)


def _reconciliar_extrato(resultado: ResultadoExtracao, tolerancia: Decimal) -> None:
    """Verifica a consistência aritmética entre saldo inicial, lançamentos e saldo final."""
    if not resultado.movimentos:
        if (
            resultado.saldo_inicial is not None
            and resultado.saldo_final is not None
            and abs(resultado.saldo_final - resultado.saldo_inicial) > tolerancia
        ):
            resultado.adicionar_observacao(
                "revisar",
                "Ausência de lançamentos para reconciliar a variação entre saldo inicial e saldo final",
            )
        return

    soma_movimentos = sum((m.valor for m in resultado.movimentos), Decimal("0.00"))
    reportou_divergencia = False

    if resultado.saldo_inicial is not None and resultado.saldo_final is not None:
        saldo_calculado = resultado.saldo_inicial + soma_movimentos
        dif = abs(resultado.saldo_final - saldo_calculado)
        if dif > tolerancia:
            resultado.adicionar_observacao(
                "revisar",
                (
                    f"Divergência na reconciliação: saldo final declarado R$ {formatar_moeda_br(resultado.saldo_final)} "
                    f"difere do saldo calculado R$ {formatar_moeda_br(saldo_calculado)} "
                    f"(diferença de R$ {formatar_moeda_br(dif)})"
                ),
            )
            reportou_divergencia = True

    # Verifica também o último saldo corrente da tabela quando disponível
    ultimo_saldo = resultado.movimentos[-1].saldo
    if not reportou_divergencia and ultimo_saldo is not None and resultado.saldo_final is not None:
        dif_ultimo = abs(resultado.saldo_final - ultimo_saldo)
        if dif_ultimo > tolerancia:
            resultado.adicionar_observacao(
                "revisar",
                (
                    f"Divergência na reconciliação: saldo final declarado R$ {formatar_moeda_br(resultado.saldo_final)} "
                    f"difere do último saldo corrente R$ {formatar_moeda_br(ultimo_saldo)} "
                    f"(diferença de R$ {formatar_moeda_br(dif_ultimo)})"
                ),
            )
            reportou_divergencia = True

    # Verifica consistência passo a passo dos saldos correntes (quando saldo_inicial e saldos existem)
    if not reportou_divergencia and resultado.saldo_inicial is not None:
        corrente = resultado.saldo_inicial
        for mov in resultado.movimentos:
            corrente += mov.valor
            if mov.saldo is not None and abs(corrente - mov.saldo) > tolerancia:
                dif_passo = abs(corrente - mov.saldo)
                resultado.adicionar_observacao(
                    "revisar",
                    (
                        f"Inconsistência no saldo corrente em '{mov.descricao}': "
                        f"esperado R$ {formatar_moeda_br(corrente)}, encontrado R$ {formatar_moeda_br(mov.saldo)} "
                        f"(diferença de R$ {formatar_moeda_br(dif_passo)})"
                    ),
                )
                break

    # Verifica totais de crédito e débito declarados (ex.: Resumo do período no PDF Tipo B)
    if resultado.total_creditos_declarado is not None:
        soma_cred = sum((m.valor for m in resultado.movimentos if m.valor > 0), Decimal("0.00"))
        if abs(soma_cred - resultado.total_creditos_declarado) > tolerancia:
            resultado.adicionar_observacao(
                "revisar",
                (
                    f"Total de créditos calculado R$ {formatar_moeda_br(soma_cred)} "
                    f"difere do declarado R$ {formatar_moeda_br(resultado.total_creditos_declarado)}"
                ),
            )
    if resultado.total_debitos_declarado is not None:
        soma_deb = sum((-m.valor for m in resultado.movimentos if m.valor < 0), Decimal("0.00"))
        if abs(soma_deb - resultado.total_debitos_declarado) > tolerancia:
            resultado.adicionar_observacao(
                "revisar",
                (
                    f"Total de débitos calculado R$ {formatar_moeda_br(soma_deb)} "
                    f"difere do declarado R$ {formatar_moeda_br(resultado.total_debitos_declarado)}"
                ),
            )


def _verificar_saldo_negativo_intradia(resultado: ResultadoExtracao, multiplicador_atipico: float) -> None:
    """Adiciona observação informativa (mantendo status 'ok') se houve saldo negativo no mês."""
    if resultado.status != "ok" or not resultado.movimentos:
        return
    if resultado.saldo_final is None or resultado.saldo_final < Decimal("0"):
        return

    saldos_correntes: list[Decimal] = []
    if all(m.saldo is not None for m in resultado.movimentos):
        saldos_correntes = [m.saldo for m in resultado.movimentos if m.saldo is not None]
    elif resultado.saldo_inicial is not None:
        corrente = resultado.saldo_inicial
        for mov in resultado.movimentos:
            corrente += mov.valor
            saldos_correntes.append(corrente)

    if not saldos_correntes:
        return

    menor_saldo = min(saldos_correntes)
    if menor_saldo >= Decimal("0"):
        return

    valores_abs = [abs(m.valor) for m in resultado.movimentos]
    mediana = Decimal(str(median(valores_abs))) if valores_abs else Decimal("0")
    debitos = [m for m in resultado.movimentos if m.valor < Decimal("0")]
    maior_debito = max(debitos, key=lambda m: abs(m.valor), default=None)

    if (
        maior_debito is not None
        and mediana > Decimal("0")
        and abs(maior_debito.valor) >= Decimal(str(multiplicador_atipico)) * mediana
    ):
        resultado.adicionar_observacao(
            "ok",
            (
                f"Saldo ficou negativo durante o período (mín. R$ {formatar_moeda_br(menor_saldo)}) "
                f"após pagamento atípico de R$ {formatar_moeda_br(abs(maior_debito.valor))} "
                f"({maior_debito.descricao}); saldo final fechou positivo"
            ),
        )
    else:
        resultado.adicionar_observacao(
            "ok",
            (
                f"Saldo ficou negativo durante o período (mín. R$ {formatar_moeda_br(menor_saldo)}), "
                "mas o saldo final fechou positivo"
            ),
        )


def validar_lote(resultados: list[ResultadoExtracao], config: AppConfig) -> dict[str, object]:
    """Aplica todas as regras de validação ao lote e retorna o resumo de auditoria."""
    periodo_lote = determinar_periodo_lote(resultados)
    padrao_conta = re.compile(config.validacao.padrao_conta_regex)
    tolerancia = config.validacao.tolerancia_reconciliacao

    # 1. Validações individuais por documento
    for r in resultados:
        if r.nao_e_extrato or (
            r.status != "falhou"
            and r.banco is None
            and r.conta is None
            and r.periodo is None
            and r.saldo_final is None
        ):
            r.nao_e_extrato = True
            r.adicionar_observacao("falhou", "Documento não é um extrato bancário")
            continue

        if r.status == "falhou" and r.saldo_final is None:
            if not r.observacoes:
                r.adicionar_observacao("falhou", "Saldo final não identificado")
            continue

        if r.saldo_final is None:
            r.adicionar_observacao("falhou", "Saldo final não identificado")
            continue

        faltantes = [
            campo
            for campo, val in (("banco", r.banco), ("conta", r.conta), ("período", r.periodo))
            if not val
        ]
        if faltantes:
            r.adicionar_observacao("revisar", f"Campos obrigatórios ausentes: {', '.join(faltantes)}")

        if r.moeda and r.moeda != "BRL":
            r.adicionar_observacao("revisar", f"Moeda diferente de BRL ({r.moeda})")

        if periodo_lote and r.periodo and r.periodo != periodo_lote:
            r.adicionar_observacao(
                "revisar",
                f"Período {r.periodo} diferente do esperado do lote ({periodo_lote})",
            )

        if r.conta and not padrao_conta.fullmatch(r.conta):
            r.adicionar_observacao(
                "revisar",
                f"Conta {r.conta} fora do padrão esperado (5 dígitos + DV)",
            )

        _reconciliar_extrato(r, tolerancia)

    # 2. Detecção de duplicidades por hash SHA-256
    grupos_hash: dict[str, list[ResultadoExtracao]] = defaultdict(list)
    for r in resultados:
        if r.hash_sha256:
            grupos_hash[r.hash_sha256].append(r)

    duplicidades: list[str] = []
    for hash_hex, grupo in grupos_hash.items():
        if len(grupo) < 2:
            continue
        grupo_ordenado = sorted(grupo, key=_chave_prioridade_original)
        original = grupo_ordenado[0]
        for copia in grupo_ordenado[1:]:
            copia.adicionar_observacao(
                "revisar",
                f"Arquivo em duplicata (mesmo hash SHA-256 de {original.arquivo})",
            )
            duplicidades.append(f"{copia.arquivo} ≡ {original.arquivo} (hash {hash_hex[:12]})")

    # 2b. Detecção de duplicidade lógica (mesmo banco, conta e período com hashes diferentes)
    grupos_chave: dict[tuple[str, str, str], list[ResultadoExtracao]] = defaultdict(list)
    for r in resultados:
        if r.banco and r.conta and r.periodo and not r.nao_e_extrato:
            grupos_chave[(r.banco.lower(), r.conta, r.periodo)].append(r)

    for grupo in grupos_chave.values():
        if len(grupo) < 2:
            continue
        grupo_ordenado = sorted(grupo, key=_chave_prioridade_original)
        primeiro = grupo_ordenado[0]
        for outro in grupo_ordenado[1:]:
            if outro.hash_sha256 != primeiro.hash_sha256:
                outro.adicionar_observacao(
                    "revisar",
                    f"Conta {outro.conta} e período {outro.periodo} duplicados em outro arquivo ({primeiro.arquivo})",
                )
                duplicidades.append(f"{outro.arquivo} ≡ {primeiro.arquivo} (mesma conta/período)")

    # 3. Alertas informativos para extratos 'ok' com eventos atípicos no mês
    for r in resultados:
        _verificar_saldo_negativo_intradia(
            r,
            config.validacao.multiplicador_lancamento_atipico,
        )

    # 4. Completude opcional (contas esperadas configuradas em config.yaml)
    contas_lidas = {r.conta for r in resultados if r.conta}
    contas_ausentes = [c for c in config.contas_esperadas if c not in contas_lidas]

    return {
        "periodo_lote": periodo_lote,
        "duplicidades": duplicidades,
        "contas_ausentes": contas_ausentes,
    }
