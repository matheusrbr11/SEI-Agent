import json
import os

import pytest
import requests

import config
import main
from automate import saidas, teams
from automate.saidas import Resultado
from test_main_saidas import _LogFalso, _configurar
from test_saidas import _pastas
from test_validador import _analise, _entrada

WEBHOOK = "https://exemplo.invalid/webhook-de-teste"
PESSOA = "fulano@fazenda.rj.gov.br"


class _RespostaFalsa:
    def __init__(self, status=200):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code}")


@pytest.fixture(autouse=True)
def pausas(monkeypatch):
    """Sem esperar de verdade entre as tentativas; devolve as pausas pedidas."""
    pedidas = []
    monkeypatch.setattr(teams.time, "sleep", pedidas.append)
    return pedidas


@pytest.fixture
def envios(monkeypatch):
    """Registra os POSTs em vez de enviar de verdade."""
    registrados = []

    def post(url, json=None, timeout=None):
        registrados.append({"url": url, "json": json, "timeout": timeout})
        return _RespostaFalsa()

    monkeypatch.setattr(teams.requests, "post", post)
    return registrados


@pytest.fixture
def teams_ligado(monkeypatch):
    monkeypatch.setattr(config, "TEAMS_WEBHOOK_URL", WEBHOOK)
    monkeypatch.setattr(config, "TEAMS_DESTINATARIOS", [PESSOA])
    monkeypatch.setattr(config, "TEAMS_LIMITE_CARACTERES", 25000)


def _resultado(tmp_path, texto="## Processo\nSEI-1/2/3\n", problemas=(), correcoes=("Alertas reformatados",)):
    corrigido = tmp_path / "ANALISE_X.md"
    corrigido.write_text(texto, encoding="utf-8")
    return Resultado(
        arquivo="ANALISE_X.md", numero="SEI-1/2/3", correcoes=list(correcoes), problemas=list(problemas), corrigido=str(corrigido)
    )


# --- mensagem

def test_mensagem_e_o_markdown_da_analise_depois_de_um_cabecalho_minimo():
    texto = "## Processo\nSEI-1/2/3\n\n## Demanda\nAnexar aos autos.\n"
    # o cabeçalho evita que o "## Processo" abra a mensagem (nesse caso o Teams o mostrava como texto cru)
    assert teams.montar_mensagem(texto, 25000) == "SEI-Agent\n\n---\n## Processo\nSEI-1/2/3\n\n## Demanda\nAnexar aos autos."


def test_texto_acima_do_limite_e_cortado_e_o_corte_vai_para_o_log(monkeypatch):
    class LogFalso:
        avisos = []

        def warning(self, mensagem, *args):
            self.avisos.append(mensagem % args)

    monkeypatch.setattr(teams, "logger", LogFalso())
    mensagem = teams.montar_mensagem("palavra " * 5000, 1000)
    assert len(mensagem) <= 1000 and mensagem.startswith("SEI-Agent\n\n---\npalavra palavra")
    assert LogFalso.avisos == ["Análise com 39999 caracteres cortada em 1000 para caber no Teams."]
    assert teams.montar_mensagem("curto", 1000) == "SEI-Agent\n\n---\ncurto"  # dentro do limite não registra nada


# --- envio

def test_envia_o_mesmo_json_do_graphapi_da_jupiter(envios):
    assert teams.enviar("olá", WEBHOOK, [PESSOA]) is True
    assert envios == [{"url": WEBHOOK, "json": {"destinatarios": [PESSOA], "mensagem": "olá"}, "timeout": teams.TIMEOUT_SEGUNDOS}]


@pytest.mark.parametrize("falha", ["http", "rede"])
def test_falha_no_envio_vira_false_sem_levantar_excecao(monkeypatch, falha):
    def post(*args, **kwargs):
        if falha == "rede":
            raise requests.exceptions.ConnectionError("sem rede")
        return _RespostaFalsa(status=500)

    monkeypatch.setattr(teams.requests, "post", post)
    assert teams.enviar("olá", WEBHOOK, [PESSOA]) is False


def _post_que_falha_ate(tentativa_que_funciona, erro):
    chamadas = []

    def post(*args, **kwargs):
        chamadas.append(1)
        if len(chamadas) < tentativa_que_funciona:
            raise erro
        return _RespostaFalsa()

    return post, chamadas


def test_falha_passageira_e_tentada_de_novo_e_conta_como_enviada(monkeypatch, pausas):
    post, chamadas = _post_que_falha_ate(3, requests.exceptions.SSLError("certificate verify failed"))
    monkeypatch.setattr(teams.requests, "post", post)
    assert teams.enviar("olá", WEBHOOK, [PESSOA]) is True
    assert len(chamadas) == 3 and pausas == [5, 15]


