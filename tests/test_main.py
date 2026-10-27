import config
import main
from banco.controle import ControleProcessos


class SEIFalso:
    def __init__(self, todos, marcados=()):
        self.todos = todos
        self.marcados = list(marcados)

    def listar_todos(self):
        return self.todos

    def listar_por_marcador(self, marcador):
        return self.marcados


def _controle(tmp_path):
    return ControleProcessos(tmp_path / "t.db")


def test_processo_unico_ignora_controle(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SEI_MODO", "marcador")
    c = _controle(tmp_path)
    c.salvar("P1", "exportado")
    assert main.escolher_processos(SEIFalso(["P1"]), c, processo_unico="P1") == ["P1"]
    c.fechar()


def test_modo_marcador_filtra_conhecidos(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SEI_MODO", "marcador")
    c = _controle(tmp_path)
    c.salvar("P1", "exportado")
    sei = SEIFalso([], marcados=["P1", "P2"])
    assert main.escolher_processos(sei, c) == ["P2"]
    assert main.escolher_processos(sei, c, reanalisar=True) == ["P1", "P2"]
    c.fechar()


def test_modo_novos_primeira_execucao_registra_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SEI_MODO", "novos")
    c = _controle(tmp_path)
    sei = SEIFalso(["P1", "P2"])
    assert main.escolher_processos(sei, c) == []
    assert c.conhecido("P1") and c.conhecido("P2")
    sei.todos = ["P1", "P2", "P3"]
    assert main.escolher_processos(sei, c) == ["P3"]
    c.fechar()


def test_erro_de_coleta_permite_nova_tentativa(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SEI_MODO", "marcador")
    c = _controle(tmp_path)
    c.salvar("P1", "erro_coleta", erro="x")
    assert main.escolher_processos(SEIFalso([], ["P1"]), c) == ["P1"]
    c.fechar()


def test_erro_envio_permite_nova_tentativa(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SEI_MODO", "marcador")
    c = _controle(tmp_path)
    c.salvar("P1", "erro_envio", erro="x")
    assert main.escolher_processos(SEIFalso([], ["P1"]), c) == ["P1"]
    c.fechar()
