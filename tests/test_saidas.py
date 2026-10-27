import json
import os

import config
from automate import saidas
from automate.saidas import localizar_entrada, numero_do_processo, processar_arquivo, processar_pasta
from test_validador import _analise, _entrada

NUMERO = "SEI-040005/000729/2026"
NOME_DA_ENTRADA = "ENTRADA_SEI-040005_000729_2026.json"


def _pastas(tmp_path, entrada=None):
    pasta_entrada, saida, destino = tmp_path / "entrada", tmp_path / "saida", tmp_path / "validadas"
    for pasta in (pasta_entrada, saida):
        pasta.mkdir()
    if entrada is not None:
        (pasta_entrada / NOME_DA_ENTRADA).write_text(json.dumps(entrada), encoding="utf-8")
    return pasta_entrada, saida, destino


def _analise_com_defeitos(entrada):
    """Defeitos de formato e de nome de unidade que o Python corrige sozinho."""
    return (
        _analise(
            entrada,
            contexto="Enviado à SUPGO.",
            alertas="1. Preencher: algo (provável fonte: x)",
            despacho="À SEFAZ/SUBTES,\nEm atenção ao despacho,\n\nInformamos que damos ciência.",
        )
        .replace("### Despacho", "## Despacho")
    )


def test_numero_do_processo():
    assert numero_do_processo(f"## Processo\n{NUMERO}\n\n## Solicitante Origem\nX") == NUMERO
    assert numero_do_processo(f"## Processo\n\n  {NUMERO}  \n") == NUMERO
    assert numero_do_processo("## Processo\n## Solicitante Origem\nX") is None
    assert numero_do_processo("sem seção") is None


def test_localizar_entrada_em_varias_pastas(tmp_path):
    vazia, com_arquivo = tmp_path / "a", tmp_path / "b"
    vazia.mkdir()
    com_arquivo.mkdir()
    (com_arquivo / NOME_DA_ENTRADA).write_text("{}", encoding="utf-8")
    assert localizar_entrada(NUMERO, [None, vazia, com_arquivo]) == com_arquivo / NOME_DA_ENTRADA
    assert localizar_entrada("SEI-1/2/3", [vazia, com_arquivo]) is None


def test_corrige_valida_e_grava_sem_mexer_na_origem(tmp_path):
    entrada = _entrada()
    pasta_entrada, saida, destino = _pastas(tmp_path, entrada)
    origem = saida / "ANALISE_X.md"
    origem.write_text(_analise_com_defeitos(entrada), encoding="utf-8")
    original = origem.read_bytes()

    resultado = processar_arquivo(origem, [pasta_entrada], destino)

    assert resultado.situacao == "OK" and resultado.problemas == []
    assert resultado.numero == NUMERO
    assert resultado.correcoes == [
        "'## Despacho' virou '### Despacho' (subseção da Proposta)",
        "1 linha(s) 'Preencher:' sem marcador [PREENCHER] na análise removida(s) dos Alertas",
        "Despacho: frase partida em dois parágrafos (terminava em vírgula) foi reunida",
        "Nomes antigos de unidades trocados pelos atuais (SUPCONC, SUPGO, SUPAEF)",
    ]
    corrigido = (destino / "ANALISE_X.md").read_text(encoding="utf-8")
    assert "### Despacho" in corrigido and "SUPHOB" in corrigido and "SUPGO" not in corrigido
    assert "Preencher" not in corrigido and "Em atenção ao despacho, informamos que damos ciência." in corrigido
    relatorio = (destino / "ANALISE_X.validacao.txt").read_text(encoding="utf-8")
    assert "Situação: OK" in relatorio and "CORREÇÕES AUTOMÁTICAS" in relatorio and f"Processo: {NUMERO}" in relatorio
    assert origem.read_bytes() == original  # a pasta do OneDrive só é lida


def test_problema_de_conteudo_continua_como_erro_no_relatorio(tmp_path):
    entrada = _entrada()
    pasta_entrada, saida, destino = _pastas(tmp_path, entrada)
    origem = saida / "ANALISE_X.md"
    origem.write_text(_analise(entrada, processo="SEI-040005/000729/2026", origem="Tribunal ([SIGLA]) (via SEFAZ/SUBCINT)"), encoding="utf-8")
    resultado = processar_arquivo(origem, [pasta_entrada], destino)
    assert resultado.situacao == "ERRO"
    assert resultado.erros == ["ERRO: o Solicitante Origem tem marcador entre colchetes"]
    assert "Situação: ERRO" in (destino / "ANALISE_X.validacao.txt").read_text(encoding="utf-8")


