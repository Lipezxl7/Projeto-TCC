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
  das fichas técnicas, calcula a produção do dia em **kg de alimento** e
  **litros de água** (gasto do dia). Exportação CSV/Excel.

### Geração dos dados (na própria UI)

Na tela **Resultado**, use os botões (eles (re)geram os JSONs, sobrescrevendo
os existentes, com feedback de sucesso/erro):

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
| **Intel (OpenVINO)** | OpenVINO já em `requirements.txt` + driver de compute da GPU (abaixo) |
| **CPU**         | `pip install torch --index-url https://download.pytorch.org/whl/cpu`       |

> Mantenha o **ultralytics** atualizado (`>=8.4`) — modelos `yolo26n` exigem e o
> device nativo `intel:gpu` também. O OpenVINO 2025+ removeu o alias
> `openvino.runtime`; o app aplica um shim automaticamente.

### Pacotes de sistema (o que não vem pelo pip)

Só o **driver da GPU** exige pacote do sistema operacional. Sem ele, torch/OpenVINO
não enxergam a GPU e a contagem cai pro CPU — o app avisa na tela quando isso
acontece ("⚠️ ... não está disponível nesta máquina").

| Hardware       | Arch / CachyOS                            | Ubuntu / Debian                                  | Como conferir |
|----------------|-------------------------------------------|--------------------------------------------------|---------------|
| **Intel GPU (OpenVINO)** | `intel-compute-runtime`          | `intel-opencl-icd`                               | `python -c "import openvino as ov; print(ov.Core().available_devices)"` → precisa listar `GPU` |
| **NVIDIA (CUDA)** | `nvidia` (ou `nvidia-open`) + `nvidia-utils` | `sudo ubuntu-drivers autoinstall` (ou `nvidia-driver-XXX`) | `nvidia-smi` |
| **Apple Silicon (MPS)** | — (driver vem com o macOS)             | —                                                | torch detecta sozinho |
| **Só CPU**     | nada extra                                | nada extra                                        | — |

> **GPU Intel:** `intel-media-driver` (codecs de vídeo) **não serve** para
> inferência — o OpenVINO precisa do *compute runtime* (driver Level-Zero/OpenCL
> "NEO"). Se `available_devices` só lista `['CPU']`, é exatamente isso que está
> faltando.
> **NVIDIA:** não instale o CUDA Toolkit — os wheels do PyTorch já embutem o
> runtime CUDA; só o driver importa.
> **Vídeos e webcam:** nada extra no sistema — o wheel `opencv-python` já embute
> o FFmpeg e o v4l2 faz parte do kernel Linux.

---

## Estrutura do projeto

```
Projeto-TCC/
├── app.py                    # App Streamlit (Contagem + Resultado)
├── modulos/                  # fontes de verdade (não dependem da UI)
│   ├── __init__.py
│   ├── calculo.py            # lógica pura do Resultado (parsing, matching, cálculo)
│   ├── cardapio.py           # cardápio (PDF -> JSON)
│   ├── receita.py            # receitas (PDF -> JSON)
│   └── contador.py           # contagem de pessoas (YOLO + ByteTrack + HSV re-ID)
├── tests/                    # pytest (lógica pura + extratores de PDF)
├── arquivos/                 # PDFs, vídeos e JSONs gerados
│   ├── cardapio.pdf, receita.pdf, video.mp4, video2.mp4
│   └── cardapio.json, receitas.json   (gerados sob demanda)
├── yolo26n.pt, yolo26x.pt ... yolo26n_openvino_model/   # modelos (gitignored)
├── requirements.txt          # deps de runtime (com pisos mínimos)
├── requirements-dev.txt      # pytest
├── pyproject.toml            # config do pytest
├── AGENTS.md                 # rampa rápida para agentes de IA
├── CONTEXT.md                # referência profunda da arquitetura
└── README.md
```

`*.json`, `*.csv`, `*.pt` e `yolo*/` são gitignored (regenerados em execução).

---

## Uso modular (cada etapa isolada, CLI)

Cada módulo continua jogável standalone:

```bash
python -m modulos.cardapio arquivos/cardapio.pdf --mes jun   # cardápio
python -m modulos.receita                                    # receitas (arquivos/receita.pdf)
python -m modulos.contador arquivos/video.mp4         # contagem (vídeo)
python -m modulos.contador --webcam                   # contagem (webcam)
python -m modulos.contador a.mp4 b.mp4 --webcam 0 --tolerance 0.02
```

> `--mes` omitido → o cardápio pergunta o mês interativamente (stdin).
> `modulos.receita` aceita um caminho opcional de PDF e gera
> `arquivos/receitas.json` + `receitas.csv` (os nomes que o app lê).

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

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

Os testes cobrem a lógica pura (`modulos/calculo.py`) e os extratores de
PDF contra os arquivos reais de `arquivos/` — **não precisam de
torch/ultralytics**. Ainda não há linter nem CI.

---

## Cálculo do gasto do dia (tela Resultado)

Para cada prato do cardápio na data escolhida:

1. **Encontra a receita correspondente** via match por slug + maior sobreposição
   de tokens (≥ 50%).
2. Extrai `rendimento_g`, `porcao_*_g` (por segmento) e **soma a água de
   todos os ingredientes "água"** da receita.
3. `fator = (porcao × alunos) / rendimento_base`
4. **água (L)** = `Σ (agua_base_g × fator) / 1000`
5. **kg a produzir** = `(porcao × alunos) / 1000`

Saída: tabela por prato + métricas (alunos, pratos, água total, kg total) +
botões CSV/Excel.

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
- Guias para agentes de IA: **`AGENTS.md`** (rampa rápida) e **`CONTEXT.md`**
  (arquitetura profunda).
