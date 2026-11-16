"""Utilitário para listar modelos Gemini disponíveis na chave configurada."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from google import genai


def main() -> None:
    """Lista os modelos Gemini disponíveis que suportam geração de conteúdo."""
    load_dotenv()
    if not os.getenv("GEMINI_API_KEY"):
        raise SystemExit("Defina GEMINI_API_KEY no ambiente ou no arquivo .env.")

    client = genai.Client()
    modelos = sorted(
        (
            m.name.removeprefix("models/"),
            getattr(m, "display_name", ""),
            getattr(m, "supported_actions", []),
        )
        for m in client.models.list()
        if getattr(m, "name", None)
    )
    for nome, display, acoes in modelos:
        if "flash" in nome or "gemini" in nome:
            print(f"{nome:38s} | {display:32s} | {acoes}")


if __name__ == "__main__":
    main()
