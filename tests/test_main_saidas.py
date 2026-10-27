import argparse
import json
import os

import config
import main
from automate import saidas
from banco.controle import ControleProcessos
from sei.modelos import DocumentoSEI, ProcessoSEI
from test_validador import _analise, _entrada


class _LogFalso:
    def __init__(self):
        self.registros = []

    def _registrar(self, nivel, mensagem, *args):
        self.registros.append((nivel, mensagem % args if args else mensagem))

    def info(self, mensagem, *args):
        self._registrar("info", mensagem, *args)

    def warning(self, mensagem, *args):
        self._registrar("warning", mensagem, *args)

    def error(self, mensagem, *args):
        self._registrar("error", mensagem, *args)

    def exception(self, mensagem, *args):
        self._registrar("exception", mensagem, *args)

    def mensagens(self, nivel):
        return [m for n, m in self.registros if n == nivel]


def _configurar(monkeypatch, tmp_path, com_saida=True):
    pasta_saida = tmp_path / "onedrive_saida"
    pasta_saida.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "SHAREPOINT_PASTA_SAIDA", pasta_saida if com_saida else None)
    monkeypatch.setattr(config, "SHAREPOINT_PASTA_ENTRADA", tmp_path / "onedrive_entrada")
    monkeypatch.setattr(config, "PASTA_AUTOMATE_ENTRADA", tmp_path / "entrada")
    monkeypatch.setattr(config, "PASTA_AUTOMATE_SAIDA", tmp_path / "validadas")
    monkeypatch.setattr(config, "SAIDA_ESPERA_MINUTOS", 30)
    monkeypatch.setattr(config, "SAIDA_INTERVALO_SEGUNDOS", 20)
    log = _LogFalso()
    monkeypatch.setattr(main, "log", log)
    return pasta_saida, log


def _nao_deve_aguardar(*args, **kwargs):
    raise AssertionError("não deveria esperar pela pasta de saída")


def test_entregar_diz_se_copiou(tmp_path, monkeypatch):
    arquivo = tmp_path / "ENTRADA_X.json"
    arquivo.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "SHAREPOINT_PASTA_ENTRADA", None)
    assert main.entregar(arquivo) is False
    destino = tmp_path / "sharepoint"
    destino.mkdir()
    monkeypatch.setattr(config, "SHAREPOINT_PASTA_ENTRADA", destino)
    assert main.entregar(arquivo) is True and (destino / "ENTRADA_X.json").is_file()


def test_sem_pasta_de_saida_configurada_ou_inexistente_nao_espera(tmp_path, monkeypatch):
    _, log = _configurar(monkeypatch, tmp_path, com_saida=False)
    monkeypatch.setattr(saidas, "aguardar_e_processar", _nao_deve_aguardar)
    main.processar_saidas(["P1"], set())
    assert log.registros == []
    monkeypatch.setattr(config, "SHAREPOINT_PASTA_SAIDA", tmp_path / "nao_existe")
    main.processar_saidas(["P1"], set())
    assert "Pasta de saída não encontrada" in log.mensagens("warning")[0]


def test_espera_so_quando_algo_foi_entregue(tmp_path, monkeypatch):
    _configurar(monkeypatch, tmp_path)
    chamadas = []
    monkeypatch.setattr(saidas, "aguardar_e_processar", lambda *a, **k: chamadas.append(a) or ([], []))
    main.processar_saidas([], set())  # nada entregue: não olha a pasta de saída
    main.processar_saidas(["P1"], {"abc"})
    assert len(chamadas) == 1
    assert chamadas[0][3] == ["P1"] and chamadas[0][4] == {"abc"} and chamadas[0][5] == 30 * 60 and chamadas[0][6] == 20


def test_analise_que_chega_e_processada_e_registrada(tmp_path, monkeypatch):
    pasta_saida, log = _configurar(monkeypatch, tmp_path)
    entrada = _entrada()
    (tmp_path / "entrada").mkdir()
    (tmp_path / "entrada" / "ENTRADA_SEI-040005_000729_2026.json").write_text(json.dumps(entrada), encoding="utf-8")
    (pasta_saida / "ANALISE_X.md").write_text(_analise(entrada), encoding="utf-8")
    os.utime(pasta_saida / "ANALISE_X.md", (1_000_000_000, 1_000_000_000))  # já estável: não está sendo gravada
    main.processar_saidas(["SEI-040005/000729/2026"], set())
    assert any(
        "Análise ANALISE_X.md (processo SEI-040005/000729/2026): 0 correção(ões), 0 erro(s), 0 aviso(s)" in m
        for m in log.mensagens("info")
    )
    assert (tmp_path / "validadas" / "ANALISE_X.validacao.txt").is_file()
    assert log.mensagens("warning") == []