def test_desiste_depois_de_tres_tentativas(monkeypatch, pausas):
    post, chamadas = _post_que_falha_ate(99, requests.exceptions.ConnectionError("sem rede"))
    monkeypatch.setattr(teams.requests, "post", post)
    assert teams.enviar("olá", WEBHOOK, [PESSOA]) is False
    assert len(chamadas) == 3 and pausas == [5, 15]


@pytest.mark.parametrize("status,tentativas", [(500, 3), (503, 3), (429, 3), (400, 1), (401, 1), (404, 1)])
def test_so_repete_erro_http_do_servidor_ou_limite_de_uso(monkeypatch, status, tentativas):
    chamadas = []

    class Resposta(_RespostaFalsa):
        def raise_for_status(self):
            erro = requests.exceptions.HTTPError(f"{status}")
            erro.response = self
            raise erro

    def post(*args, **kwargs):
        chamadas.append(1)
        return Resposta(status)

    monkeypatch.setattr(teams.requests, "post", post)
    assert teams.enviar("olá", WEBHOOK, [PESSOA]) is False
    assert len(chamadas) == tentativas


def test_log_nao_mostra_a_chave_do_webhook(monkeypatch, caplog):
    monkeypatch.setattr(teams.logger, "propagate", True)  # o logger da jupiter não propaga; aqui interessa só o texto
    url = "https://exemplo.invalid/invoke?api-version=1&sp=%2Ftriggers&sig=SEGREDO123abc_-"
    erro = requests.exceptions.SSLError(f"HTTPSConnectionPool: Max retries exceeded with url: {url} (Caused by SSLError)")
    post, _ = _post_que_falha_ate(99, erro)
    monkeypatch.setattr(teams.requests, "post", post)
    with caplog.at_level("DEBUG", logger="jupiter.agente.teams"):
        assert teams.enviar("olá", url, [PESSOA]) is False
    texto = caplog.text + "".join(str(r.exc_info) for r in caplog.records)
    assert "SEGREDO123abc" not in texto and "sig=***" in texto
    assert all(r.exc_info is None for r in caplog.records)


def test_nao_envia_sem_webhook_ou_sem_destinatario(tmp_path, envios, monkeypatch):
    assert teams.configurado() is False and teams.enviar_resultado(_resultado(tmp_path)) is False
    monkeypatch.setattr(config, "TEAMS_WEBHOOK_URL", WEBHOOK)  # sem destinatário
    assert teams.configurado() is False and teams.enviar_resultado(_resultado(tmp_path)) is False
    monkeypatch.setattr(config, "TEAMS_WEBHOOK_URL", "")
    monkeypatch.setattr(config, "TEAMS_DESTINATARIOS", [PESSOA])  # sem webhook
    assert teams.configurado() is False
    assert envios == []


def test_enviar_resultado_manda_o_texto_corrigido_para_a_pessoa(tmp_path, envios, teams_ligado):
    resultado = _resultado(tmp_path, texto="## Processo\nSEI-1/2/3\n\n## Demanda\nAnexar aos autos.\n")
    assert teams.enviar_resultado(resultado) is True
    (envio,) = envios
    assert envio["url"] == WEBHOOK and envio["json"]["destinatarios"] == [PESSOA]
    assert envio["json"]["mensagem"] == "SEI-Agent\n\n---\n## Processo\nSEI-1/2/3\n\n## Demanda\nAnexar aos autos."  # cabeçalho + .md


def test_arquivo_corrigido_ilegivel_nao_derruba(tmp_path, envios, teams_ligado):
    resultado = _resultado(tmp_path)
    resultado.corrigido = str(tmp_path / "nao_existe.md")
    assert teams.enviar_resultado(resultado) is False and envios == []


# --- configuração

@pytest.mark.parametrize("texto, esperado", [
    ("a@x.br, b@x.br,", ["a@x.br", "b@x.br"]),
    (f" {PESSOA} ", [PESSOA]),
    (" , ,", []),
    ("", []),
])
def test_destinatarios_do_env_separados_por_virgula(texto, esperado):
    assert config._emails(texto) == esperado


def test_config_json_nao_e_mais_usado():
    assert not hasattr(config, "CAMINHO_CONFIG_JSON")


# --- integração com a leitura da saída

def _entrada_e_analise(tmp_path):
    entrada = _entrada()
    pasta_entrada, saida, destino = _pastas(tmp_path, entrada)
    (saida / "ANALISE_X.md").write_text(_analise(entrada), encoding="utf-8")
    return pasta_entrada, saida


