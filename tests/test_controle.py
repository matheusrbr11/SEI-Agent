import pytest
from banco.controle import ControleProcessos


@pytest.fixture
def controle(tmp_path):
    c = ControleProcessos(tmp_path / "teste.db")
    yield c
    c.fechar()


def test_banco_novo_esta_vazio(controle):
    assert controle.vazio()


def test_salvar_e_conhecido(controle):
    controle.salvar("P1", "exportado", arquivo_entrada="a.json")
    assert not controle.vazio()
    assert controle.conhecido("P1")
    assert not controle.conhecido("P2")


def test_erros_nao_sao_conhecidos(controle):
    controle.salvar("P1", "erro_coleta", erro="falha")
    controle.salvar("P2", "erro_ia", erro="falha")
    assert not controle.conhecido("P1")
    assert not controle.conhecido("P2")


def test_status_invalido(controle):
    with pytest.raises(ValueError):
        controle.salvar("P1", "qualquer")


def test_upsert_preserva_arquivos_e_limpa_erro(controle):
    controle.salvar("P1", "exportado", arquivo_entrada="a.json")
    controle.salvar("P1", "analisado", arquivo_saida="a.md")
    linha = controle.conexao.execute(
        "SELECT status, arquivo_entrada, arquivo_saida, erro FROM processos WHERE numero='P1'"
    ).fetchone()
    assert linha == ("analisado", "a.json", "a.md", None)
    assert controle.conexao.execute("SELECT COUNT(*) FROM processos").fetchone()[0] == 1


def test_registrar_baseline(controle):
    controle.registrar_baseline(["P1", "P2", "P3"])
    assert all(controle.conhecido(n) for n in ("P1", "P2", "P3"))


def _linha(controle, numero):
    return controle.conexao.execute(
        "SELECT status, arquivo_entrada, arquivo_saida, erro FROM processos WHERE numero=?", (numero,)
    ).fetchone()


def test_registrar_analise_atualiza_a_linha_e_preserva_o_json_de_entrada(controle):
    controle.salvar("P1", "exportado", arquivo_entrada="a.json")
    assert controle.registrar_analise("P1", "saida/a.md") is True
    assert _linha(controle, "P1") == ("analisado", "a.json", "saida/a.md", None)
    assert controle.conhecido("P1")


def test_registrar_analise_guarda_o_resumo_da_validacao_e_depois_limpa(controle):
    controle.salvar("P1", "exportado", arquivo_entrada="a.json")
    controle.registrar_analise("P1", "saida/a.md", "Validação: 2 ERRO(s)")
    assert _linha(controle, "P1")[3] == "Validação: 2 ERRO(s)"
    controle.registrar_analise("P1", "saida/a.md")
    assert _linha(controle, "P1")[3] is None


def test_registrar_analise_de_processo_desconhecido_nao_cria_linha(controle):
    assert controle.registrar_analise("outro", "saida/a.md") is False
    assert controle.vazio()


# --- esquema e migração

def _colunas(controle):
    return {linha[1] for linha in controle.conexao.execute("PRAGMA table_info(processos)")}


def test_banco_novo_nasce_na_versao_atual_com_as_tres_tabelas(controle):
    from banco.controle import VERSAO_DO_ESQUEMA

    assert controle.conexao.execute("PRAGMA user_version").fetchone()[0] == VERSAO_DO_ESQUEMA
    tabelas = {linha[0] for linha in controle.conexao.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"processos", "execucoes", "historico"} <= tabelas
    assert {"falhas_seguidas", "exportado_em", "analisado_em", "teams_enviado", "validacao_erros",
            "validacao_avisos"} <= _colunas(controle)


def test_banco_antigo_e_migrado_sem_perder_as_linhas(tmp_path):
    import sqlite3

    caminho = tmp_path / "antigo.db"
    antigo = sqlite3.connect(str(caminho))
    antigo.execute(
        """CREATE TABLE processos (numero TEXT PRIMARY KEY, status TEXT NOT NULL, arquivo_entrada TEXT,
                                   arquivo_saida TEXT, erro TEXT, atualizado_em TEXT NOT NULL)"""
    )
    antigo.execute("INSERT INTO processos VALUES('P1','exportado','a.json',NULL,NULL,'2026-10-27T11:48:05')")
    antigo.execute("INSERT INTO processos VALUES('P2','baseline',NULL,NULL,NULL,'2026-10-27T11:00:00')")
    antigo.commit()
    antigo.close()

    controle = ControleProcessos(caminho)
    try:
        assert controle.linha("P1")["status"] == "exportado" and controle.linha("P1")["arquivo_entrada"] == "a.json"
        assert controle.linha("P1")["falhas_seguidas"] == 0 and controle.linha("P1")["analisado_em"] is None
        assert controle.conhecido("P1") and controle.conhecido("P2")
        assert controle.conexao.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        controle.fechar()
    ControleProcessos(caminho).fechar()  # abrir de novo um banco já migrado não falha nem duplica colunas


def test_linha_de_processo_desconhecido_e_none(controle):
    assert controle.linha("P9") is None


# --- falhas seguidas e desistência

