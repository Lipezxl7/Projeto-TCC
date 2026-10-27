from modulos import receita


def test_parse_number():
    assert receita.parse_number("1.200,5") == 1200.5
    assert receita.parse_number("12,5") == 12.5
    assert receita.parse_number("12000") == 12000.0
    assert receita.parse_number(" 12 kg ") == 12.0
    assert receita.parse_number(None) is None
    assert receita.parse_number("sem numero") is None


def test_parse_footer_row_rendimento():
    footer = {}
    receita.parse_footer_row("Rendimento: 12 kg", footer)
    assert footer["rendimento"] == "12 kg"


def test_parse_footer_row_porcoes_em_alunos():
    footer = {}
    receita.parse_footer_row(
        "Rendimento: 300 alunos Peso da porção: 120 g cozido", footer)
    assert footer["porcao_fund"] == "120 g cozido"

    receita.parse_footer_row(
        "EJA: Rendimento: 200 alunos Peso da porção (g): 150 g", footer)
    assert footer["porcao_em_eja"] == "150 g"


def test_parse_footer_row_tempo_preparo():
    footer = {}
    receita.parse_footer_row("Tempo de preparo: 1h e 30min", footer)
    assert footer["tempo_preparo"] == "1h e 30min"


def test_parse_footer_row_medida_caseira():
    footer = {}
    receita.parse_footer_row(
        "Medida caseira Fund: 2 conchas Medida caseira EM: 1 concha", footer)
    assert footer["medida_caseira_fund"] == "2 conchas"
    assert footer["medida_caseira_em_eja"] == "1 concha"
