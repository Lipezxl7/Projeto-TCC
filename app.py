"""TCC — Gestão do Refeitório Escolar | App Streamlit (arquivo único).

Rodar com:
    streamlit run app.py

Estrutura:
  modulos/   -> fontes de verdade (cardapio, receita, contador)
  arquivos/  -> PDFs, vídeos e JSONs gerados (cardapio.json, receitas.json, precos.json)

Telas (menu lateral):
  🎬 Contagem   -> vídeo + IA (YOLO/ByteTrack) contando alunos únicos
  📊 Resultado  -> gasto do dia (cardápio + fichas técnicas + preços)
"""
from __future__ import annotations

import io
import json
import queue
import re
import threading
import time
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parent
ARQUIVOS = RAIZ / "arquivos"
SEGMENTOS = ["Fundamental", "Ensino Médio"]
SEG_CAMPO = {"Fundamental": "porcao_fund_g", "Ensino Médio": "porcao_em_g"}
MESES = {m: i + 1 for i, m in enumerate(
    ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"])}
MESES_NOMES = list(MESES.keys())

# ═══════════════════════════════════════════════════════════════════
#  CAMINHOS
# ═══════════════════════════════════════════════════════════════════

def _caminho(*partes: str) -> Path:
    return ARQUIVOS.joinpath(*partes)


CARDAPIO_PDF = _caminho("cardapio.pdf")
RECEITA_PDF = _caminho("receita.pdf")
CARDAPIO_JSON = _caminho("cardapio.json")
RECEITAS_JSON = _caminho("receitas.json")
PRECOS_JSON = _caminho("precos.json")

# ═══════════════════════════════════════════════════════════════════
#  GERAÇÃO DE DADOS (modulos)
# ═══════════════════════════════════════════════════════════════════

def gerar_cardapio(mes: str) -> None:
    """Extrai o cardápio do PDF (se ausente) usando modulos.cardapio."""
    if CARDAPIO_JSON.exists():
        return
    if not CARDAPIO_PDF.exists():
        st.error(f"PDF do cardápio não encontrado: {CARDAPIO_PDF}")
        return
    from modulos import cardapio
    cardapio.executar_extracao(
        str(CARDAPIO_PDF), str(CARDAPIO_JSON), mes=mes,
        salvar_json=True, salvar_csv=False)


def gerar_receitas() -> None:
    """Extrai as receitas do PDF (se ausente) usando modulos.receita."""
    if RECEITAS_JSON.exists():
        return
    if not RECEITA_PDF.exists():
        st.error(f"PDF das receitas não encontrado: {RECEITA_PDF}")
        return
    from modulos import receita
    recipes = receita.extract_recipes(str(RECEITA_PDF))
    receita.save_json(recipes, str(RECEITAS_JSON))

# ═══════════════════════════════════════════════════════════════════
#  DADOS: receitas, cardápio e preços
# ═══════════════════════════════════════════════════════════════════

def _sem_acento(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c))


def _slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _sem_acento(texto).lower())