def test_falhas_seguidas_somam_nos_erros_e_zeram_no_sucesso(controle):
    controle.salvar("P1", "erro_coleta", erro="a")
    controle.salvar("P1", "erro_envio", arquivo_entrada="a.json", erro="b")
    assert controle.linha("P1")["falhas_seguidas"] == 2
    controle.salvar("P1", "exportado", arquivo_entrada="a.json")
    assert controle.linha("P1")["falhas_seguidas"] == 0


def test_desistiu_so_em_erro_e_ao_atingir_o_teto(controle):
    for _ in range(2):
        controle.salvar("P1", "erro_coleta", erro="x")
    assert not controle.desistiu("P1", 3)
    controle.salvar("P1", "erro_coleta", erro="x")
    assert controle.desistiu("P1", 3)
    controle.salvar("P1", "exportado")
    assert not controle.desistiu("P1", 3)
    assert not controle.desistiu("desconhecido", 3)


# --- datas e ciclo

def test_exportado_grava_a_data_e_novo_exportado_limpa_a_analise_anterior(controle):
    controle.salvar("P1", "exportado", arquivo_entrada="a.json")
    primeira = controle.linha("P1")["exportado_em"]
    assert primeira
    controle.registrar_analise("P1", "saida/a.md", "Validação: 1 ERRO(s)", validacao_erros=1, validacao_avisos=2,
                               teams_enviado=True)
    analisada = controle.linha("P1")
    assert (analisada["analisado_em"], analisada["validacao_erros"], analisada["validacao_avisos"],
            analisada["teams_enviado"]) == (analisada["atualizado_em"], 1, 2, 1)

    controle.salvar("P1", "exportado", arquivo_entrada="a.json")  # reexportado: começa um ciclo novo
    nova = controle.linha("P1")
    assert nova["arquivo_saida"] is None and nova["analisado_em"] is None and nova["teams_enviado"] is None
    assert nova["validacao_erros"] is None and nova["validacao_avisos"] is None and nova["erro"] is None


def test_teams_enviado_distingue_falha_de_nao_tentado(controle):
    controle.salvar("P1", "exportado")
    controle.registrar_analise("P1", "a.md")
    assert controle.linha("P1")["teams_enviado"] is None
    controle.registrar_analise("P1", "a.md", teams_enviado=False)
    assert controle.linha("P1")["teams_enviado"] == 0


# --- diário

def test_evento_sem_execucao_iniciada_fica_sem_execucao(controle):
    controle.registrar_evento("P1", "coleta", "ok", "1 documento(s)")
    assert controle.historico_do_processo("P1")[0][1:] == (None, "coleta", "ok", "1 documento(s)")
    controle.finalizar_execucao(0)  # sem execução aberta: não faz nada nem falha


def test_evento_invalido_e_recusado(controle):
    with pytest.raises(ValueError, match="Etapa"):
        controle.registrar_evento("P1", "qualquer", "ok")
    with pytest.raises(ValueError, match="Resultado"):
        controle.registrar_evento("P1", "coleta", "talvez")


def test_execucao_soma_os_totais_a_partir_do_historico(controle):
    primeira = controle.iniciar_execucao("marcador", "processo=- reanalisar=False")
    for numero in ("P1", "P2", "P3"):
        controle.registrar_evento(numero, "selecionado", "ok")
    controle.registrar_evento("P1", "coleta", "ok")
    controle.registrar_evento("P1", "entrega", "ok")
    controle.registrar_evento("P2", "coleta", "erro", "Falha na coleta")
    controle.registrar_evento("P3", "coleta", "ok")
    controle.registrar_evento("P3", "entrega", "erro", "OneDrive fechado")
    controle.registrar_evento("P1", "analise", "aviso")
    controle.finalizar_execucao(1)

    segunda = controle.iniciar_execucao("saidas")  # os eventos desta não entram nos totais da primeira
    controle.registrar_evento("P9", "analise", "ok")
    controle.finalizar_execucao(0)

    (id2, *_), (id1, inicio, fim, modo, selecionados, exportados, falhas, analises, codigo) = controle.execucoes_recentes(2)
    assert (id1, id2) == (primeira, segunda) and modo == "marcador" and fim and inicio <= fim
    assert (selecionados, exportados, falhas, analises, codigo) == (3, 1, 2, 1, 1)


# --- consultas

def test_exportados_sem_analise_e_desistiram(controle):
    from datetime import datetime, timedelta

    controle.salvar("P1", "exportado")
    controle.salvar("P2", "exportado")
    controle.registrar_analise("P2", "a.md")
    controle.conexao.execute("UPDATE processos SET exportado_em='2026-10-27T08:00:00' WHERE numero='P1'")
    controle.conexao.commit()
    agora = datetime(2026, 10, 27, 11, 0, 0)
    assert controle.exportados_sem_analise(2, agora) == [("P1", "2026-10-27T08:00:00")]
    assert controle.exportados_sem_analise(4, agora) == []

    for _ in range(3):
        controle.salvar("P3", "erro_coleta", erro="iframe indisponível")
    controle.salvar("P4", "erro_coleta", erro="x")
    assert controle.desistiram(3) == [("P3", "erro_coleta", 3, "iframe indisponível")]
    assert dict(controle.contagem_por_status()) == {"exportado": 1, "analisado": 1, "erro_coleta": 2}
