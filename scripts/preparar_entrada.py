"""Utilitário de setup para preparar a pasta de entrada e o modelo de planilha."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path


def preparar_ambiente(raiz: Path | None = None) -> tuple[list[Path], Path]:
    """Descompacta o zip de extratos para ``entrada/`` e copia o modelo para ``modelo/``."""
    base = raiz or Path(__file__).resolve().parent.parent
    zip_path = base / "extratos_ufv_out2026.zip"
    entrada_dir = base / "entrada"
    modelo_src = base / "modelo_consolidado_extratos.xlsx"
    modelo_dst = base / "modelo" / "modelo_consolidado_extratos.xlsx"

    if not zip_path.exists():
        raise FileNotFoundError(f"Arquivo zip não encontrado: {zip_path}")

    entrada_dir.mkdir(parents=True, exist_ok=True)
    extraidos: list[Path] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = Path(info.filename)
            partes = rel.parts
            if partes and partes[0] == "extratos":
                rel = Path(*partes[1:])
            if not str(rel) or rel.name.startswith(".") or rel.name.startswith("~$"):
                continue
            destino = entrada_dir / rel
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(zf.read(info.filename))
            extraidos.append(destino)

    if modelo_src.exists():
        modelo_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(modelo_src, modelo_dst)

    return extraidos, modelo_dst


def main() -> None:
    """Ponto de entrada CLI."""
    extraidos, modelo_dst = preparar_ambiente()
    print(f"Extraídos {len(extraidos)} arquivos para entrada/:")
    for p in sorted(extraidos, key=lambda x: x.name.lower()):
        print(f"  - {p.name}")
    print(f"Modelo disponível em: {modelo_dst}")


if __name__ == "__main__":
    main()