def _parse_gramas(texto) -> float:
    """'12kg' -> 12000 | '50g (120g cozido)' -> 120 (prefere o parêntese)."""
    if texto is None:
        return 0.0
    if isinstance(texto, (int, float)):
        return float(texto)
    s = str(texto).lower()
    m = re.search(r"\((\d[\d.,]*)\s*(kg|g|gramas|l|litros|ml)?", s) or \
        re.search(r"(\d[\d.,]*)\s*(kg|g|gramas|l|litros|ml)?", s)
    if not m:
        return 0.0
    try:
        valor = float(m.group(1).replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0
    if (m.group(2) or "").strip() in ("kg", "l", "litros"):
        valor *= 1000.0
    return valor


@st.cache_data(show_spinner="Carregando fichas técnicas...")
def carregar_receitas(_path: str) -> dict[str, dict]:
    with open(_path, "r", encoding="utf-8") as f:
        brutas = json.load(f)
    banco = {}
    for r in brutas:
        ings = []
        for ing in r.get("ingredientes", []):
            qtd = ing.get("quantidade_g_ml")
            if qtd is None:
                qtd = ing.get("peso_base_g")
            ings.append({
                "nome": ing.get("ingrediente") or ing.get("nome") or "",
                "qtd": float(qtd) if isinstance(qtd, (int, float)) else _parse_gramas(qtd),
            })
        chave = _slug(r.get("nome", ""))
        if chave:
            banco[chave] = {
                "nome": r.get("nome", ""),
                "rendimento_g": _parse_gramas(r.get("rendimento", "")),
                "porcao_fund_g": _parse_gramas(r.get("porcao_fund", "")),
                "porcao_em_g": _parse_gramas(r.get("porcao_em_eja", "")),
                "ingredientes": ings,
            }
    return banco


STOP = {"de", "do", "da", "com", "ao", "a", "e", "em", "no", "na", "the"}


def _tokens(texto: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", _sem_acento(texto).lower()) if t and t not in STOP}


def buscar_receita(banco: dict, prato: str) -> dict | None:
    """Match exato por slug ou maior sobreposição de tokens (>= 50%)."""
    slug = _slug(prato)
    if slug in banco:
        return banco[slug]
    toks = _tokens(prato)
    melhor, melhor_score = None, 0.0
    for rec in banco.values():
        inter = len(toks & _tokens(rec["nome"]))
        if inter:
            score = inter / max(len(toks), 1)
            if score > melhor_score:
                melhor, melhor_score = rec, score
    return melhor if melhor_score >= 0.5 else None


def normalizar_data(valor) -> str:
    """Qualquer data -> chave 'dd/mm' do cardápio."""
    if isinstance(valor, date):
        return valor.strftime("%d/%m")
    s = str(valor).strip()
    m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        return f"{int(m.group(3)):02d}/{int(m.group(2)):02d}"
    m = re.match(r"(\d{1,2})[/-](\d{1,2})", s)
    if m:
        return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}"
    m = re.match(r"(\d{1,2})/([a-zç]+)", s, re.IGNORECASE)
    if m and m.group(2).lower().rstrip(".") in MESES:
        return f"{int(m.group(1)):02d}/{MESES[m.group(2).lower().rstrip('.')]:02d}"
    return ""


def pratos_do_dia(data) -> list[str]:
    try:
        with open(CARDAPIO_JSON, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    chave = normalizar_data(data)
    for d in dados:
        if normalizar_data(d.get("data", "")) == chave:
            return [p for p in d.get("pratos", []) if p and "REFEIÇÃO" not in p.upper()]
    return []


@st.cache_data(show_spinner="Carregando preços...")
def carregar_precos(_path: str) -> dict[str, float]:
    try:
        with open(_path, "r", encoding="utf-8") as f:
            return {k: float(v) for k, v in json.load(f).items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def salvar_precos(precos: dict[str, float]) -> None:
    with open(PRECOS_JSON, "w", encoding="utf-8") as f:
        json.dump(precos, f, ensure_ascii=False, indent=2)


def _migrar_precos() -> None:
    """Move precos.json da raiz para arquivos/ (se só houver na raiz)."""
    if PRECOS_JSON.exists():
        return
    raiz = RAIZ / "precos.json"
    if raiz.exists():
        try:
            raiz.replace(PRECOS_JSON)
            return
        except OSError:
            pass
    #Plantar defaults de exemplo
    if not PRECOS_JSON.exists():
        salvar_precos({
            "arroz": 6.50, "feijao": 8.00, "frango": 12.00,
            "carne bovina": 25.00, "carne moida": 22.00, "carne suina": 18.00,
            "oleo": 7.00, "sal": 2.00, "cebola": 5.00, "alho": 15.00,
            "tomate": 6.00, "batata": 5.00, "mandioca": 4.00, "abobora": 4.00,
            "macarrao": 5.00, "agua": 0.0, "ovo": 0.80, "milho": 4.00,
            "couve": 4.00, "alface": 3.00, "repolho": 3.50, "beterraba": 5.00,
            "abobrinha": 5.00, "banana": 5.00, "tangerina": 6.00, "abacaxi": 8.00,
            "extrato de tomate": 10.00, "molho de tomate": 8.00,
            "farinha de trigo": 5.00, "farinha de mandioca": 6.00,
        })


def preco_ingrediente(nome: str, precos: dict) -> float | None:
    alvo = _sem_acento(nome).lower().strip()
    melhor_chave, melhor_len = None, 0
    for chave in precos:
        c = _sem_acento(chave).lower().strip()
        if c and c in alvo and len(c) > melhor_len:
            melhor_chave, melhor_len = chave, len(c)
    return precos[melhor_chave] if melhor_chave else None


def _eh_agua(nome: str) -> bool:
    n = _sem_acento(nome).lower()
    return "agua" in n


def calcular_dia(alunos: int, pratos: list[str], segmento: str,
                 banco: dict, precos: dict) -> pd.DataFrame:
    """Linhas: prato, receita, porção, fator, água (L), custo (R$), avisos."""
    campo = SEG_CAMPO.get(segmento, "porcao_em_g")
    linhas = []
    for nome in pratos:
        rec = buscar_receita(banco, nome)
        if rec is None:
            linhas.append({"Prato": nome, "Receita": "—", "Porção (g)": 0.0, "Fator": 0.0,
                           "Água (L)": 0.0, "Custo (R$)": 0.0, "Avisos": "sem ficha técnica"})
            continue

        porcao = rec.get(campo) or 0.0
        rend = rec.get("rendimento_g") or 0.0
        fator = (porcao * alunos) / rend if porcao > 0 and rend > 0 else 0.0

        agua, custo, sem_preco = 0.0, 0.0, []
        for ing in rec.get("ingredientes", []):
            qtd = float(ing.get("qtd") or 0.0)
            if _eh_agua(ing["nome"]):
                agua = qtd * fator / 1000.0
                continue
            preco = preco_ingrediente(ing["nome"], precos)
            if preco is None:
                if qtd > 0:
                    sem_preco.append(ing["nome"])
                continue
            custo += qtd * fator * preco / 1000.0  # g -> kg

        aviso = f"sem preço: {', '.join(sem_preco[:3])}" if sem_preco else ""
        linhas.append({"Prato": nome, "Receita": rec["nome"], "Porção (g)": porcao,
                       "Fator": round(fator, 2), "Água (L)": round(agua, 2),
                       "Custo (R$)": round(custo, 2), "Avisos": aviso})

    return pd.DataFrame(linhas)

# ═══════════════════════════════════════════════════════════════════
#  CONTAGEM: engine em thread + fila de frames (para o Streamlit)
# ═══════════════════════════════════════════════════════════════════

_MODULO_CONTADOR = None


def _get_contador():
    """Importa modulos.contador apenas quando necessário (torch/ultralytics)."""
    global _MODULO_CONTADOR
    if _MODULO_CONTADOR is None:
        from modulos import contador
        _MODULO_CONTADOR = contador
    return _MODULO_CONTADOR


class CounterEngine:
    def __init__(self, video_path: str, modelo: str = "yolo26n.pt",
                 device: str | None = None, tolerancia: float = 0.005,
                 sample_rate: int = 1, img_size: int = 640):
        self.video_path = video_path
        self.modelo = modelo
        self.device, self.device_desc = _get_contador().detect_device(device)
        self.tolerancia = tolerancia
        self.sample_rate = sample_rate
        self.img_size = img_size
        self._fila: queue.Queue = queue.Queue(maxsize=1)
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self.done = False
        self.final_count: int | None = None
        self.live_count = 0
        self.error: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._parar.clear()
        self.done, self.final_count, self.error = False, None, None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._parar.set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def get_frame(self, timeout: float = 0.1):
        try:
            return self._fila.get(timeout=timeout)
        except queue.Empty:
            return None

    def has_pending(self) -> bool:
        return not self._fila.empty()

    def _run(self) -> None:
        try:
            total = _get_contador().count_unique_people(
                [(False, self.video_path, "video")],
                tolerance=self.tolerancia,
                sample_rate=self.sample_rate,
                img_size=self.img_size,
                show_window=False,
                device=self.device,
                model_name=self.modelo,
                frame_queue=self._fila,
                status_cb=lambda n: self._set_live(n),
                stop_event=self._parar,
            )
            self.final_count = total
            self.live_count = total
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
        finally:
            self.done = True

    def _set_live(self, n: int) -> None:
        self.live_count = n


def _engine() -> CounterEngine | None:
    return st.session_state.get("engine")


def _criar_engine(video, modelo, device, tolerancia, sample_rate, img_size) -> CounterEngine:
    eng = _engine()
    if eng is not None:
        eng.stop()
    eng = CounterEngine(str(video), modelo, device, tolerancia, sample_rate, img_size)
    st.session_state["engine"] = eng
    st.session_state.pop("contagem_final", None)
    return eng

# ═══════════════════════════════════════════════════════════════════
#  TELA 1 — CONTAGEM
# ═══════════════════════════════════════════════════════════════════

def _listar_videos() -> list[str]:
    exts = ("*.mp4", "*.avi", "*.mov", "*.mkv")
    return sorted(p.name for ext in exts for p in ARQUIVOS.glob(ext) if p.is_file())


def tela_contagem() -> None:
    st.title("🎬 Contagem de Alunos com IA")
    st.caption("Detecção **YOLO** + **ByteTrack** + correspondência de aparência (HSV).")

    videos = _listar_videos()

    with st.sidebar:
        st.header("⚙️ Contagem")
        video = st.selectbox("🎥 Vídeo", videos if videos else ["—"])
        modelo = st.selectbox("🤖 Modelo YOLO",
                              ["yolo26n.pt", "yolo26x.pt", "yolo11x.pt",
                               "yolov8s.pt", "yolov8n.pt"])
        tolerancia = st.slider("🎯 Tolerância", 0.001, 0.35, 0.005, 0.001,
                               help="Menor = exige mais semelhança para contar como a mesma pessoa.")
        sample_rate = st.slider("🔁 Sample rate", 1, 10, 1)
        img_size = st.selectbox("🖼️ Resolução", [320, 480, 640, 768, 1024], index=2)
        device = st.selectbox("🖥️ Hardware",
                              ["auto", "cpu", "intel:gpu", "intel:cpu", "cuda", "mps"],
                              help="'auto' escolhe o melhor disponível.")

    if not videos:
        st.warning("Nenhum vídeo (.mp4/.avi/.mov/.mkv) na pasta `arquivos/`.")
        return

    eng = _engine()
    if eng is not None and eng.video_path != str(ARQUIVOS / video):
        eng.stop()
        st.session_state.pop("engine", None)
        st.rerun()

    if eng is not None and eng.error:
        st.error(f"❌ Erro na contagem: {eng.error}")
        st.session_state.pop("engine", None)
        st.rerun()

    c1, c2, c3 = st.columns([1, 1, 2])
    iniciar = c1.button("▶️ Iniciar contagem", type="primary",
                        disabled=eng is not None and eng.running)
    parar = c2.button("⏹️ Parar", disabled=eng is None or not eng.running)

    if iniciar:
        try:
            _get_contador()  # valida dependências de visão antes de começar
        except ImportError:
            st.error("Dependências de visão computacional não instaladas "
                     "(torch / ultralytics / opencv / openvino).")
            st.code("pip install torch ultralytics opencv-python openvino", language="bash")
            return
        eng = _criar_engine(ARQUIVOS / video, modelo, None if device == "auto" else device,
                            tolerancia, sample_rate, img_size)
        eng.start()

    if parar and eng is not None:
        eng.stop()

    # Exibição ao vivo (fatia de ~4s por rerun; assim o "Parar" fica clicável)
    if eng is not None and (eng.running or eng.has_pending()):
        ph = st.empty()
        t0 = time.monotonic()
        while time.monotonic() - t0 < 4.0:
            frame = eng.get_frame(timeout=0.05)
            if frame is not None:
                ph.image(frame, channels="BGR")
            if not eng.running and not eng.has_pending():
                break
            time.sleep(0.02)
        st.rerun()

    if eng is not None:
        st.metric("👥 Pessoas únicas (ao vivo)", eng.live_count)
        if eng.done and eng.final_count is not None:
            st.session_state["contagem_final"] = eng.final_count
            st.success(f"✅ Contagem concluída: **{eng.final_count}** aluno(s).")
            if st.button("📊 Ver o gasto do dia"):
                st.session_state["pagina"] = "Resultado"
                st.rerun()
        elif not eng.running and not eng.has_pending() and not eng.done:
            st.info("Configure e clique em **▶️ Iniciar contagem**.")

    elif "contagem_final" in st.session_state:
        st.metric("👥 Alunos (última contagem)", st.session_state["contagem_final"])
        if st.button("📊 Ver o gasto do dia"):
            st.session_state["pagina"] = "Resultado"
            st.rerun()

# ═══════════════════════════════════════════════════════════════════
#  TELA 2 — RESULTADO / GASTO DO DIA
# ═══════════════════════════════════════════════════════════════════

def tela_resultado() -> None:
    st.title("📊 Resultado do dia")
    st.caption("Produção estimada e **gasto do dia** com base na contagem de alunos.")

    _migrar_precos()

    eng = _engine()
    if eng is not None and eng.done and eng.final_count is not None:
        st.session_state["contagem_final"] = eng.final_count

    # Geração automática dos dados (se os PDFs existirem e os JSONs não)
    with st.expander("📂 Geração dos dados (PDFs)", expanded=not RECEITAS_JSON.exists()):
        faltando = []
        if not RECEITAS_JSON.exists():
            faltando.append("receitas.json")
        if not CARDAPIO_JSON.exists():
            faltando.append("cardapio.json")
        if faltando:
            st.caption(f"Faltando gerar: {', '.join(faltando)}")
        c_rec, c_car = st.columns(2)
        if c_rec.button("Extrair receitas do PDF"):
            gerar_receitas()
            st.rerun()
        mes_sel = c_car.selectbox("Mês do cardápio", MESES_NOMES, index=5)
        if c_car.button("Extrair cardápio do PDF"):
            gerar_cardapio(mes_sel)
            st.rerun()

    if not RECEITAS_JSON.exists():
        st.warning("Gere as receitas (`Extrair receitas do PDF`) antes de calcular.")
        return

    banco = carregar_receitas(str(RECEITAS_JSON))
    precos = carregar_precos(str(PRECOS_JSON))

    default_alunos = st.session_state.get("contagem_final", 0)
    c_data, c_seg, c_alu = st.columns([2, 2, 1])
    data_dia = c_data.date_input("📅 Data", value=date.today())
    segmento = c_seg.selectbox("🏫 Segmento", SEGMENTOS)
    alunos = c_alu.number_input("👥 Alunos", min_value=0,
                                value=int(default_alunos), step=1)
    if default_alunos:
        st.caption(f"Valor da última contagem: **{default_alunos}** (editável acima).")

    pratos_auto = pratos_do_dia(data_dia)
    opcoes = list(dict.fromkeys(pratos_auto + sorted(r["nome"] for r in banco.values())))
    pratos = st.multiselect(
        "🍽️ Pratos do dia (automático pelo cardápio, editável)",
        options=opcoes, default=pratos_auto)

    if not pratos:
        st.warning("Selecione ao menos um prato.")
        return

    df = calcular_dia(alunos, pratos, segmento, banco, precos)
    agua_total = df["Água (L)"].sum()
    custo_total = df["Custo (R$)"].sum()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("👥 Alunos", f"{alunos}")
    m2.metric("🍽️ Pratos", f"{len(pratos)}")
    m3.metric("💧 Água total", f"{agua_total:.2f} L")
    m4.metric("💰 Gasto do dia", f"R$ {custo_total:.2f}")

    st.dataframe(df, width="stretch", hide_index=True)

    sem_preco = set()
    for aviso in df["Avisos"].tolist():
        if aviso.startswith("sem preço:"):
            sem_preco.update(a.strip() for a in aviso.replace("sem preço:", "").split(","))
    if sem_preco:
        st.warning(f"Ingredientes sem preço cadastrado (não somam no custo): "
                   f"{', '.join(sorted(sem_preco))}. Complete na seção de preços abaixo.")
    if (df["Avisos"] == "sem ficha técnica").any():
        st.warning("Alguns pratos não têm ficha técnica no receitas.json. "
                   "Ajuste a seleção ou gere novamente as receitas.")

    # Exportação
    st.divider()
    col_x, col_y = st.columns(2)
    fname = f"producao_{data_dia.strftime('%Y-%m-%d')}"
    col_x.download_button("📥 Baixar CSV", df.to_csv(index=False, sep=";", encoding="utf-8-sig"),
                          file_name=f"{fname}.csv", mime="text/csv", width="stretch")
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="producao")
    col_y.download_button("📥 Baixar Excel", buf.getvalue(),
                          file_name=f"{fname}.xlsx", width="stretch",
                          mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # Editor de preços
    st.divider()
    with st.expander("💲 Tabela de preços (R$/kg por ingrediente)"):
        df_precos = pd.DataFrame(
            [{"Ingrediente": k, "Preço (R$/kg)": v} for k, v in precos.items()])
        editado = st.data_editor(df_precos, num_rows="dynamic",
                                 width="stretch", hide_index=True,
                                 key="editor_precos")
        if st.button("💾 Salvar preços", type="primary"):
            novos = {str(r["Ingrediente"]).strip(): float(r["Preço (R$/kg)"])
                     for _, r in editado.iterrows() if str(r["Ingrediente"]).strip()}
            salvar_precos(novos)
            carregar_precos.clear()
            st.success("Preços salvos! Recalcule acima para atualizar o custo.")
            st.rerun()

# ═══════════════════════════════════════════════════════════════════
#  APP
# ═══════════════════════════════════════════════════════════════════

st.set_page_config(page_title="TCC — Refeitório", page_icon="🍽️", layout="wide")

if "pagina" not in st.session_state:
    st.session_state["pagina"] = "Contagem"

with st.sidebar:
    st.header("🍽️ Refeitório — TCC")
    pagina = st.radio("Navegação", ["Contagem", "Resultado"],
                      index=0 if st.session_state["pagina"] == "Contagem" else 1,
                      key="nav")
    st.session_state["pagina"] = pagina

if pagina == "Contagem":
    tela_contagem()
else:
    tela_resultado()

st.sidebar.caption("— visão computacional + gestão de produção —")
