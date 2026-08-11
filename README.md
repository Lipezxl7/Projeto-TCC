# TCC — Regulamento Alimentar Escolar

Pipeline em Python + **app Streamlit** que integra gestão da alimentação escolar:
extrai o cardápio e as receitas de PDFs, conta pessoas únicas em vídeo (com
re-identificação visual) e calcula a produção e o **gasto do dia**.

Trabalho de Conclusão de Curso (TCC).

---

## App Streamlit (uso principal)

```bash
streamlit run app.py
```

Telas (menu lateral):

- **🎬 Contagem** — seleciona um vídeo da pasta `arquivos/`, roda YOLO + ByteTrack
  ao vivo (botões **Iniciar/Parar**) e estima o número de **alunos únicos**.
- **📊 Resultado** — a partir da contagem (ou valor manual), do cardápio do dia e
  das fichas técnicas, calcula produção, água e **gasto do dia** (custo de
  ingredientes). Editor de preços e exportação CSV/Excel.

### Geração dos dados (na própria UI)

Na tela **Resultado**, se `arquivos/cardapio.json` ou `arquivos/receitas.json`
ainda não existirem, use os botões:

- **Extrair receitas do PDF** → `arquivos/receitas.json` (via `modulos/receita.py`)
- **Extrair cardápio do PDF** (com seletor de mês) → `arquivos/cardapio.json` (via `modulos/cardapio.py`)

Os PDFs precisam estar em `arquivos/cardapio.pdf` e `arquivos/receita.pdf`.

---

## Requisitos

- **Python 3.11+** (3.14 NÃO recomendado — torch/ultralytics/openvino ainda sem wheels).
- `pip install -r requirements.txt` (streamlit, pandas, openpyxl, ultralytics,
  openvino, opencv-python, torch).
- (Opcional) GPU NVIDIA, Apple Silicon ou Intel para a etapa de contagem.

### torch por hardware

| Hardware       | Instruções                                                                 |
|----------------|----------------------------------------------------------------------------|
| **NVIDIA**     | `pip install torch --index-url https://download.pytorch.org/whl/cu121`      |
| **Apple Silicon** | `pip install torch` (MPS)                                             |
| **Intel (OpenVINO)** | OpenVINO já em `requirements.txt`                                      |
| **CPU**         | `pip install torch --index-url https://download.pytorch.org/whl/cpu`       |

> Mantenha o **ultralytics** atualizado (`>=8.3`) — modelos `yolo26n` exigem.
> O OpenVINO 2025+ removeu o alias `openvino.runtime`; o app aplica um shim
> automaticamente, mas atualizar o ultralytics é o recomendado.

---

## Estrutura do projeto

```
Projeto-TCC/
├── app.py                    # App Streamlit (Contagem + Resultado)
├── modulos/                  # fontes de verdade (não dependem da UI)
│   ├── __init__.py
│   ├── cardapio.py           # cardápio (PDF -> JSON)
│   ├── receita.py            # receitas (PDF -> JSON)
│   └── contador.py           # contagem de pessoas (YOLO + ByteTrack + HSV re-ID)
├── arquivos/                 # PDFs, vídeos e JSONs gerados (+ precos.json)
│   ├── cardapio.pdf, receita.pdf, video.mp4, video2.mp4, i2v6ti.mp4
│   ├── cardapio.json, receitas.json   (gerados sob demanda)
│   └── precos.json                    (tabela de preços editável na UI)
├── yolo26n.pt, yolo26x.pt ... yolo26n_openvino_model/   # modelos (gitignored)
├── requirements.txt
├── CONTEXT.md
└── README.md
```

`*.json`, `*.csv`, `*.pt` e `yolo*/` são gitignored (regenerados em execução).

---

## Uso modular (cada etapa isolada, CLI)

Cada módulo continua jogável standalone:

```bash
python -m modulos.cardapio arquivos/cardapio.pdf      # cardápio
python -m modulos.receita                             # receitas
python -m modulos.contador arquivos/video.mp4         # contagem (vídeo)
python -m modulos.contador --webcam                   # contagem (webcam)
python -m modulos.contador a.mp4 b.mp4 --webcam 0 --tolerance 0.02
```

### Argumentos do contador (standalone)

| Parâmetro          | Padrão       | Descrição                                                                  |
|--------------------|--------------|-----------------------------------------------------------------------------|
| `video` (posicional) | —          | Um ou mais vídeos (`nargs="*"`)                                             |
| `--webcam [IDX]`   | índice `0`   | Webcam como fonte; repetitível                                              |
| `--tolerance`      | `0.005`      | Limiar de similaridade (recomendado 0.003–0.10)                             |
| `--sample-rate`    | `3`          | Atualiza aparência a cada N frames                                          |
| `--img-size`       | `640`        | Resolução YOLO                                                              |
| `--model`          | `yolo26n.pt` | Modelo YOLO (`yolo26n`→`s`→`m`→`l`→`x`) ou `.pt` customizado                 |
| `--device`         | auto         | `cuda` \| `mps` \| `intel:gpu` \| `intel:cpu` \| `cpu`                       |
| `--no-window`      | off          | Modo headless                                                               |

---

## Cálculo do gasto do dia (tela Resultado)

Para cada prato do cardápio na data escolhida:

1. **Encontra a receita correspondente** via match por slug + maior sobreposição
   de tokens (≥ 50%).
2. Extrai `rendimento_g`, `porcao_*_g` (por segmento) e `agua` (ingrediente água).
3. `fator = (porcao × alunos) / rendimento_base`
4. **água (L)** = `(agua_base_g × fator) / 1000`
5. **custo (R$)** = `Σ qtd_ingrediente_g × fator × preço(ingrediente) / 1000`
   (preços em R$/kg, editáveis em `arquivos/precos.json`).

Saída: tabela por prato + métricas (alunos, água total, gasto total) + botões
CSV/Excel.

---

## Hardware suportado (contador)

Detecção automática via `modulos/contador.py`:

| Dispositivo    | Flag            | Notas                              |
|----------------|-----------------|------------------------------------|
| NVIDIA GPU     | `--device cuda` | Requer PyTorch com CUDA            |
| Apple Silicon  | `--device mps`  | MPS nativo                         |
| Intel GPU      | `intel:gpu`     | OpenVINO (`openvino:GPU`)          |
| Intel CPU      | `intel:cpu`     | OpenVINO (`openvino:CPU`)          |
| CPU genérico   | `cpu`           | Fallback universal                 |

No Streamlit, marque **auto** no menu lateral.

---

## Repositório

- Codeberg: [codeberg.org/yLipe/Projeto-TCC](https://codeberg.org/yLipe/Projeto-TCC)
