"""Descoberta recursiva de arquivos na pasta de entrada e cálculo de hash SHA-256."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

NOMES_IGNORADOS = {".ds_store", "thumbs.db", "desktop.ini"}


@dataclass(frozen=True)
class ArquivoDescoberto:
    """Representa um arquivo elegível encontrado na pasta de entrada."""

    caminho: Path
    nome: str
    hash_sha256: str


def deve_ignorar(caminho: Path) -> bool:
    """Retorna True para arquivos temporários ou ocultos que devem ser ignorados."""
    nome = caminho.name
    if nome.startswith("~$") or nome.startswith("."):
        return True
    if nome.lower() in NOMES_IGNORADOS:
        return True
    return any(parte.startswith(".") for parte in caminho.parts[:-1])


def calcular_sha256(caminho: Path) -> str:
    """Calcula o hash SHA-256 hexadecimal completo do arquivo."""
    digest = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(65536), b""):
            digest.update(bloco)
    return digest.hexdigest()


def listar_arquivos(entrada: Path) -> list[ArquivoDescoberto]:
    """Lista recursivamente os arquivos de ``entrada`` em ordem determinística."""
    if not entrada.exists():
        raise FileNotFoundError(f"Pasta de entrada não encontrada: {entrada}")
    if not entrada.is_dir():
        raise NotADirectoryError(f"Caminho de entrada não é uma pasta: {entrada}")

    arquivos: list[ArquivoDescoberto] = []
    for item in entrada.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(entrada)
        if deve_ignorar(rel):
            continue
        arquivos.append(
            ArquivoDescoberto(
                caminho=item,
                nome=item.name,
                hash_sha256=calcular_sha256(item),
            )
        )

    arquivos.sort(key=lambda a: (a.nome.lower(), a.nome, str(a.caminho)))
    return arquivos
