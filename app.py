"""TCC — Gestão do Refeitório Escolar | App Streamlit (arquivo único).

Rodar com:
    streamlit run app.py

Estrutura:
  modulos/   -> fontes de verdade (calculo, cardapio, receita, contador)
  arquivos/  -> PDFs, vídeos e JSONs gerados (cardapio.json, receitas.json)

Telas (menu lateral):
  Contagem   -> vídeo + IA (YOLO/ByteTrack) contando alunos únicos
  Resultado  -> produção do dia em kg de alimento e litros de água
"""
from __future__ import annotations

import hashlib
import io
import json
import queue
import threading
import time
from datetime import date
from pathlib import Path

import streamlit as st
from streamlit.components.v1 import html as st_html

from modulos import calculo

RAIZ = Path(__file__).resolve().parent
ARQUIVOS = RAIZ / "arquivos"

# ═══════════════════════════════════════════════════════════════════
#  CAMINHOS
# ═══════════════════════════════════════════════════════════════════

def _caminho(*partes: str) -> Path:
    return ARQUIVOS.joinpath(*partes)


CARDAPIO_PDF = _caminho("cardapio.pdf")
RECEITA_PDF = _caminho("receita.pdf")
CARDAPIO_JSON = _caminho("cardapio.json")
RECEITAS_JSON = _caminho("receitas.json")


# ════════════════════════════════════════════════════════════════════
#  CACHE NO LOCALSTORAGE (browser)
# ════════════════════════════════════════════════════════════════════

# Chaves do localStorage
_LS_KEY_RECEITAS = "tcc_receitas_json"
_LS_KEY_RECEITAS_HASH = "tcc_receitas_hash"
_LS_KEY_CARDAPIO = "tcc_cardapio_json"
_LS_KEY_CARDAPIO_HASH = "tcc_cardapio_hash"

def _pdf_hash(pdf_path: Path) -> str:
    """Retorna MD5 do arquivo PDF (string hex)."""
    h = hashlib.md5()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def _ls_get(key: str) -> str | None:
    """Lê uma chave do localStorage via session_state (preenchido por JS)."""
    return st.session_state.get(f"_ls_{key}")

def _ls_set(key: str, value: str) -> None:
    """Escreve no session_state e no localStorage via st_javascript."""
    st.session_state[f"_ls_{key}"] = value
    # Escrita no localStorage via st_javascript (fire-and-forget)
    try:
        st.javascript(f'localStorage.setItem("{key}", {json.dumps(value)});')
    except Exception:
        pass

def _cache_get_receitas() -> tuple[dict | None, str | None]:
    """Retorna (dados, hash_salvo) do cache de receitas."""
    dados_str = _ls_get(_LS_KEY_RECEITAS)
    hash_salvo = _ls_get(_LS_KEY_RECEITAS_HASH)
    if dados_str:
        try:
            return json.loads(dados_str), hash_salvo
        except Exception:
            pass
    return None, None

def _cache_set_receitas(dados: dict, hash_pdf: str) -> None:
    """Salva receitas + hash no cache."""
    _ls_set(_LS_KEY_RECEITAS, json.dumps(dados, ensure_ascii=False, separators=(",", ":")))
    _ls_set(_LS_KEY_RECEITAS_HASH, hash_pdf)

def _cache_get_cardapio() -> tuple[dict | None, str | None]:
    """Retorna (dados, hash_salvo) do cache de cardápio."""
    dados_str = _ls_get(_LS_KEY_CARDAPIO)
    hash_salvo = _ls_get(_LS_KEY_CARDAPIO_HASH)
    if dados_str:
        try:
            return json.loads(dados_str), hash_salvo
        except Exception:
            pass
    return None, None

def _cache_set_cardapio(dados: dict, hash_pdf: str) -> None:
    """Salva cardápio + hash no cache."""
    _ls_set(_LS_KEY_CARDAPIO, json.dumps(dados, ensure_ascii=False, separators=(",", ":")))
    _ls_set(_LS_KEY_CARDAPIO_HASH, hash_pdf)

def _cache_clear_all() -> None:
    """Limpa todo o cache do app (session_state + localStorage)."""
    for key in [_LS_KEY_RECEITAS, _LS_KEY_RECEITAS_HASH, _LS_KEY_CARDAPIO, _LS_KEY_CARDAPIO_HASH]:
        st.session_state.pop(f"_ls_{key}", None)
    js = f"""
    <script>
    const keys = ["{_LS_KEY_RECEITAS}", "{_LS_KEY_RECEITAS_HASH}", "{_LS_KEY_CARDAPIO}", "{_LS_KEY_CARDAPIO_HASH}"];
    keys.forEach(k => localStorage.removeItem(k));
    </script>
    """
    st_html(js, height=0, width=0)

