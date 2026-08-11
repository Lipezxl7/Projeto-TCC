# TCC — Regulamento Alimentar Escolar

Pipeline em Python que integra **4 etapas** para apoiar a gestão da alimentação escolar: extrai o cardápio e as receitas de PDFs, conta pessoas únicas em vídeo/webcam (com re-identificação visual), e calcula a produção final gerando uma planilha `.xlsx` pronta para o Power BI.

Trabalho de Conclusão de Curso (TCC).

---

##Funcionalidades

- **Cardápio**: lê o PDF do cardápio escolar, identifica datas e pratos, e exporta JSON + CSV.
- **Receitas**: lê o PDF de receitas, extrai ingredientes, rendimento, porções (fundamental e EJA/E.M.), modo de preparo, e exporta JSON + CSV.
- **Contagem de pessoas** (`modulos/contador.py`): detecta, rastreia e diferencia indivíduos — mesmo após oclusões e reentradas — via YOLO26 + ByteTrack + re-identificação por histograma HSV. Suporta múltiplas fontes simultâneas (vídeos + webcams) com IDs consistentes entre fontes.
- **Produção (Power BI)**: cruza cardápio + receitas via fuzzy match (com mapeamento manual opcional), calcula água total e total a produzir por prato, e gera `arquivos/planilha.xlsx`.

---

## Requisitos

- **Python 3.14+** (usa `match/case` e anotações de tipo PEP 604).
- `pip install -r requirements.txt`.
- (Opcional) GPU NVIDIA, Apple Silicon ou Intel para a etapa de contagem.
- Servidor gráfico (X11/Wayland) para a janela de visualização — use `--no-window` em headless.

---

## Instalação

```bash
git clone https://codeberg.org/yLipe/Projeto-TCC
cd Projeto-TCC
python3.14 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### GPU (opcional — apenas para a etapa de contagem)

| Hardware       | Instruções                                                                                  |
|----------------|---------------------------------------------------------------------------------------------|
| **NVIDIA**     | `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130`           |
| **Apple Silicon** | `pip install torch` (MPS ativado automaticamente com PyTorch 2.12+)                       |
| **Intel**       | OpenVINO já está em `requirements.txt` — nenhuma instalação extra                          |
| **CPU genérico** | Funciona como fallback universal, sem extras                                              |

---

## Estrutura do projeto

```
Projeto-TCC/
├── main.py                  # Orquestrador de 4 etapas (cardápio + receitas + contagem + PBI)
├── modulos/
│   ├── __init__.py
│   ├── cardapio.py          # Extração do cardápio (PDF -> JSON/CSV)
│   ├── receita.py           # Extração de receitas (PDF -> JSON/CSV)
│   └── contador.py          # Contagem de pessoas unicas (~450 linhas)
├── arquivos/                # Fixtures e saídas
│   ├── cardapio.pdf
│   ├── receita.pdf
│   ├── video.mp4
│   ├── video2.mp4
│   ├── i2v6ti.mp4
│   ├── planilha.xlsx         # exemplo de saída PBI
│   └── TCC_Regulamento_Alimentar (1).docx
├── requirements.txt
├── CONTEXT.md
└── README.md
```

`*.json`, `*.csv`, `*.pt` e `yolo*/` são gitignored (regenerados em tempo de execução).

---

## Uso — pipeline completo via `main.py`

```bash
# Pipeline completo (manhã — fundamental)
python main.py --cardapio-pdf arquivos/cardapio.pdf --mes jun \
    --receita-pdf arquivos/receita.pdf \
    --video arquivos/video.mp4 \
    --etapa fund --alunos 300 --data 12-05 --no-window

# Tarde (médio/EJA) — mesmo cardápio, reaproveitando JSONs já extraídos
python main.py --skip-cardapio --skip-receitas --skip-contador \
    --cardapio-json arquivos/cardapio.json \
    --receitas-json arquivos/receitas.json \
    --etapa med --alunos 200 --data 12-05

# Só contagem de pessoas (pula cardápio, receitas e produção)
python main.py --skip-cardapio --skip-receitas --skip-producao \
    --video arquivos/video.mp4 --device cuda
