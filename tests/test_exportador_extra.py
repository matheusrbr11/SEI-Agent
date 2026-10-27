import json
import pytest
from automate.exportador import SCHEMA_VERSION, copiar_para_sharepoint, exportar_para_automate, preparar_para_automate
from sei.modelos import DocumentoSEI, ProcessoSEI


def _processo():
    return ProcessoSEI(
        numero="SEI-040009/000002/2026",
        tipo="Tipo",
        marcadores="AGENTE - ANALISAR",
        documentos=[
            DocumentoSEI(nome="Com texto", texto="abc", origem_texto="sei_html", unidade="SEFAZ/SUPCONC"),
            DocumentoSEI(nome="Sem texto"),
        ],
    )


def test_payload_estrutura_e_controle():
    dados = preparar_para_automate(_processo())
    assert dados["schema_version"] == SCHEMA_VERSION
    assert dados["controle"]["quantidade_documentos"] == 2
    assert dados["controle"]["documentos_sem_texto"] == ["Sem texto"]
    assert dados["controle"]["necessita_revisao_humana"] is True
    assert [d["ordem"] for d in dados["documentos"]] == [1, 2]
    assert dados["documentos"][1]["texto"] == "[SEM TEXTO EXTRAÍDO]"
    assert [d["unidade"] for d in dados["documentos"]] == ["SEFAZ/SUPCONFI", None]  # a IA só vê o nome atual
    assert dados["processo"]["marcadores"] == "AGENTE - ANALISAR"


def test_processo_sem_documentos():
    dados = preparar_para_automate(ProcessoSEI(numero="X/1"))
    assert dados["documentos"] == []
    assert dados["controle"]["quantidade_documentos"] == 0


def test_exportar_cria_pasta_sem_tmp_residual_e_sobrescreve(tmp_path):
    pasta = tmp_path / "novo" / "entrada"
    p = _processo()
    destino = exportar_para_automate(p, pasta)
    p.tipo = "Alterado"
    destino2 = exportar_para_automate(p, pasta)
    assert destino == destino2
    assert list(pasta.glob("*.tmp")) == []
    assert json.loads(destino.read_text(encoding="utf-8"))["processo"]["tipo"] == "Alterado"


def test_preserva_acentos_no_json(tmp_path):
    p = ProcessoSEI(numero="A/1", documentos=[DocumentoSEI(nome="d", texto="ação")])
    destino = exportar_para_automate(p, tmp_path)
    assert "ação" in destino.read_text(encoding="utf-8")


def test_copia_para_pasta_sharepoint(tmp_path):
    arquivo = exportar_para_automate(_processo(), tmp_path / "local")
    pasta = tmp_path / "sharepoint"
    pasta.mkdir()
    destino = copiar_para_sharepoint(arquivo, pasta)
    assert destino == pasta / arquivo.name
    assert destino.read_bytes() == arquivo.read_bytes()


def test_copia_falha_se_pasta_nao_sincronizada(tmp_path):
    arquivo = exportar_para_automate(_processo(), tmp_path / "local")
    with pytest.raises(FileNotFoundError, match="OneDrive"):
        copiar_para_sharepoint(arquivo, tmp_path / "inexistente")
