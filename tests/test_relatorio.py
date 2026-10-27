from datetime import datetime

import pytest

import config
from banco import relatorio
from banco.controle import ControleProcessos

AGORA = datetime(2026, 10, 27, 11, 0, 0)


@pytest.fixture
def controle(tmp_path):
    c = ControleProcessos(tmp_path / "relatorio.db")
    yield c
    c.fechar()


def test_relatorio_de_banco_vazio(controle):
    texto = relatorio.montar_relatorio(controle, 3, agora=AGORA)
    assert "(banco vazio)" in texto and "nenhuma" in texto


def test_relatorio_mostra_status_pendentes_desistencias_e_execucoes(controle):
    controle.salvar("SEI-1/1/1", "exportado")
    controle.conexao.execute("UPDATE processos SET exportado_em='2026-10-27T08:00:00' WHERE numero='SEI-1/1/1'")
    controle.conexao.commit()
    controle.salvar("SEI-2/2/2", "analisado")
    for _ in range(3):
        controle.salvar("SEI-3/3/3", "erro_coleta", erro="iframe indisponível")
    controle.iniciar_execucao("marcador")
    controle.contar("SEI-1/1/1", "selecionados")
    controle.registrar_no_historico("SEI-2/2/2", "SAIDA_2.md", ["ERRO: Prazo sem data", "AVISO: x"])
    controle.finalizar_execucao(0)
    controle.iniciar_execucao("marcador")  # esta não terminou (o programa caiu)

    texto = relatorio.montar_relatorio(controle, 3, horas=2, agora=AGORA)
    assert "exportado: 1" in texto and "analisado: 1" in texto and "erro_coleta: 1" in texto
    assert "SEI-1/1/1  exportado em 2026-10-27 08:00:00 (3.0 h)" in texto
    assert "SEI-3/3/3  erro_coleta, 3 falhas: iframe indisponível" in texto
    assert "selecionados 1, exportados 0, falhas 0, análises 1, saída 0" in texto
    assert "SEI-2/2/2  erro  (SAIDA_2.md, exec #1)" in texto
    assert "      ERRO: Prazo sem data\n      AVISO: x" in texto
    assert "sem fim registrado (interrompida?)" in texto


def test_analises_do_processo_com_os_erros(controle):
    controle.iniciar_execucao("processo")
    controle.registrar_no_historico("SEI-1/1/1", "SAIDA_1.md", ["ERRO: Prazo sem data", "AVISO: manifestações"])
    controle.registrar_no_historico("SEI-1/1/1", "SAIDA_1.md", [])
    texto = relatorio.montar_historico(controle, "SEI-1/1/1")
    assert "ANÁLISES DE SEI-1/1/1" in texto
    assert "erro  (SAIDA_1.md, exec #1)\n      ERRO: Prazo sem data\n      AVISO: manifestações\n" in texto
    assert "ok  (SAIDA_1.md, exec #1)" in texto
    assert "nenhuma análise registrada" in relatorio.montar_historico(controle, "SEI-9/9/9")


def test_relatorio_sem_analises_diz_nenhuma(controle):
    assert "ÚLTIMAS 10 ANÁLISES\n  nenhuma" in relatorio.montar_relatorio(controle, 3, agora=AGORA)


def test_linha_de_comando(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "CAMINHO_BANCO", tmp_path / "nao_existe.db")
    assert relatorio.main([]) == 2
    assert "Banco não encontrado" in capsys.readouterr().out

    caminho = tmp_path / "agente.db"
    monkeypatch.setattr(config, "CAMINHO_BANCO", caminho)
    banco = ControleProcessos(caminho)
    banco.salvar("SEI-1/1/1", "exportado")
    banco.registrar_no_historico("SEI-1/1/1", "SAIDA_1.md", [])
    banco.fechar()
    assert relatorio.main([]) == 0
    assert "PROCESSOS POR STATUS" in capsys.readouterr().out
    assert relatorio.main(["--processo", "SEI-1/1/1"]) == 0
    assert "ANÁLISES DE SEI-1/1/1" in capsys.readouterr().out