def test_comando_envia_cada_analise_nova_uma_vez(tmp_path, monkeypatch, capsys, envios, teams_ligado):
    pasta_entrada, saida = _entrada_e_analise(tmp_path)
    _configurar(monkeypatch, tmp_path, com_saida=True)
    monkeypatch.setattr(config, "SHAREPOINT_PASTA_SAIDA", saida)
    monkeypatch.setattr(config, "PASTA_AUTOMATE_ENTRADA", pasta_entrada)

    assert saidas.main([]) == 0
    assert "Teams: enviada" in capsys.readouterr().out and len(envios) == 1

    assert saidas.main([]) == 0  # nada novo: não reenvia
    assert len(envios) == 1


def test_refazer_e_sem_teams_nao_enviam(tmp_path, monkeypatch, capsys, envios, teams_ligado):
    pasta_entrada, saida = _entrada_e_analise(tmp_path)
    _configurar(monkeypatch, tmp_path, com_saida=True)
    monkeypatch.setattr(config, "SHAREPOINT_PASTA_SAIDA", saida)
    monkeypatch.setattr(config, "PASTA_AUTOMATE_ENTRADA", pasta_entrada)
    assert saidas.main(["--sem-teams"]) == 0
    assert saidas.main(["--refazer"]) == 0
    assert envios == []


def test_main_registra_o_envio_no_log(tmp_path, monkeypatch, envios, teams_ligado):
    log = _LogFalso()
    monkeypatch.setattr(main, "log", log)
    main._registrar(_resultado(tmp_path))
    assert log.mensagens("info")[-1] == f"Análise ANALISE_X.md enviada pelo Teams para {PESSOA}."

    monkeypatch.setattr(teams.requests, "post", lambda *a, **k: (_ for _ in ()).throw(requests.exceptions.Timeout()))
    main._registrar(_resultado(tmp_path))
    assert "Análise ANALISE_X.md NÃO foi enviada pelo Teams (veja o log de erros)." in log.mensagens("warning")


def test_main_so_envia_a_analise_do_processo_processado(tmp_path, monkeypatch, envios, teams_ligado):
    pasta_saida, log = _configurar(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "SAIDA_ESPERA_MINUTOS", 0)  # uma passada só; não dorme esperando o processo B
    (tmp_path / "entrada").mkdir()
    entrada = _entrada()
    (tmp_path / "entrada" / "ENTRADA_SEI-040005_000729_2026.json").write_text(json.dumps(entrada), encoding="utf-8")
    (pasta_saida / "ANALISE_A.md").write_text(_analise(entrada), encoding="utf-8")
    os.utime(pasta_saida / "ANALISE_A.md", (1_000_000_000, 1_000_000_000))  # já estável: não está sendo gravada

    # a pasta de saída tem a análise do processo A, mas a execução foi do processo B: nem analisa, nem envia
    main.processar_saidas(["SEI-9/9/9"], set())
    assert envios == [] and not (tmp_path / "validadas").exists()
    assert not any("Análise ANALISE_A.md" in m for _, m in log.registros)

    # análise do processo A que já estava na pasta antes desta execução: ignorada
    main.processar_saidas(["SEI-040005/000729/2026"], {saidas._impressao_digital(pasta_saida / "ANALISE_A.md")})
    assert envios == [] and not (tmp_path / "validadas").exists()

    # análise nova do processo A: analisada e enviada
    main.processar_saidas(["SEI-040005/000729/2026"], set())
    assert len(envios) == 1 and (tmp_path / "validadas" / "ANALISE_A.validacao.txt").is_file()


def test_main_sem_teams_configurado_nao_menciona_teams(tmp_path, monkeypatch, envios):
    log = _LogFalso()
    monkeypatch.setattr(main, "log", log)
    main._registrar(_resultado(tmp_path))
    assert not any("Teams" in m for _, m in log.registros) and envios == []


# --- comando de teste

def test_comando_de_teste_valida_a_configuracao(monkeypatch, capsys, envios):
    assert teams.main(["x"]) == 2  # sem --teste: mostra o uso
    assert teams.main(["x", "--teste"]) == 2 and "Sem webhook" in capsys.readouterr().out
    monkeypatch.setattr(config, "TEAMS_WEBHOOK_URL", WEBHOOK)
    assert teams.main(["x", "--teste"]) == 2 and "Sem destinatário" in capsys.readouterr().out
    monkeypatch.setattr(config, "TEAMS_DESTINATARIOS", [PESSOA])
    assert teams.main(["x", "--teste"]) == 0
    assert f"Mensagem de teste enviada para: {PESSOA}" in capsys.readouterr().out
    assert len(envios) == 1 and "Teste do SEI-Agent" in envios[0]["json"]["mensagem"]
