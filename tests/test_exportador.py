import json
from automate.exportador import exportar_para_automate
from sei.modelos import DocumentoSEI, ProcessoSEI


def test_exportacao(tmp_path):
    processo = ProcessoSEI(
        numero="SEI-040009/000001/2026",
        tipo="Teste",
        documentos=[DocumentoSEI(nome="Ofício (1)", texto="Conteúdo", origem_texto="sei_html")],
    )
    caminho = exportar_para_automate(processo, tmp_path)
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    assert caminho.name == "ENTRADA_SEI-040009_000001_2026.json"
    assert dados["processo"]["numero"] == processo.numero
    assert dados["documentos"][0]["texto"] == "Conteúdo"
    assert dados["status"] == "aguardando_analise"
