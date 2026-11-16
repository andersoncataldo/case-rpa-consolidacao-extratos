# Automação de Consolidação de Saldos Bancários — Documentação Executiva

## 1. Fluxo da Automação

```
entrada/ (*.pdf, *.xlsx, *.png)
   │
   ▼
[1. Descoberta] ──► [2. Classificação] ──► [3. Extração] ──► [4. Validação] ──► [5. Consolidação]
  rglob + SHA-256     magic bytes +          Excel: openpyxl    Reconciliação     saida/consolidado_AAAA-MM.xlsx
  (ignora ~$*/.)      conteúdo (6 layouts)   PDF: pdfplumber    Moda de período   logs/execucao_*.log + .json
                                             PNG: Gemini Visão  Duplicata SHA-256
```

A automação varre `entrada/` recursivamente, identifica o layout pelo conteúdo (nunca pelo nome do arquivo), extrai cabeçalho, lançamentos e saldo final, reconcilia aritmeticamente em `Decimal` (`saldo inicial + movimentos == saldo final`), aplica precedência de status (`falhou > revisar > ok`) e gera planilha idêntica ao modelo com log auditável.

## 2. Premissas Reais Implementadas

- **Uma linha por arquivo (100% de rastreabilidade):** erros são isolados por arquivo; nenhum extrato some da planilha ou do log.
- **Determinístico primeiro, IA só onde necessário:** Excel e PDF selecionável são 100% determinísticos; apenas imagens (`.png` em resolução original) usam a API do Google Gemini (`google-genai`, `temperature=0`, saída JSON validada por Pydantic) — ainda assim submetidas à reconciliação aritmética no código.
- **Precisão financeira e formatos:** valores monetários processados exclusivamente em `Decimal`, `Conta` gravada como texto (`@`) preservando zeros à esquerda, `Período` normalizado para `AAAA-MM` e moda do lote calculada dinamicamente.
- **Fora de escopo:** login em internet banking, leitura automática de e-mail/SharePoint, integração Open Finance/OFX e lançamento no ERP.

## 3. Estimativa de Ganho (Conta Explicada)

Premissas base para o fechamento mensal de **17 contas** (7 PDF + 5 PNG + 5 XLSX), comparando o fluxo manual com a automação:

| Etapa | Processo Manual | Processo Automatizado |
|---|---|---|
| Leitura e digitação por arquivo | 12 PDF/PNG × 8 min + 5 XLSX × 4 min = **116 min** | Execução ponta a ponta: **< 1 min** (lote completo) |
| Formatação da planilha e conferência | **30 min** | Gerada pronta no modelo: **0 min** |
| Retrabalho por erro de digitação/conferência | 1 correção/mês × 20 min = **20 min** | Revisão humana apenas dos alertas (`revisar`/`falhou`): 4 × 5 min = **20 min** |
| **Total mensal** | **166 min (≈ 2,77 h/mês)** | **≈ 21 min (≈ 0,35 h/mês)** |

- **Ganho líquido mensal (17 contas):** `166 − 21 = 145 min ≈ 2,4 h/mês` (**87% de redução de tempo**).
- **Escala:** o ganho cresce linearmente com o portfólio de usinas — em **100 contas/mês**, o esforço manual saltaria para **≈ 14,5 h/mês**, enquanto a automação mantém o tempo operacional focado apenas nas exceções (**≈ 1,5 h/mês**), economizando **≈ 13 h/mês** e eliminando erros de digitação com trilha de auditoria SHA-256.
- **Custo de API:** apenas 5 imagens vão ao Gemini por lote (custo na faixa de frações de centavo de dólar por mês, desprezível frente à hora técnica economizada). *(Atualizado com medições exatas após execução ao vivo.)*

## 4. Próximos Passos (Prioridade)

1. **Alta — Completude e batimento intermensal:** cruzar as contas processadas com uma lista mestra em `config.yaml` (detectar conta faltante) e validar se `saldo_inicial(mês N) == saldo_final(mês N-1)`.
2. **Média — Ingestão e notificação contínuas:** coletar anexos automaticamente de caixa de e-mail/SharePoint e enviar resumo automático (Teams/e-mail) destacando apenas linhas `revisar` e `falhou`.
3. **Baixa — Fontes estruturadas (OFX/API/Open Finance):** substituir gradualmente capturas de tela e PDFs por arquivos OFX ou integração bancária direta, reduzindo ainda mais a dependência de visão por IA.