```

### Argumentos do `main.py`

| Argumento            | Tipo    | Padrão                              | Descrição                                                       |
|----------------------|---------|-------------------------------------|-----------------------------------------------------------------|
| `--cardapio-pdf`     | string  | `arquivos/cardapio.pdf`             | PDF do cardápio                                                 |
| `--mes`              | string  | pergunta interactiva                | Mês a filtrar (`jan`, `fev`, ..., `dez`)                         |
| `--skip-cardapio`    | flag    | off                                 | Pula extração do cardápio, usa `--cardapio-json`                |
| `--cardapio-json`    | string  | `arquivos/cardapio.json`            | JSON do cardápio (entrada/saída)                                |
| `--receita-pdf`      | string  | `arquivos/receita.pdf`              | PDF das receitas                                                |
| `--skip-receitas`    | flag    | off                                 | Pula extração das receitas, usa `--receitas-json`               |
| `--receitas-json`    | string  | `arquivos/receitas.json`            | JSON das receitas (entrada/saída)                               |
| `--video`            | string  | —                                   | Arquivos de vídeo para contagem (multi; `nargs="*"`)            |
| `--webcam`           | int     | índice `0`                          | Webcam como fonte; repetitível (`--webcam 0 --webcam 1`)        |
| `--skip-contador`    | flag    | off                                 | Pula a etapa de contagem                                        |
| `--tolerance`        | float   | `0.005`                             | Tolерância da re-ID (faixa 0.003–0.10)                         |
| `--sample-rate`      | int     | `1`                                 | Atualiza aparência a cada N frames                              |
| `--img-size`         | int     | `640`                               | Resolução YOLO: `320 480 640 768 1024 1280 1536 2048`          |
| `--model`            | string  | `yolo26x.pt`                        | Modelo YOLO (`yolo26n`→`s`→`m`→`l`→`x`) ou `.pt` customizado     |
| `--device`           | string  | auto                                | `cuda` \| `mps` \| `intel:gpu` \| `intel:cpu` \| `cpu`          |
| `--no-window`        | flag    | off                                 | Modo headless                                                    |
| `--etapa`            | string  | obrigatório (a menos que `--skip-producao`) | `fund` (fundamental) ou `med` (médio/EJA)                       |
| `--alunos`           | int     | obrigatório (a menos que `--skip-producao`) | Quantidade de alunos; deve ser > 0                                |
| `--data`             | string  | obrigatório (a menos que `--skip-producao`) | Data de referência no formato `DD-MM`                            |
| `--skip-producao`    | flag    | off                                 | Pula a planilha PBI                                              |
| `--mapeamento`       | string  | `arquivos/mapeamento_manual.json`   | JSON com mapeamento manual prato→receita (opcional)             |
| `--no-json`          | flag    | off                                 | Não salva JSONs das extrações                                    |
| `--no-csv`           | flag    | off                                 | Não salva CSVs das extrações                                     |
| `--output`           | string  | `arquivos/planilha.xlsx`            | Planilha de saída PBI                                            |

---

## Uso modular — cada etapa isolada

```bash
# 1. Só o cardápio
python -m modulos.cardapio arquivos/cardapio.pdf

# 2. Só as receitas (usa arquivos/receita.pdf por padrão interno)
python -m modulos.receita

