import json
from datetime import date

from modulos import calculo


# ── parsing de quantidades ─────────────────────────────────────────

def test_parse_gramas_basico():
    assert calculo.parse_gramas("12 kg") == 12000.0
    assert calculo.parse_gramas("12kg") == 12000.0
    assert calculo.parse_gramas("12000 g") == 12000.0
    assert calculo.parse_gramas("12 litros") == 12000.0
    assert calculo.parse_gramas("1,5 kg") == 1500.0
    assert calculo.parse_gramas(1500) == 1500.0  # já numérico
    assert calculo.parse_gramas(None) == 0.0
    assert calculo.parse_gramas("alunos") == 0.0


def test_parse_gramas_prefere_parentese():
    # '50g (120g cozido)' -> 120 (o parêntese ganha)
    assert calculo.parse_gramas("50g (120g cozido)") == 120.0


def test_parse_gramas_ponto_decimal_vs_milhar():
    # ponto seguido de exatamente 3 dígitos = milhar
    assert calculo.parse_gramas("1.500 g") == 1500.0
    assert calculo.parse_gramas("1.234.567 g") == 1234567.0
    # ponto com menos de 3 dígitos = decimal (regressão do bug '1.5 kg' -> 15 g)
    assert calculo.parse_gramas("1.5 kg") == 1500.0
    assert calculo.parse_gramas("0,5 l") == 500.0


# ── normalização de datas ──────────────────────────────────────────

def test_normalizar_data():
    assert calculo.normalizar_data(date(2026, 5, 12)) == "12/05"
    assert calculo.normalizar_data("2026-05-12") == "12/05"
    assert calculo.normalizar_data("12-05") == "12/05"
    assert calculo.normalizar_data("12/05") == "12/05"
    assert calculo.normalizar_data("12/mai") == "12/05"
    assert calculo.normalizar_data("12/jun.") == "12/06"
    assert calculo.normalizar_data("lixo") == ""


# ── busca de receita ──────────────────────────────────────────────

BANCO = {
    "arrozdoce": {
        "nome": "Arroz Doce",
        "rendimento_g": 10000.0,
        "porcao_fund_g": 100.0,
        "porcao_em_g": 120.0,
        "ingredientes": [],
    }
}


def test_buscar_receita_slug_exato():
    assert calculo.buscar_receita(BANCO, "ARROZ DOCE")["nome"] == "Arroz Doce"


def test_buscar_receita_sobreposicao_de_tokens():
    # 'com' é stopword; interseção 2/3 >= 50%
    assert calculo.buscar_receita(BANCO, "Arroz Doce com Canela") is not None
    assert calculo.buscar_receita(BANCO, "Feijoada Completa") is None


# ── cálculo do dia ────────────────────────────────────────────────

def test_calcular_dia_agua_acumula():
    # regressão: dois ingredientes 'água' devem SOMAR (antes só o último contava)
    banco = {
        "sopa": {
            "nome": "Sopa",
            "rendimento_g": 10000.0,
            "porcao_fund_g": 100.0,
            "porcao_em_g": 120.0,
            "ingredientes": [
                {"nome": "ÁGUA", "qtd": 5000.0},
                {"nome": "ÁGUA PARA COZIMENTO", "qtd": 3000.0},
                {"nome": "BATATA", "qtd": 2000.0},
            ],
        }
    }
    df = calculo.calcular_dia(10, ["Sopa"], "Fundamental", banco)
    row = df.iloc[0]
    # fator = (100*10)/10000 = 0.1 -> água = (5000+3000)*0.1/1000 = 0.8 L
    assert row["Água (L)"] == 0.8
    assert row["kg a produzir"] == 1.0  # 100*10/1000
    assert row["Avisos"] == ""


def test_calcular_dia_sem_ficha_tecnica():
    df = calculo.calcular_dia(10, ["Prato Fantasma"], "Fundamental", {})
    assert df.iloc[0]["Avisos"] == "sem ficha técnica"
    assert df.iloc[0]["Água (L)"] == 0.0


def test_calcular_dia_fator_zero_sem_rendimento():
    banco = {
        "x": {"nome": "X", "rendimento_g": 0.0, "porcao_fund_g": 100.0,
              "porcao_em_g": 100.0,
              "ingredientes": [{"nome": "ÁGUA", "qtd": 5000.0}]},
    }
    df = calculo.calcular_dia(10, ["X"], "Fundamental", banco)
    assert df.iloc[0]["Fator"] == 0.0
    assert df.iloc[0]["Água (L)"] == 0.0


# ── carregamento do receitas.json ─────────────────────────────────

def test_carregar_receitas(tmp_path):
    caminho = tmp_path / "receitas.json"
    caminho.write_text(json.dumps([{
        "nome": "Arroz Doce",
        "rendimento": "12 kg",
        "porcao_fund": "150 g",
        "porcao_em_eja": "180 g",
        "ingredientes": [
            {"ingrediente": "ARROZ", "quantidade_g_ml": 1000},
            # fallbacks: chave 'nome' + 'peso_base_g'
            {"nome": "ÁGUA", "peso_base_g": "2,5 litros"},
        ],
    }]), encoding="utf-8")

    banco = calculo.carregar_receitas(str(caminho))
    rec = banco["arrozdoce"]
    assert rec["nome"] == "Arroz Doce"
    assert rec["rendimento_g"] == 12000.0
    assert rec["porcao_fund_g"] == 150.0
    assert rec["porcao_em_g"] == 180.0
    assert rec["ingredientes"][0]["qtd"] == 1000.0
    assert rec["ingredientes"][1]["qtd"] == 2500.0  # '2,5 litros' -> 2500


def test_carregar_receitas_json_invalido(tmp_path):
    caminho = tmp_path / "receitas.json"
    caminho.write_text("não é json", encoding="utf-8")
    try:
        calculo.carregar_receitas(str(caminho))
        assert False, "deveria lançar exceção"
    except json.JSONDecodeError:
        pass


# ── pratos do dia ─────────────────────────────────────────────────

def test_pratos_do_dia(tmp_path):
    caminho = tmp_path / "cardapio.json"
    caminho.write_text(json.dumps([
        {"data": "12/jun", "pratos": ["ARROZ DOCE", "FEIJÃO", "REFEIÇÃO X"]},
        {"data": "13/jun", "pratos": ["MACARRÃO"]},
    ]), encoding="utf-8")

    # por objeto date e por 'dd/mm'
    assert calculo.pratos_do_dia(caminho, date(2026, 6, 12)) == ["ARROZ DOCE", "FEIJÃO"]
    assert calculo.pratos_do_dia(caminho, "12/06") == ["ARROZ DOCE", "FEIJÃO"]
    # pela própria chave do cardápio ('12/jun')
    assert calculo.pratos_do_dia(caminho, "12/jun") == ["ARROZ DOCE", "FEIJÃO"]
    assert calculo.pratos_do_dia(caminho, "01/01") == []
    assert calculo.pratos_do_dia(tmp_path / "inexistente.json", "12/06") == []
