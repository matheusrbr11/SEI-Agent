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
        from banco.controle import VERSAO_DO_ESQUEMA

        assert controle.conexao.execute("PRAGMA user_version").fetchone()[0] == VERSAO_DO_ESQUEMA
    finally:
        controle.fechar()
    ControleProcessos(caminho).fechar()  # abrir de novo um banco já migrado não falha nem duplica colunas


def _historico_antigo(caminho, versao, linhas):
    """Um banco com o historico de uma versão anterior, para testar a migração."""
    controle = ControleProcessos(caminho)
    controle.iniciar_execucao("marcador")
    controle.finalizar_execucao(0)
    controle.conexao.execute("DROP TABLE historico")
    if versao == 1:  # um registro por acontecimento
        controle.conexao.execute(
            "CREATE TABLE historico (id INTEGER PRIMARY KEY AUTOINCREMENT, execucao_id INTEGER, numero TEXT NOT NULL,"
            " etapa TEXT NOT NULL, resultado TEXT NOT NULL, detalhe TEXT, em TEXT NOT NULL)"
        )
        controle.conexao.executemany(
            "INSERT INTO historico(execucao_id,numero,etapa,resultado,em) VALUES(?,?,?,?,?)", linhas
        )
    else:  # uma linha por análise, com os problemas num texto só
        controle.conexao.execute(
            "CREATE TABLE historico (id INTEGER PRIMARY KEY AUTOINCREMENT, execucao_id INTEGER, numero TEXT,"
            " arquivo TEXT NOT NULL, resultado TEXT NOT NULL, problemas TEXT, em TEXT NOT NULL)"
        )
        controle.conexao.executemany(
            "INSERT INTO historico(execucao_id,numero,arquivo,resultado,problemas,em) VALUES(?,?,?,?,?,?)", linhas
        )
    controle.conexao.execute(f"PRAGMA user_version = {versao}")
    controle.conexao.commit()
    controle.fechar()


def test_historico_da_versao_1_e_descartado_e_as_execucoes_ficam(tmp_path):
    caminho = tmp_path / "v1.db"
    _historico_antigo(caminho, 1, [(1, "P1", "coleta", "ok", "2026-10-27T09:00:00")])
    controle = ControleProcessos(caminho)
    try:
        assert {c[1] for c in controle.conexao.execute("PRAGMA table_info(historico)")} >= {"analise", "tipo", "mensagem"}
        assert controle.analises_recentes() == [] and len(controle.execucoes_recentes()) == 1
    finally:
        controle.fechar()


def test_historico_da_versao_2_vira_uma_linha_por_problema(tmp_path):
    caminho = tmp_path / "v2.db"
    _historico_antigo(caminho, 2, [
        (1, "P1", "A.md", "erro", "ERRO: Prazo sem data\nAVISO: manifestações: duas", "2026-10-27T09:00:00"),
        (1, "P2", "B.md", "ok", None, "2026-10-27T09:05:00"),
    ])
    controle = ControleProcessos(caminho)
    try:
        assert [linha[2:] for linha in controle.historico_do_processo("P1")] == [
            (1, "A.md", "erro", "Prazo sem data"), (1, "A.md", "aviso", "manifestações: duas"),
        ]
        assert [linha[3:] for linha in controle.historico_do_processo("P2")] == [("B.md", "ok", None)]
        assert controle.conexao.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        controle.fechar()
    ControleProcessos(caminho).fechar()  # abrir de novo não duplica as linhas
    controle = ControleProcessos(caminho)
    assert len(controle.analises_recentes()) == 3
    controle.fechar()


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


# --- historico e execuções

def test_historico_tem_uma_linha_por_erro_ou_aviso(controle):
    controle.iniciar_execucao("marcador")
    problemas = ["ERRO: Solicitante Origem deveria ser só SEFAZ/SUPCONFI", "AVISO: prazo próximo", "ERRO: o Prazo precisa da data"]
    assert controle.registrar_no_historico("P1", "SAIDA_P1.md", problemas) == "erro"
    assert controle.registrar_no_historico("P1", "SAIDA_P1.md", ["AVISO: prazo próximo"]) == "aviso"
    assert controle.registrar_no_historico("P1", "SAIDA_P1.md", []) == "ok"
    linhas = controle.historico_do_processo("P1")
    assert [(analise, execucao, arquivo, tipo, mensagem) for analise, _, execucao, arquivo, tipo, mensagem in linhas] == [
        (1, 1, "SAIDA_P1.md", "erro", "Solicitante Origem deveria ser só SEFAZ/SUPCONFI"),
        (1, 1, "SAIDA_P1.md", "aviso", "prazo próximo"),
        (1, 1, "SAIDA_P1.md", "erro", "o Prazo precisa da data"),
        (2, 1, "SAIDA_P1.md", "aviso", "prazo próximo"),
        (3, 1, "SAIDA_P1.md", "ok", None),
    ]


def test_analise_sem_numero_e_registrada_assim_mesmo(controle):
    controle.registrar_no_historico(None, "SAIDA_X.md", ["ERRO: processo não identificado"])
    assert controle.analises_recentes()[0][3:] == (None, "SAIDA_X.md", "erro", "processo não identificado")


def test_analises_recentes_limita_por_analise_e_vem_da_mais_nova(controle):
    for numero in ("P1", "P2", "P3"):
        controle.registrar_no_historico(numero, f"{numero}.md", ["ERRO: a", "ERRO: b"])
    assert [(linha[0], linha[3]) for linha in controle.analises_recentes(2)] == [(3, "P3"), (3, "P3"), (2, "P2"), (2, "P2")]


def test_total_invalido_e_recusado(controle):
    with pytest.raises(ValueError, match="Total"):
        controle.contar("P1", "qualquer")


def test_finalizar_sem_execucao_aberta_nao_faz_nada(controle):
    controle.finalizar_execucao(0)


def test_execucao_soma_os_totais_e_cada_processo_conta_uma_vez(controle):
    primeira = controle.iniciar_execucao("marcador", "processo=- reanalisar=False")
    for numero in ("P1", "P2", "P3"):
        controle.contar(numero, "selecionados")
    controle.contar("P1", "exportados")
    controle.contar("P2", "falhas")
    controle.contar("P3", "falhas")
    controle.contar("P3", "falhas")  # a coleta e a entrega do mesmo processo não contam duas vezes
    controle.registrar_no_historico("P1", "P1.md", ["AVISO: x", "AVISO: y"])  # duas linhas, uma análise
    controle.finalizar_execucao(1)

    segunda = controle.iniciar_execucao("saidas")  # os totais desta não somam com os da primeira
    controle.registrar_no_historico("P9", "P9.md", [])
    controle.finalizar_execucao(0)

    (id2, *_, analises2, _), (id1, inicio, fim, modo, selecionados, exportados, falhas, analises, codigo) = controle.execucoes_recentes(2)
    assert (id1, id2) == (primeira, segunda) and modo == "marcador" and fim and inicio <= fim
    assert (selecionados, exportados, falhas, analises, codigo) == (3, 1, 2, 1, 1) and analises2 == 1


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