# ════════════════════════════════════════════════════════════════════
#  GERAÇÃO DE DADOS (modulos)
# ═══════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════
#  GERAÇÃO DE DADOS (modulos)
# ═══════════════════════════════════════════════════════════════════

def gerar_cardapio(mes: str) -> int:
    """Extrai o cardápio do PDF usando modulos.cardapio (com cache no localStorage).

    Se o PDF não mudou (mesmo hash), carrega do localStorage instantaneamente.
    Caso contrário, extrai, salva JSON no disco + no localStorage.
    """
    if not CARDAPIO_PDF.exists():
        raise FileNotFoundError(f"PDF do cardápio não encontrado: {CARDAPIO_PDF}")

    # Hash do PDF atual
    hash_atual = _pdf_hash(CARDAPIO_PDF)

    # Tenta cache do localStorage
    cached_dados, cached_hash = _cache_get_cardapio()
    if cached_dados is not None and cached_hash == hash_atual:
        # Cache válido → salva no disco e retorna
        cardapio.save_json(cached_dados, str(CARDAPIO_JSON))
        return len(cached_dados)

    # Cache inválido/inexistente → extrai do PDF
    from modulos import cardapio
    dados = cardapio.executar_extracao(
        str(CARDAPIO_PDF), str(CARDAPIO_JSON), mes=mes,
        salvar_json=True, salvar_csv=False)

    # Salva no localStorage para próxima vez
    _cache_set_cardapio(dados, hash_atual)
    return len(dados)


def gerar_receitas() -> int:
    """Extrai as receitas do PDF usando modulos.receita (com cache no localStorage).

    Se o PDF não mudou (mesmo hash), carrega do localStorage instantaneamente.
    Caso contrário, extrai, salva JSON no disco + no localStorage.
    """
    if not RECEITA_PDF.exists():
        raise FileNotFoundError(f"PDF das receitas não encontrado: {RECEITA_PDF}")

    # Hash do PDF atual
    hash_atual = _pdf_hash(RECEITA_PDF)

    # Tenta cache do localStorage
    cached_dados, cached_hash = _cache_get_receitas()
    if cached_dados is not None and cached_hash == hash_atual:
        # Cache válido → salva no disco e retorna
        receita.save_json(cached_dados, str(RECEITAS_JSON))
        return len(cached_dados)

    # Cache inválido/inexistente → extrai do PDF
    from modulos import receita
    recipes = receita.extract_recipes(str(RECEITA_PDF))
    receita.save_json(recipes, str(RECEITAS_JSON))

    # Salva no localStorage para próxima vez
    _cache_set_receitas(recipes, hash_atual)
    return len(recipes)


@st.cache_data(show_spinner="Carregando fichas técnicas...")
def carregar_receitas(caminho: str) -> dict[str, dict]:
    return calculo.carregar_receitas(caminho)


# ═══════════════════════════════════════════════════════════════════
#  CONTAGEM: engine em thread + fila de frames (para o Streamlit)
# ═══════════════════════════════════════════════════════════════════

_MODULO_CONTADOR = None