# 3. Só contagem de pessoas (contador.py standalone)
python -m modulos.contador arquivos/video.mp4
python -m modulos.contador --webcam
python -m modulos.contador a.mp4 b.mp4 --webcam 0 --tolerance 0.02
```

### Argumentos do `contador.py` (uso standalone)

| Parâmetro          | Padrão       | Descrição                                                                    |
|--------------------|--------------|------------------------------------------------------------------------------|
| `video` (posicional) | —          | Um ou mais arquivos de vídeo (`nargs="*"`)                                    |
| `--webcam [IDX]`   | índice `0`   | Webcam como fonte; repetitível (`--webcam 0 --webcam 1`)                      |
| `--tolerance`      | `0.005`      | Limiar de similaridade (faixa recomendada 0.003–0.10)                         |
| `--sample-rate`    | `1`          | Atualiza aparência a cada N frames                                            |
| `--img-size`       | `640`        | Resolução YOLO: `320 480 640 768 1024 1280 1536 2048`                         |
| `--model`          | `yolo26n.pt` | Modelo YOLO (`yolo26n`→`s`→`m`→`l`→`x`) ou `.pt` customizado                  |
| `--device`         | auto         | `cuda` \| `mps` \| `intel:gpu` \| `intel:cpu` \| `cpu`                        |
| `--no-window`      | off          |Roduca sem janelas (headless)                                                  |

**Note:** rodando `contador.py` no standalone mantém o histórico ByteTrack por fonte (`persist=True`), mas não há cruzamento entre fontes além do que ocorre dentro de uma única invocação.

---

## Cálculo de Produção (etapa 4 → Power BI)

Para cada prato do cardápio na data escolhida:

1. **Encontra a receita correspondente** via fuzzy match (`difflib`) + mapeamento manual opcional; limiar mínimo `0.55`.
2. Extrai `rendimento_base_g` (converte kg/litros → g), `porcao_aluno_g` (fund. ou EJA) e `agua_base_g`.
3. Aplica as fórmulas:
   - `fator = (alunos * porcao_aluno_g) / rendimento_base_g`
   - `agua_total_l = (fator * agua_base_g) / 1000`
   - `total_a_fazer_kg = (alunos * porcao_aluno_g) / 1000`
4. Gera `arquivos/planilha.xlsx` (1 aba `Producao`, 7 colunas): `Prato`, `Rendimento_Base_g`, `Porcao_Aluno_g`, `Alunos`, `Agua_Total_L`, `Total_A_Fazer_kg`.

Implementação: `calcular_producao_pbi()` (`main.py:193`) e `gerar_excel_pbi()` (`main.py:279`).

---

## Hardware suportado (contador)

O sistema detecta automaticamente o melhor dispositivo disponível (`modulos/contador.py:16`):

| Dispositivo    | Flag            | Notas                                      |
|----------------|-----------------|--------------------------------------------|
| NVIDIA GPU     | `--device cuda`   | Requer PyTorch com CUDA                   |
| Apple Silicon  | `--device mps`    | Automático com PyTorch 2.12+              |
| Intel GPU      | `--device intel:gpu`  | Via OpenVINO (`openvino:GPU`)         |
| Intel CPU      | `--device intel:cpu`  | Via OpenVINO (`openvino:CPU`)         |
| CPU genérico   | `--device cpu`    | Fallback universal                         |

---

## Re-identificação (contador)

Para cada detecção é extraído um vetor de aparência de **360 dimensões** a partir de um recorte de 48×96 px convertido para HSV e dividido em região superior e inferior do corpo. A correspondência usa distância cosseno (`modulos/contador.py:144`) com tolerância configurável:

- **Tolerância baixa** (ex: 0.001) → mata correspondências legítimas → super-contagem.
- **Tolerância alta** (ex: 0.10+) → funde pessoas diferentes → sub-contagem.
- **Padrão (0.005)** → bom equilíbrio para cores de roupa distintas.

Números de ajuste fino (EMA 0.7/0.3 por track, 0.6/0.4 + L2-norm por pessoa, peso 1.2× na região inferior) são intencionalmente calibrados — ver `CONTEXT.md`.

---

## Saídas

- **`arquivos/cardapio.json` / `.csv`** — dados estruturados do cardápio.
- **`arquivos/receitas.json` / `.csv`** — dados estruturados das receitas.
- **`arquivos/planilha.xlsx`** — planilha PBI (1 aba, 7 colunas).
- **Janelas OpenCV** (uma por fonte, ao rodar com janela): boxes coloridos por pessoa, painel `Pessoas unicas: N` e tecla **Q** para interromper.
- **Console**: progresso por etapa + contagem unificada; informações do dispositivo OpenVINO (solicitado vs. em uso); resultado final.

---

## Repositório

- Codeberg: [codeberg.org/yLipe/Projeto-TCC](https://codeberg.org/yLipe/Projeto-TCC)
