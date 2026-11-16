"""Modelos de dados do pipeline de extração, validação e consolidação."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

PRIORIDADE_STATUS: dict[str, int] = {
    "ok": 0,
    "revisar": 1,
    "falhou": 2,
}


@dataclass
class Movimento:
    """Representa um lançamento individual do extrato bancário."""

    data: str | None
    descricao: str
    valor: Decimal
    saldo: Decimal | None = None


@dataclass
class ResultadoExtracao:
    """Resultado completo do processamento de um arquivo de extrato."""

    arquivo: str
    caminho: Path
    hash_sha256: str
    formato: str
    banco: str | None = None
    conta: str | None = None
    periodo: str | None = None
    saldo_inicial: Decimal | None = None
    saldo_final: Decimal | None = None
    movimentos: list[Movimento] = field(default_factory=list)
    total_creditos_declarado: Decimal | None = None
    total_debitos_declarado: Decimal | None = None
    moeda: str = "BRL"
    confianca_ia: str | None = None
    nao_e_extrato: bool = False
    status: str = "ok"
    observacoes: list[str] = field(default_factory=list)
    metodo: str = ""
    duracao_s: float = 0.0
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_total: int = 0
    chamadas_ia: int = 0

    def adicionar_observacao(self, novo_status: str, texto: str) -> None:
        """Atualiza o status respeitando a precedência ``falhou > revisar > ok`` e registra a observação."""
        if novo_status not in PRIORIDADE_STATUS:
            raise ValueError(f"Status inválido: {novo_status}")
        if PRIORIDADE_STATUS[novo_status] > PRIORIDADE_STATUS[self.status]:
            self.status = novo_status
        texto_limpo = texto.strip()
        if texto_limpo and texto_limpo not in self.observacoes:
            self.observacoes.append(texto_limpo)

    @property
    def observacao_texto(self) -> str:
        """Retorna todas as observações concatenadas com '; '."""
        return "; ".join(self.observacoes)

    @classmethod
    def falha(
        cls,
        caminho: Path,
        motivo: str,
        *,
        hash_sha256: str = "",
        formato: str = "Desconhecido",
        metodo: str = "erro",
        duracao_s: float = 0.0,
    ) -> ResultadoExtracao:
        """Constrói um resultado de falha padronizado para erros isolados por arquivo."""
        res = cls(
            arquivo=caminho.name,
            caminho=caminho,
            hash_sha256=hash_sha256,
            formato=formato,
            status="falhou",
            metodo=metodo,
            duracao_s=duracao_s,
        )
        res.adicionar_observacao("falhou", motivo)
        return res
