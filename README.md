# RPA Extratos — Consolidação Automática de Saldos Bancários

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://case-rpa-consolidacao-extratos.streamlit.app/)

> **🔗 Demonstração interativa online:** [https://case-rpa-consolidacao-extratos.streamlit.app/](https://case-rpa-consolidacao-extratos.streamlit.app/)

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

## Painel Visual (Bônus — Streamlit)

Para apresentar o percurso completo da automação de forma interativa:

```bash
streamlit run app/streamlit_app.py
```

O painel exibe:
- **Percurso da automação em tempo real**: diagrama visual com as 5 etapas (`Descoberta → Classificação → Extração → Validação → Consolidação`) acendendo conforme os arquivos são processados.
- **Dois modos de execução**:
  - **Demonstração**: processa PDFs e Excels de verdade e reaproveita as respostas do Gemini salvas em `demo/cache_gemini.json` para os prints de app (instantâneo, sem chave e sem custo).
  - **Ao vivo**: executa o pipeline 100% real incluindo chamadas à API do Google Gemini.
- **Lote do case ou upload**: usa os 17 arquivos do case (extraindo `extratos_ufv_out2026.zip` automaticamente se `entrada/` não existir) ou permite enviar novos arquivos pela interface.
- **Rastreio individual por arquivo**: documento original lado a lado com os dados extraídos, reconciliação aritmética detalhada (`saldo inicial + créditos − débitos = saldo final`) e evolução do saldo.
- **Ganho de negócio (ROI)** e **download** da planilha consolidada (`.xlsx`) e dos logs (`.log` / `.json`).

Para publicar gratuitamente no **Streamlit Community Cloud**, basta apontar para este repositório no [share.streamlit.io](https://share.streamlit.io) com o arquivo principal `app/streamlit_app.py` (opcionalmente adicionando `GEMINI_API_KEY` em *Secrets* para habilitar o modo *Ao vivo* na nuvem).

## Testes

```bash
# Testes unitários, mocks, idempotência e aceitação determinística (PDF + Excel)
pytest -m "not gemini" -v

# Suíte completa incluindo chamada real ao Gemini para os 5 PNGs (requer GEMINI_API_KEY)
pytest -v
```