# device pedido na UI -> device resolvido esperado (p/ avisar quando cai p/ outro)
_DISPOSITIVO_ESPERADO = {
    "cuda": "cuda", "mps": "mps",
    "intel:gpu": "openvino:GPU", "intel:cpu": "openvino:CPU", "cpu": "cpu",
}


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
                 sample_rate: int = 3, img_size: int = 640):
        self.video_path = video_path
        self.modelo = modelo
        self.device_pedido = device  # bruto, p/ avisar quando cair p/ outro
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
    st.title("Contagem alunos")
    st.caption("Detecção **YOLO** + **ByteTrack** + correspondência de aparência (HSV).")

    videos = _listar_videos()

    with st.sidebar:
        st.header(" Contagem")
        video = st.selectbox(" Vídeo", videos if videos else ["—"])
        modelo = st.selectbox(" Modelo YOLO",
                              ["yolo26n.pt", "yolo26x.pt", "yolo11x.pt",
                               "yolov8s.pt", "yolov8n.pt"])
        tolerancia = st.slider(" Tolerância", 0.001, 0.35, 0.005, 0.001,
                               help="Menor = exige mais semelhança para contar como a mesma pessoa.")
        sample_rate = st.slider(" Sample rate", 1, 10, 3)
        img_size = st.selectbox(" Resolução", [320, 480, 640, 768, 1024], index=2)
        device = st.selectbox(" Hardware",
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
        st.error(f"Erro na contagem: {eng.error}")
        st.session_state.pop("engine", None)
        st.rerun()

    # Mostra sempre o hardware que está rodando DE VERDADE — o detect_device
    # pode fazer fallback (ex.: GPU indisponível → CPU) e antes isso era invisível.
    if eng is not None:
        st.caption(f"Hardware em uso: {eng.device_desc}")
        esperado = _DISPOSITIVO_ESPERADO.get(eng.device_pedido or "")
        if esperado and eng.device != esperado:
            st.warning(
                f"**{eng.device_pedido}** não está disponível nesta máquina — "
                f"rodando em: **{eng.device_desc}**. "
                "Verifique o driver: no Linux/Intel o OpenVINO só lista a GPU com o "
                "compute runtime da Intel instalado (Arch: `sudo pacman -S "
                "intel-compute-runtime`; depois confira com "
                "`python -c \"import openvino as ov; print(ov.Core().available_devices)\"`)."
            )

    c1, c2 = st.columns([1, 1])
    iniciar = c1.button("Iniciar contagem", type="primary",
                        disabled=eng is not None and eng.running)
    parar = c2.button("Parar", disabled=eng is None or not eng.running)

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

    # ─── MODO AO VIVO (IA real) ───
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
        st.metric("Pessoas únicas (ao vivo)", eng.live_count)
        if eng.done and eng.final_count is not None:
            st.session_state["contagem_final"] = eng.final_count
            st.success(f" Contagem concluída: **{eng.final_count}** aluno(s).")
            if st.button(" Ver o gasto do dia"):
                st.session_state["pagina"] = "Resultado"
                st.rerun()
        elif not eng.running and not eng.has_pending() and not eng.done:
            st.info("Configure e clique em **Iniciar contagem**.")

    elif "contagem_final" in st.session_state:
        st.metric(" Alunos (última contagem)", st.session_state["contagem_final"])
        if st.button(" Ver o gasto do dia"):
            st.session_state["pagina"] = "Resultado"
            st.rerun()

# ═══════════════════════════════════════════════════════════════════
#  TELA 2 — RESULTADO / GASTO DO DIA
# ═══════════════════════════════════════════════════════════════════

def tela_resultado() -> None:
    st.title(" Resultado do dia")
    st.caption("Produção estimada do dia (kg de alimento e litros de água) "
               "com base na contagem de alunos.")

    eng = _engine()
    if eng is not None and eng.done and eng.final_count is not None:
        st.session_state["contagem_final"] = eng.final_count

    # ─── VERIFICAÇÃO DE CACHE (receitas + cardápio do mês) ───
    mes_sel_raw = st.session_state.get("mes_cardapio_sel", date.today().month - 1)
    if isinstance(mes_sel_raw, str):
        try:
            mes_sel = calculo.MESES_NOMES.index(mes_sel_raw)
        except ValueError:
            mes_sel = date.today().month - 1
    else:
        mes_sel = int(mes_sel_raw)
    mes_nome = calculo.MESES_NOMES[mes_sel]

    hash_receita_atual = _pdf_hash(RECEITA_PDF) if RECEITA_PDF.exists() else None
    hash_cardapio_atual = _pdf_hash(CARDAPIO_PDF) if CARDAPIO_PDF.exists() else None

    cached_receitas, cached_hash_receitas = _cache_get_receitas()
    cached_cardapio, cached_hash_cardapio = _cache_get_cardapio()

    receitas_ok = cached_receitas is not None and cached_hash_receitas == hash_receita_atual
    cardapio_ok = cached_cardapio is not None and cached_hash_cardapio == hash_cardapio_atual

    n_receitas = len(cached_receitas) if cached_receitas else 0
    n_cardapio = len(cached_cardapio) if cached_cardapio else 0

    # ─── SIDEBAR: Dados disponíveis (status do cache) ───
    # As variáveis ficam disponíveis para a sidebar ler via session_state
    st.session_state["_cache_receitas_ok"] = receitas_ok
    st.session_state["_cache_n_receitas"] = n_receitas
    st.session_state["_cache_cardapio_ok"] = cardapio_ok
    st.session_state["_cache_n_cardapio"] = n_cardapio
    st.session_state["_cache_mes_nome"] = mes_nome

    # ─── EXTRAIR PDFs (expansível) ───
    with st.expander("Extrair PDFs", expanded=False):
        # ─── RECEITAS ───
        st.markdown("####  Receitas")
        if receitas_ok:
            st.success(f"✔ {n_receitas} receitas (cache)")
            if st.button("Re-extrair receitas", key="reextrair_rec", help="Força nova extração do PDF"):
                _cache_set_receitas({}, "")
                st.rerun()
        else:
            if st.button("Extrair receitas do PDF", type="primary", key="extrair_rec"):
                with st.spinner("Extraindo receitas do PDF..."):
                    try:
                        n = gerar_receitas()
                        carregar_receitas.clear()
                        st.success(f"receitas.json gerado ({n} receitas).")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Falha ao extrair receitas: {e}")

        st.divider()

        # ─── CARDÁPIO ───
        st.markdown("####  Cardápio")
        mes_sel = st.selectbox("Mês do cardápio", calculo.MESES_NOMES,
                               index=mes_sel, key="mes_cardapio_sel")
        
        # Recalcula cardapio_ok pro mês selecionado
        cached_cardapio_mes, cached_hash_cardapio_mes = _cache_get_cardapio()
        cardapio_ok_mes = cached_cardapio_mes is not None and cached_hash_cardapio_mes == hash_cardapio_atual
        n_cardapio_mes = len(cached_cardapio_mes) if cached_cardapio_mes else 0

        if cardapio_ok_mes:
            st.success(f"✔ {n_cardapio_mes} dias ({mes_sel})")
            if st.button("Re-extrair cardápio", key="reextrair_car", help="Força nova extração do PDF para este mês"):
                _cache_set_cardapio({}, "")
                st.rerun()
        else:
            if st.button("Extrair cardápio do PDF", type="primary", key="extrair_car"):
                with st.spinner(f"Extraindo cardápio ({mes_sel})..."):
                    try:
                        n = gerar_cardapio(mes_sel)
                        st.success(f"cardapio.json gerado ({n} dias).")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Falha ao extrair cardápio: {e}")

    # ─── OPÇÕES AVANÇADAS ───
    with st.expander("Opções avançadas"):
        if st.button("Limpar cache do navegador", help="Remove receitas e cardápio salvos no localStorage"):
            _cache_clear_all()
            st.success("Cache limpo. Próxima extração reprocessa os PDFs.")
            st.rerun()

    # ─── VALIDAÇÃO: precisa ter receitas extraídas (lê do cache do disco) ───
    receitas_json = st.session_state.get("_ls_tcc_receitas_json")
    receitas_hash = st.session_state.get("_ls_tcc_receitas_hash")
    receitas_ok = bool(receitas_json and receitas_hash)

    if not receitas_ok:
        st.warning(" Gere as receitas (`Extrair receitas do PDF`) antes de calcular.")
        return

    banco = carregar_receitas(str(RECEITAS_JSON))

    default_alunos = st.session_state.get("contagem_final", 0)
    c_data, c_seg, c_alu = st.columns([2, 2, 1])
    data_dia = c_data.date_input(" Data", value=date.today())
    segmento = c_seg.selectbox(" Segmento", calculo.SEGMENTOS)
    alunos = c_alu.number_input(" Alunos", min_value=0,
                                value=int(default_alunos), step=1)
    if default_alunos:
        st.caption(f"Valor da última contagem: **{default_alunos}** (editável acima).")

    pratos_auto = calculo.pratos_do_dia(CARDAPIO_JSON, data_dia)
    opcoes = list(dict.fromkeys(pratos_auto + sorted(r["nome"] for r in banco.values())))
    pratos = st.multiselect(
        "Pratos do dia (automático pelo cardápio, editável)",
        options=opcoes, default=pratos_auto)

    if not pratos:
        st.warning("Selecione ao menos um prato.")
        return

    df = calculo.calcular_dia(alunos, pratos, segmento, banco)
    agua_total = df["Água (L)"].sum()
    kg_total = df["kg a produzir"].sum()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Alunos", f"{alunos}")
    m2.metric("Pratos", f"{len(pratos)}")
    m3.metric("Agua total", f"{agua_total:.2f} L")
    m4.metric("Gasto do dia", f"{kg_total:.2f} kg")

    st.dataframe(df, width="stretch", hide_index=True)

    if (df["Avisos"] == "sem ficha técnica").any():
        st.warning("Alguns pratos não têm ficha técnica no receitas.json. "
                   "Ajuste a seleção ou gere novamente as receitas.")

    # Exportação
    st.divider()
    col_x, col_y = st.columns(2)
    fname = f"producao_{data_dia.strftime('%Y-%m-%d')}"
    col_x.download_button("Baixar CSV", df.to_csv(index=False, sep=";", encoding="utf-8-sig"),
                           file_name=f"{fname}.csv", mime="text/csv", width="stretch")
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="producao")
    col_y.download_button("Baixar Excel", buf.getvalue(),
                          file_name=f"{fname}.xlsx", width="stretch",
                          mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ═══════════════════════════════════════════════════════════════════
#  APP
# ═══════════════════════════════════════════════════════════════════

# ─── CARREGAMENTO DO CACHE DO DISCO (síncrono, antes de tudo) ───
def _load_cache_from_disk() -> None:
    """
    Lê os arquivos JSON do disco (arquivos/receitas.json, arquivos/cardapio.json)
    e popula session_state ANTES de qualquer renderização.
    Isso garante que o cache esteja disponível IMEDIATAMENTE no primeiro load (F5),
    sem depender de st.javascript (assíncrono) nem localStorage.
    """
    # Flag para rodar só uma vez por sessão
    if st.session_state.get("_disk_cache_loaded", False):
        return

    import json
    from pathlib import Path

    ARQUIVOS = Path(__file__).resolve().parent / "arquivos"

    # Receitas
    receitas_path = ARQUIVOS / "receitas.json"
    if receitas_path.exists():
        try:
            with open(receitas_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            st.session_state["_ls_tcc_receitas_json"] = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            # Hash simples baseado no tamanho + mtime do arquivo
            import hashlib
            stat = receitas_path.stat()
            hash_str = hashlib.md5(f"{stat.st_size}{stat.st_mtime}".encode()).hexdigest()
            st.session_state["_ls_tcc_receitas_hash"] = hash_str
        except Exception:
            pass

    # Cardápio
    cardapio_path = ARQUIVOS / "cardapio.json"
    if cardapio_path.exists():
        try:
            with open(cardapio_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            st.session_state["_ls_tcc_cardapio_json"] = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            import hashlib
            stat = cardapio_path.stat()
            hash_str = hashlib.md5(f"{stat.st_size}{stat.st_mtime}".encode()).hexdigest()
            st.session_state["_ls_tcc_cardapio_hash"] = hash_str
        except Exception:
            pass

    st.session_state["_disk_cache_loaded"] = True

# Executa ANTES de set_page_config
_load_cache_from_disk()

st.set_page_config(page_title="TCC — Refeitório", page_icon="", layout="wide")

if "pagina" not in st.session_state:
    st.session_state["pagina"] = "Contagem"

with st.sidebar:
    st.header(" Refeitório — TCC")
    pagina = st.radio("Navegação", ["Contagem", "Resultado"],
                      index=0 if st.session_state["pagina"] == "Contagem" else 1,
                      key="nav")
    st.session_state["pagina"] = pagina

    # ─── SIDEBAR: Dados disponíveis (só na tela Resultado) ───
    if pagina == "Resultado":
        st.divider()
        st.markdown("###  Dados disponíveis")
        
        # Lê direto do session_state (populado por _sync_localstorage)
        def _get_ls(key: str, default=None):
            return st.session_state.get(f"_ls_{key}", default)

        # Receitas
        receitas_json = _get_ls("tcc_receitas_json")
        receitas_hash = _get_ls("tcc_receitas_hash")
        try:
            n_receitas = len(json.loads(receitas_json)) if receitas_json else 0
        except Exception:
            n_receitas = 0
        receitas_ok = bool(receitas_json and receitas_hash)

        # Cardápio
        cardapio_json = _get_ls("tcc_cardapio_json")
        cardapio_hash = _get_ls("tcc_cardapio_hash")
        try:
            n_cardapio = len(json.loads(cardapio_json)) if cardapio_json else 0
        except Exception:
            n_cardapio = 0
        cardapio_ok = bool(cardapio_json and cardapio_hash)

        # Mês do cardápio (extrai do primeiro item do JSON)
        mes_nome = ""
        if cardapio_json:
            try:
                data = json.loads(cardapio_json)
                if data and "data" in data[0]:
                    mes_nome = data[0]["data"].split("/")[1] if "/" in data[0]["data"] else ""
            except Exception:
                pass

        # Status
        if receitas_ok:
            st.success(f"✔ **{len(json.loads(receitas_json))} receitas** (cache válido)")
        else:
            st.warning("⚠ Receitas **não extraídas** ou PDF alterado")

        if cardapio_ok:
            st.success(f"✔ **{len(json.loads(cardapio_json))} dias — {mes_nome}** (cache válido)")
        else:
            st.warning(f"⚠ Cardápio **não extraído** para **{mes_nome}** ou PDF alterado")

        if not receitas_ok or not cardapio_ok:
            st.info("Use os botões na tela para extrair o que falta.")

if pagina == "Contagem":
    tela_contagem()
else:
    tela_resultado()
