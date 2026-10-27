import argparse
import json
import os

import config
import main
from automate import saidas
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
