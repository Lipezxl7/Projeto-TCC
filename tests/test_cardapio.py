"""Teste de integração contra o PDF real do repositório (só pdfplumber)."""
import json
import re
from pathlib import Path

from modulos import cardapio

RAIZ = Path(__file__).resolve().parent.parent
PDF = RAIZ / "arquivos" / "cardapio.pdf"


def test_extracao_do_pdf_real(tmp_path):
    saida = tmp_path / "cardapio.json"
    dados = cardapio.executar_extracao(
        str(PDF), str(saida), mes="jun",
        salvar_json=True, salvar_csv=False)

    assert len(dados) > 0
    for dia in dados:
        assert re.fullmatch(r"\d{1,2}/jun", dia["data"], re.IGNORECASE), dia["data"]
        assert len(dia["pratos"]) > 0
        for prato in dia["pratos"]:
            assert prato == prato.upper()
            assert "REFEIÇÃO" not in prato

    # JSON gravado bate com o retorno
    no_disco = json.loads(saida.read_text(encoding="utf-8"))
    assert no_disco == dados


def test_extracao_erro_pdf_inexistente(tmp_path):
    try:
        cardapio.executar_extracao(
            str(tmp_path / "nao_existe.pdf"), mes="jun",
            salvar_json=False, salvar_csv=False)
        assert False, "deveria lançar exceção"
    except Exception:
        pass