def test_entrada_nao_encontrada_vira_erro_mas_ainda_corrige_o_formato(tmp_path):
    pasta_entrada, saida, destino = _pastas(tmp_path)
    origem = saida / "ANALISE_X.md"
    origem.write_text(_analise_com_defeitos(_entrada()), encoding="utf-8")
    resultado = processar_arquivo(origem, [pasta_entrada], destino)
    assert resultado.erros == [f"ERRO: JSON de entrada não encontrado: {NOME_DA_ENTRADA}"]
    assert "### Despacho" in (destino / "ANALISE_X.md").read_text(encoding="utf-8")


def test_analise_sem_numero_de_processo(tmp_path):
    pasta_entrada, saida, destino = _pastas(tmp_path)
    origem = saida / "sem_numero.md"
    origem.write_text("## Contexto\nSem seção de processo.\n", encoding="utf-8")
    assert processar_arquivo(origem, [pasta_entrada], destino).erros == [
        "ERRO: a seção Processo não traz o número; não foi possível achar o JSON de entrada"
    ]


def test_json_de_entrada_em_formato_antigo(tmp_path):
    entrada = _entrada()
    antigo = json.loads(json.dumps(entrada))
    del antigo["pre_calculado"]["solicitante_origem"]
    pasta_entrada, saida, destino = _pastas(tmp_path, antigo)
    origem = saida / "ANALISE_X.md"
    origem.write_text(_analise(entrada), encoding="utf-8")
    resultado = processar_arquivo(origem, [pasta_entrada], destino)
    assert resultado.erros == ["ERRO: o JSON de entrada está em formato antigo (falta 'solicitante_origem'); gere-o de novo com o agente"]


def test_aceita_arquivo_com_bom_do_windows(tmp_path):
    entrada = _entrada()
    pasta_entrada, saida, destino = _pastas(tmp_path, entrada)
    (saida / "ANALISE_X.md").write_bytes(b"\xef\xbb\xbf" + _analise(entrada).encode("utf-8"))
    assert processar_pasta(saida, [pasta_entrada], destino)[0].situacao == "OK"


def test_so_processa_o_que_e_novo_a_menos_que_peca_para_refazer(tmp_path):
    entrada = _entrada()
    pasta_entrada, saida, destino = _pastas(tmp_path, entrada)
    (saida / "A.md").write_text(_analise(entrada), encoding="utf-8")
    (saida / "~$A.md").write_text("temporário do Word", encoding="utf-8")
    (saida / "nota.txt").write_text("não é análise", encoding="utf-8")
    assert [r.arquivo for r in processar_pasta(saida, [pasta_entrada], destino)] == ["A.md"]
    assert processar_pasta(saida, [pasta_entrada], destino) == []
    assert [r.arquivo for r in processar_pasta(saida, [pasta_entrada], destino, refazer=True)] == ["A.md"]

    # só o horário mudou (o OneDrive faz isso): mesmo conteúdo, continua sem ser novo
    depois = (saida / "A.md").stat().st_mtime + 10
    os.utime(saida / "A.md", (depois, depois))
    assert processar_pasta(saida, [pasta_entrada], destino) == []

    # o conteúdo mudou, mesmo com horário antigo: é uma análise nova
    (saida / "A.md").write_text(_analise(entrada, contexto="Outro resumo."), encoding="utf-8")
    os.utime(saida / "A.md", (1_000_000_000, 1_000_000_000))
    assert [r.arquivo for r in processar_pasta(saida, [pasta_entrada], destino)] == ["A.md"]


def test_arquivo_especifico(tmp_path):
    entrada = _entrada()
    pasta_entrada, saida, destino = _pastas(tmp_path, entrada)
    for nome in ("A.md", "B.md"):
        (saida / nome).write_text(_analise(entrada), encoding="utf-8")
    assert [r.arquivo for r in processar_pasta(saida, [pasta_entrada], destino, arquivo="B.md")] == ["B.md"]
    assert processar_pasta(saida, [pasta_entrada], destino, arquivo="nao_existe.md") == []


def _configurar(monkeypatch, tmp_path, saida, pasta_entrada):
    monkeypatch.setattr(config, "SHAREPOINT_PASTA_SAIDA", saida)
    monkeypatch.setattr(config, "SHAREPOINT_PASTA_ENTRADA", None)
    monkeypatch.setattr(config, "PASTA_AUTOMATE_ENTRADA", pasta_entrada)
    monkeypatch.setattr(config, "PASTA_AUTOMATE_SAIDA", tmp_path / "validadas")


