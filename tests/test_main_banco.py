"""O fluxo do main() com o banco: falhas, código de saída, reaproveitamento do JSON, teto de tentativas e totais da execução."""
import argparse

import pytest

import config
import main
from banco.controle import ControleProcessos
from sei.modelos import DocumentoSEI, ProcessoSEI


class SEIFalso:
    """Imita o SEIService: lista os processos marcados e coleta (ou falha ao coletar)."""

    def __init__(self, marcados=("P1",), falha=None):
        self.marcados, self.falha, self.coletados = list(marcados), falha, []

    def autenticar(self, *args):
        return True

    def listar_todos(self):
        return list(self.marcados)

    def listar_por_marcador(self, marcador):
        return list(self.marcados)

    def coletar_processo(self, numero):
        self.coletados.append(numero)
        if isinstance(self.falha, Exception):
            raise self.falha
        if self.falha:
            return None
        return ProcessoSEI(
            numero=numero,
            documentos=[DocumentoSEI(nome="D", texto="À SUPCONFI", origem_texto="sei_html", unidade="SEFAZ/SUBTES")],
        )

    def apagar_downloads(self, numero):
        pass

    def fechar(self):
        pass


@pytest.fixture
def preparar(monkeypatch, tmp_path):
    """Devolve rodar(sei, onedrive=True, processo=None, reanalisar=False) -> código de saída do main()."""
    monkeypatch.setattr(config, "SEI_MODO", "marcador")
    monkeypatch.setattr(config, "SEI_USUARIO", "usuario")
    monkeypatch.setattr(config, "TENTATIVAS_MAXIMAS", 3)
    monkeypatch.setattr(config, "PASTA_AUTOMATE_ENTRADA", tmp_path / "entrada")
    monkeypatch.setattr(config, "SHAREPOINT_PASTA_SAIDA", None)
    monkeypatch.setattr(main.getpass, "getpass", lambda *_: "senha")
    monkeypatch.setattr(main, "_interativo", lambda: True)

    def rodar(sei, onedrive=True, processo=None, reanalisar=False, sharepoint_configurado=True):
        destino = tmp_path / "onedrive"
        if onedrive:
            destino.mkdir(exist_ok=True)
        # onedrive=False deixa a pasta inexistente (OneDrive fechado): a entrega falha
        monkeypatch.setattr(config, "SHAREPOINT_PASTA_ENTRADA", destino if sharepoint_configurado else None)
        monkeypatch.setattr(main, "SEIService", lambda *a, **k: sei)
        monkeypatch.setattr(
            main, "argumentos", lambda: argparse.Namespace(processo=processo, reanalisar=reanalisar, sem_saida=True)
        )
        return main.main()

    return rodar


def _banco():
    return ControleProcessos(config.CAMINHO_BANCO)


def _linha(numero="P1"):
    banco = _banco()
    try:
        return banco.linha(numero)
    finally:
        banco.fechar()


def _ultima_execucao():
    banco = _banco()
    try:
        return banco.execucoes_recentes(1)[0]
    finally:
        banco.fechar()


# --- sucesso

def test_execucao_sem_falhas_devolve_0_e_registra_a_execucao(preparar):
    assert preparar(SEIFalso()) == 0
    assert _linha()["status"] == "exportado" and _linha()["falhas_seguidas"] == 0
    _, _, fim, modo, selecionados, exportados, falhas, analises, codigo = _ultima_execucao()
    assert fim and modo == "marcador" and (selecionados, exportados, falhas, analises, codigo) == (1, 1, 0, 0, 0)


def test_sem_pasta_do_sharepoint_o_json_nao_e_copiado_mas_nao_e_falha(preparar):
    assert preparar(SEIFalso(), sharepoint_configurado=False) == 0
    assert _linha()["status"] == "exportado"
    assert _ultima_execucao()[4:7] == (1, 1, 0)  # selecionados, exportados, falhas


# --- falhas e código de saída

@pytest.mark.parametrize("falha", [True, RuntimeError("iframe indisponível")])
def test_falha_na_coleta_devolve_1_e_fica_registrada(preparar, falha):
    assert preparar(SEIFalso(falha=falha)) == 1
    linha = _linha()
    assert linha["status"] == "erro_coleta" and linha["falhas_seguidas"] == 1 and linha["erro"]
    assert _ultima_execucao()[6:] == (1, 0, 1)  # falhas, análises, código de saída