def test_analise_que_nao_chega_gera_aviso_com_o_comando_para_depois(tmp_path, monkeypatch):
    _, log = _configurar(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "SAIDA_ESPERA_MINUTOS", 0)
    main.processar_saidas(["SEI-1/2/3"], set())
    assert "Sem análise após 0 min: SEI-1/2/3. Rode `python -m automate.saidas` mais tarde." in log.mensagens("warning")


def test_erro_na_espera_nao_derruba_a_execucao(tmp_path, monkeypatch):
    _, log = _configurar(monkeypatch, tmp_path)

    def quebra(*args, **kwargs):
        raise RuntimeError("falha qualquer")

    monkeypatch.setattr(saidas, "aguardar_e_processar", quebra)
    main.processar_saidas(["P1"], set())
    assert log.mensagens("exception") == ["Falha ao processar a pasta de saída."]

    def interrompe(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(saidas, "aguardar_e_processar", interrompe)
    main.processar_saidas(["P1"], set())
    assert "Espera pelas análises interrompida." in log.mensagens("warning")


class _SEIFalso:
    def __init__(self, eventos):
        self.eventos = eventos

    def autenticar(self, *args):
        return True

    def listar_todos(self):
        return []

    def coletar_processo(self, numero):
        return ProcessoSEI(
            numero=numero,
            documentos=[DocumentoSEI(nome="D", texto="À SUPCONFI", origem_texto="sei_html", unidade="SEFAZ/SUBTES")],
        )

    def apagar_downloads(self, numero):
        self.eventos.append(("downloads apagados", numero))

    def fechar(self):
        self.eventos.append("navegador fechado")


def _preparar_main(monkeypatch, tmp_path, eventos, sem_saida):
    for pasta in ("entrada", "onedrive_entrada"):
        (tmp_path / pasta).mkdir(exist_ok=True)
    monkeypatch.setattr(main, "SEIService", lambda *a, **k: _SEIFalso(eventos))
    monkeypatch.setattr(main, "argumentos", lambda: argparse.Namespace(processo="P1", reanalisar=False, sem_saida=sem_saida))
    monkeypatch.setattr(main.getpass, "getpass", lambda *_: "senha")
    monkeypatch.setattr(main, "_interativo", lambda: True)
    monkeypatch.setattr(config, "SEI_USUARIO", "usuario")
    monkeypatch.setattr(config, "CAMINHO_BANCO", tmp_path / "t.db")


def test_main_entrega_fecha_o_navegador_e_so_depois_espera(tmp_path, monkeypatch):
    pasta_saida, _ = _configurar(monkeypatch, tmp_path)
    (pasta_saida / "antiga.md").write_text("## Processo\nSEI-9/9/9\n", encoding="utf-8")
    eventos = []
    _preparar_main(monkeypatch, tmp_path, eventos, sem_saida=False)
    monkeypatch.setattr(
        saidas, "aguardar_e_processar",
        lambda pasta, entradas, destino, aguardados, antes, espera, intervalo, **k: eventos.append(
            ("espera", aguardados, len(antes), espera)
        ) or ([], []),
    )

    assert main.main() == 0
    assert (tmp_path / "onedrive_entrada" / "ENTRADA_P1.json").is_file()
    assert eventos == [("downloads apagados", "P1"), "navegador fechado", ("espera", ["P1"], 1, 30 * 60)]


def test_main_com_sem_saida_nao_espera(tmp_path, monkeypatch):
    _configurar(monkeypatch, tmp_path)
    _preparar_main(monkeypatch, tmp_path, [], sem_saida=True)
    monkeypatch.setattr(saidas, "aguardar_e_processar", _nao_deve_aguardar)
    assert main.main() == 0


def test_main_liga_o_log_so_ao_executar(tmp_path, monkeypatch):
    _configurar(monkeypatch, tmp_path)
    _preparar_main(monkeypatch, tmp_path, [], sem_saida=True)
    chamadas = []
    monkeypatch.setattr(main, "_configurar_log", lambda: chamadas.append("log"))
    assert chamadas == []  # importar o módulo não liga o log em arquivo
    assert main.main() == 0
    assert chamadas == ["log"]


# --- o banco acompanha a análise

def _banco_com(tmp_path, numero="SEI-040005/000729/2026"):
    controle = ControleProcessos(tmp_path / "banco.db")
    controle.salvar(numero, "exportado", arquivo_entrada="entrada.json")
    return controle


def _linha(controle, numero="SEI-040005/000729/2026"):
    return controle.conexao.execute(
        "SELECT status, arquivo_entrada, arquivo_saida, erro FROM processos WHERE numero=?", (numero,)
    ).fetchone()


def _analise_na_saida(tmp_path, pasta_saida, **trocas):
    entrada = _entrada()
    (tmp_path / "entrada").mkdir(exist_ok=True)
    (tmp_path / "entrada" / "ENTRADA_SEI-040005_000729_2026.json").write_text(json.dumps(entrada), encoding="utf-8")
    (pasta_saida / "ANALISE_X.md").write_text(_analise(entrada, **trocas), encoding="utf-8")
    os.utime(pasta_saida / "ANALISE_X.md", (1_000_000_000, 1_000_000_000))


def test_analise_que_chega_marca_o_processo_como_analisado(tmp_path, monkeypatch):
    pasta_saida, log = _configurar(monkeypatch, tmp_path)
    _analise_na_saida(tmp_path, pasta_saida)
    controle = _banco_com(tmp_path)
    main.processar_saidas(["SEI-040005/000729/2026"], set(), controle)
    status, entrada, saida, erro = _linha(controle)
    assert status == "analisado" and entrada == "entrada.json" and erro is None
    assert saida == str(tmp_path / "validadas" / "ANALISE_X.md")
    assert log.mensagens("warning") == []
    controle.fechar()


def test_analise_com_erro_de_validacao_fica_analisada_com_o_resumo(tmp_path, monkeypatch):
    pasta_saida, _ = _configurar(monkeypatch, tmp_path)
    _analise_na_saida(tmp_path, pasta_saida, competencia="COMPETÊNCIA PARCIAL. Talvez.")
    controle = _banco_com(tmp_path)
    main.processar_saidas(["SEI-040005/000729/2026"], set(), controle)
    status, _, _, erro = _linha(controle)
    assert status == "analisado" and controle.conhecido("SEI-040005/000729/2026")  # não será coletado de novo
    assert erro == "Validação: 1 ERRO(s)"
    controle.fechar()


def test_analise_de_processo_fora_do_banco_gera_aviso_e_nao_cria_linha(tmp_path, monkeypatch):
    pasta_saida, log = _configurar(monkeypatch, tmp_path)
    _analise_na_saida(tmp_path, pasta_saida)
    controle = _banco_com(tmp_path, numero="SEI-outro")
    main.processar_saidas(["SEI-040005/000729/2026"], set(), controle)
    assert any("SEI-040005/000729/2026 não está no banco" in m for m in log.mensagens("warning"))
    assert controle.conexao.execute("SELECT COUNT(*) FROM processos").fetchone()[0] == 1
    controle.fechar()


def test_falha_do_banco_nao_derruba_o_processamento_da_analise(tmp_path, monkeypatch):
    pasta_saida, log = _configurar(monkeypatch, tmp_path)
    _analise_na_saida(tmp_path, pasta_saida)

    class _BancoQuebrado:
        def registrar_analise(self, *args):
            raise RuntimeError("banco travado")

    main.processar_saidas(["SEI-040005/000729/2026"], set(), _BancoQuebrado())
    assert log.mensagens("exception") == ["Não foi possível atualizar o banco com a análise ANALISE_X.md."]
    assert (tmp_path / "validadas" / "ANALISE_X.validacao.txt").is_file()  # a análise foi corrigida e validada


def test_main_mantem_o_banco_aberto_ate_depois_da_espera(tmp_path, monkeypatch):
    _configurar(monkeypatch, tmp_path)
    _preparar_main(monkeypatch, tmp_path, [], sem_saida=False)
    estado = {}

    def espera(entregues, antes, controle=None):
        controle.conexao.execute("SELECT 1")  # levanta ProgrammingError se já estiver fechado
        estado["controle"] = controle

    monkeypatch.setattr(main, "processar_saidas", espera)
    assert main.main() == 0
    assert "controle" in estado
    try:
        estado["controle"].conexao.execute("SELECT 1")
        fechado = False
    except Exception:
        fechado = True
    assert fechado  # e só é fechado no fim da execução


def test_resultado_do_teams_e_os_eventos_da_analise_vao_para_o_banco(tmp_path, monkeypatch):
    pasta_saida, _ = _configurar(monkeypatch, tmp_path)
    _analise_na_saida(tmp_path, pasta_saida)
    monkeypatch.setattr(main.teams, "configurado", lambda: True)
    monkeypatch.setattr(main.teams, "enviar_resultado", lambda resultado: False)  # o Teams recusou
    controle = _banco_com(tmp_path)
    controle.iniciar_execucao("marcador")
    main.processar_saidas(["SEI-040005/000729/2026"], set(), controle)
    assert controle.linha("SEI-040005/000729/2026")["teams_enviado"] == 0
    eventos = [(etapa, resultado) for _, _, etapa, resultado, _ in controle.historico_do_processo("SEI-040005/000729/2026")]
    assert eventos == [("analise", "ok"), ("teams", "erro")]
    controle.fechar()


def test_teams_desligado_deixa_teams_enviado_vazio(tmp_path, monkeypatch):
    pasta_saida, _ = _configurar(monkeypatch, tmp_path)
    _analise_na_saida(tmp_path, pasta_saida)
    controle = _banco_com(tmp_path)
    main.processar_saidas(["SEI-040005/000729/2026"], set(), controle)
    assert controle.linha("SEI-040005/000729/2026")["teams_enviado"] is None
    assert [e[2] for e in controle.historico_do_processo("SEI-040005/000729/2026")] == ["analise"]
    controle.fechar()