def test_linha_de_comando(tmp_path, monkeypatch, capsys):
    entrada = _entrada()
    pasta_entrada, saida, destino = _pastas(tmp_path, entrada)
    _configurar(monkeypatch, tmp_path, saida, pasta_entrada)

    assert saidas.main([]) == 0
    assert "A pasta de saída não tem nenhuma análise (.md)." in capsys.readouterr().out

    (saida / "OK.md").write_text(_analise(entrada), encoding="utf-8")
    assert saidas.main([]) == 0
    assert "[OK] OK.md" in capsys.readouterr().out

    assert saidas.main([]) == 0  # nada mudou: diz que já foi processada, em vez de parecer que não viu o arquivo
    mensagem = capsys.readouterr().out
    assert "Nenhuma análise nova: as 1 análise(s) da pasta de saída já foram processadas" in mensagem
    assert "--refazer" in mensagem
    assert saidas.main(["--refazer"]) == 0
    assert "[OK] OK.md" in capsys.readouterr().out

    (saida / "RUIM.md").write_text(_analise(entrada, processo="outro"), encoding="utf-8")
    assert saidas.main([]) == 1
    saida_do_comando = capsys.readouterr().out
    assert "[ERRO] RUIM.md" in saida_do_comando and "Resultados em:" in saida_do_comando


def test_linha_de_comando_sem_pasta_configurada_ou_inexistente(tmp_path, monkeypatch, capsys):
    pasta_entrada, saida, _ = _pastas(tmp_path)
    _configurar(monkeypatch, tmp_path, None, pasta_entrada)
    assert saidas.main([]) == 2
    assert "Defina SHAREPOINT_PASTA_SAIDA" in capsys.readouterr().out
    _configurar(monkeypatch, tmp_path, tmp_path / "nao_existe", pasta_entrada)
    assert saidas.main([]) == 2
    assert "Pasta de saída não encontrada" in capsys.readouterr().out


def test_linha_de_comando_marca_o_processo_como_analisado_no_banco(tmp_path, monkeypatch, capsys):
    from banco.controle import ControleProcessos

    entrada = _entrada()
    pasta_entrada, saida, _ = _pastas(tmp_path, entrada)
    _configurar(monkeypatch, tmp_path, saida, pasta_entrada)
    numero = entrada["processo"]["numero"]
    banco = ControleProcessos(config.CAMINHO_BANCO)
    banco.salvar(numero, "exportado", arquivo_entrada="entrada.json")
    banco.fechar()

    (saida / "OK.md").write_text(_analise(entrada), encoding="utf-8")
    assert saidas.main([]) == 0
    assert "não está no banco" not in capsys.readouterr().out

    banco = ControleProcessos(config.CAMINHO_BANCO)
    linha = banco.conexao.execute("SELECT status, arquivo_entrada, arquivo_saida FROM processos").fetchone()
    banco.fechar()
    assert linha == ("analisado", "entrada.json", str(tmp_path / "validadas" / "OK.md"))


def test_linha_de_comando_avisa_quando_o_processo_nao_esta_no_banco(tmp_path, monkeypatch, capsys):
    entrada = _entrada()
    pasta_entrada, saida, _ = _pastas(tmp_path, entrada)
    _configurar(monkeypatch, tmp_path, saida, pasta_entrada)
    (saida / "OK.md").write_text(_analise(entrada), encoding="utf-8")
    assert saidas.main([]) == 0
    assert "Banco: o processo" in capsys.readouterr().out


def test_linha_de_comando_registra_a_execucao_e_o_historico(tmp_path, monkeypatch, capsys):
    from banco.controle import ControleProcessos

    entrada = _entrada()
    pasta_entrada, saida, _ = _pastas(tmp_path, entrada)
    _configurar(monkeypatch, tmp_path, saida, pasta_entrada)
    numero = entrada["processo"]["numero"]
    banco = ControleProcessos(config.CAMINHO_BANCO)
    banco.salvar(numero, "exportado")
    banco.fechar()

    assert saidas.main([]) == 0  # sem análise nova: não registra execução à toa
    assert saidas.main([]) == 0
    banco = ControleProcessos(config.CAMINHO_BANCO)
    assert banco.execucoes_recentes() == []

    (saida / "OK.md").write_text(_analise(entrada), encoding="utf-8")
    banco.fechar()
    assert saidas.main([]) == 0
    banco = ControleProcessos(config.CAMINHO_BANCO)
    (execucao,) = banco.execucoes_recentes()
    assert execucao[3] == "saidas" and execucao[7] == 1 and execucao[8] == 0  # modo, análises, código de saída
    assert [e[3:] for e in banco.historico_do_processo(numero)] == [("OK.md", "ok", None)]
    banco.fechar()
