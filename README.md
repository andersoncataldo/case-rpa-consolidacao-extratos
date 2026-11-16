# RPA Extratos — Consolidação Automática de Saldos Bancários

Automação ponta a ponta em Python que lê extratos bancários em **PDF**, **Excel (`.xlsx`)** e **Imagem (`.png`)**, aplica reconciliação aritmética e validações de lote, gera a planilha consolidada no layout do modelo oficial (`saida/consolidado_AAAA-MM.xlsx`) e grava logs auditáveis em `.log` e `.json` (`logs/`).

## Arquitetura resumida

- **Excel e PDF com texto**: extração **100% determinística** (`openpyxl` e `pdfplumber`) por detecção de layout pelo conteúdo.
- **Imagens PNG (prints de app)**: extração estruturada via API do **Google Gemini** (`google-genai`, `temperature=0`, JSON Schema validado com Pydantic), seguida de **reconciliação aritmética em `Decimal`** no código.
- **Isolamento de falhas**: erro em um arquivo nunca interrompe o lote (`Status = falhou` + motivo em `Observação`).

## Instalação

Requisitos: Python 3.11+.

```bash
python -m venv .venv
# Windows (PowerShell): .venv\Scripts\Activate.ps1
# Linux/macOS:          source .venv/bin/activate

pip install -r requirements.txt
pip install --no-build-isolation --no-deps -e .
```

## Configuração da API Gemini

Copie `.env.example` para `.env` e defina sua chave:

```dotenv
GEMINI_API_KEY=sua_chave_real_aqui
```

O modelo padrão, tolerância de reconciliação e rótulos ficam em `config.yaml`.

## Execução

1. (Setup inicial dos dados do case) Extraia os 17 arquivos para `entrada/`:

   ```bash
   python scripts/preparar_entrada.py
   ```

2. Execute o pipeline ponta a ponta:

   ```bash
   python -m rpa_extratos --entrada entrada --saida saida --logs logs
   ```

   Saídas geradas:
   - `saida/consolidado_AAAA-MM.xlsx`
   - `logs/execucao_YYYYMMDD_HHMMSS.log` e `.json` (`logs/ultima_execucao.*`)

## Testes

```bash
# Testes unitários, mocks, idempotência e aceitação determinística (PDF + Excel)
pytest -m "not gemini" -v

# Suíte completa incluindo chamada real ao Gemini para os 5 PNGs (requer GEMINI_API_KEY)
pytest -v
```
