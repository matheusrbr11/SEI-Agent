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
    controle.registrar_evento("SEI-1/1/1", "selecionado", "ok")
    controle.finalizar_execucao(0)
    controle.iniciar_execucao("marcador")  # esta não terminou (o programa caiu)

    texto = relatorio.montar_relatorio(controle, 3, horas=2, agora=AGORA)
    assert "exportado: 1" in texto and "analisado: 1" in texto and "erro_coleta: 1" in texto
    assert "SEI-1/1/1  exportado em 2026-10-27 08:00:00 (3.0 h)" in texto
    assert "SEI-3/3/3  erro_coleta, 3 falhas: iframe indisponível" in texto
    assert "selecionados 1, exportados 0, falhas 0, análises 0, saída 0" in texto
    assert "sem fim registrado (interrompida?)" in texto


def test_historico_do_processo(controle):
    controle.iniciar_execucao("processo")
    controle.registrar_evento("SEI-1/1/1", "coleta", "ok", "2 documento(s)")
    controle.registrar_evento("SEI-1/1/1", "entrega", "erro", "OneDrive fechado")
    texto = relatorio.montar_historico(controle, "SEI-1/1/1")
    assert "HISTÓRICO DE SEI-1/1/1" in texto
    assert "exec #1  coleta  ok  2 documento(s)" in texto and "entrega  erro  OneDrive fechado" in texto
    assert "nenhum evento registrado" in relatorio.montar_historico(controle, "SEI-9/9/9")


def test_linha_de_comando(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "CAMINHO_BANCO", tmp_path / "nao_existe.db")
    assert relatorio.main([]) == 2
    assert "Banco não encontrado" in capsys.readouterr().out

    caminho = tmp_path / "agente.db"
    monkeypatch.setattr(config, "CAMINHO_BANCO", caminho)
    banco = ControleProcessos(caminho)
    banco.salvar("SEI-1/1/1", "exportado")
    banco.registrar_evento("SEI-1/1/1", "coleta", "ok")
    banco.fechar()
    assert relatorio.main([]) == 0
    assert "PROCESSOS POR STATUS" in capsys.readouterr().out
    assert relatorio.main(["--processo", "SEI-1/1/1"]) == 0
    assert "HISTÓRICO DE SEI-1/1/1" in capsys.readouterr().out