def test_falha_na_entrega_devolve_1_e_guarda_o_json_para_depois(preparar):
    assert preparar(SEIFalso(), onedrive=False) == 1
    linha = _linha()
    assert linha["status"] == "erro_envio" and linha["arquivo_entrada"] and linha["falhas_seguidas"] == 1
    assert _ultima_execucao()[4:7] == (1, 0, 1)


def test_falha_de_autenticacao_devolve_1_e_a_execucao_fica_registrada(preparar):
    class SemLogin(SEIFalso):
        def autenticar(self, *args):
            return False

    assert preparar(SemLogin()) == 1
    _, _, fim, _, _, _, _, _, codigo = _ultima_execucao()
    assert fim and codigo == 1


def test_erro_inesperado_no_sei_nao_derruba_o_main_vai_ao_log_e_fecha_o_navegador(preparar, caplog):
    class QuebraNaLista(SEIFalso):
        fechado = False

        def listar_todos(self):
            raise RuntimeError("SEI fora do ar")

        def fechar(self):
            self.fechado = True

    sei = QuebraNaLista()
    assert preparar(sei) == 1  # não levanta: o Agendador de Tarefas só veria a tela de erro, que ninguém lê
    assert sei.fechado
    assert "SEI fora do ar" in caplog.text
    _, _, fim, _, _, _, _, _, codigo = _ultima_execucao()
    assert fim and codigo == 1


def test_navegador_que_nao_abre_devolve_1_e_a_execucao_fica_registrada(preparar, monkeypatch, caplog):
    def nao_abre(*args, **kwargs):
        raise RuntimeError("driver incompatível")

    preparar(SEIFalso())  # só para aplicar a configuração do teste
    monkeypatch.setattr(main, "SEIService", nao_abre)
    monkeypatch.setattr(main, "argumentos", lambda: argparse.Namespace(processo=None, reanalisar=False, sem_saida=True))
    assert main.main() == 1
    assert "driver incompatível" in caplog.text
    _, _, fim, _, _, _, _, _, codigo = _ultima_execucao()
    assert fim and codigo == 1


# --- reaproveitar o JSON

def test_reenvio_reaproveita_o_json_sem_coletar_de_novo(preparar):
    sei = SEIFalso()
    assert preparar(sei, onedrive=False) == 1
    assert sei.coletados == ["P1"]

    assert preparar(sei, onedrive=True) == 0
    assert sei.coletados == ["P1"]  # não coletou outra vez
    linha = _linha()
    assert linha["status"] == "exportado" and linha["falhas_seguidas"] == 0
    assert _ultima_execucao()[4:7] == (1, 1, 0)


def test_json_que_sumiu_obriga_a_coletar_de_novo(preparar):
    sei = SEIFalso()
    preparar(sei, onedrive=False)
    from pathlib import Path

    Path(_linha()["arquivo_entrada"]).unlink()
    assert preparar(sei, onedrive=True) == 0
    assert sei.coletados == ["P1", "P1"]


@pytest.mark.parametrize("opcoes", [{"reanalisar": True}, {"processo": "P1"}])
def test_reanalisar_e_processo_sempre_coletam_de_novo(preparar, opcoes):
    sei = SEIFalso()
    preparar(sei, onedrive=False)
    assert preparar(sei, onedrive=True, **opcoes) == 0
    assert sei.coletados == ["P1", "P1"]


# --- teto de tentativas

def test_processo_que_falhou_demais_e_ignorado_ate_ser_pedido(preparar):
    sei = SEIFalso(falha=True)
    for _ in range(3):
        assert preparar(sei) == 1
    assert sei.coletados == ["P1"] * 3 and _linha()["falhas_seguidas"] == 3

    assert preparar(sei) == 0  # ignorado, e por isso não é uma falha desta execução
    assert sei.coletados == ["P1"] * 3
    assert _ultima_execucao()[4:7] == (0, 0, 0)  # nada selecionado: o processo foi ignorado

    assert preparar(sei, processo="P1") == 1  # pedido explicitamente: tenta de novo
    assert sei.coletados == ["P1"] * 4


def test_teto_configuravel(preparar, monkeypatch):
    monkeypatch.setattr(config, "TENTATIVAS_MAXIMAS", 1)
    sei = SEIFalso(falha=True)
    preparar(sei)
    preparar(sei)
    assert sei.coletados == ["P1"]  # com teto 1, a primeira falha já basta
