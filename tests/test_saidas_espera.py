import os

from automate import saidas
from automate.saidas import processar_pasta
from test_saidas import NUMERO, _pastas
from test_validador import _analise, _entrada


class _Relogio:
    """Relógio falso: dormir só avança a hora; `ao_dormir(n)` simula o que acontece na pasta durante a espera."""

    def __init__(self, ao_dormir=None):
        self.hora, self.esperas, self.ao_dormir = 0.0, [], ao_dormir

    def __call__(self):
        return self.hora

    def dormir(self, segundos):
        self.esperas.append(segundos)
        self.hora += segundos
        if self.ao_dormir:
            self.ao_dormir(len(self.esperas))


def _aguardar(saida, pasta_entrada, destino, relogio, aguardados=(NUMERO,), ja_existentes=frozenset(), espera=100, intervalo=10):
    return saidas.aguardar_e_processar(
        saida, [pasta_entrada], destino, list(aguardados), set(ja_existentes), espera, intervalo,
        estavel_ha=0, dormir=relogio.dormir, relogio=relogio,
    )


def _chega_na_espera(saida, entrada, numero_da_espera, **trocas):
    def ao_dormir(n):
        if n == numero_da_espera:
            (saida / "NOVA.md").write_text(_analise(entrada, **trocas), encoding="utf-8")

    return _Relogio(ao_dormir)


def test_espera_ate_a_analise_chegar_e_processa(tmp_path):
    entrada = _entrada()
    pasta_entrada, saida, destino = _pastas(tmp_path, entrada)
    relogio = _chega_na_espera(saida, entrada, 2)
    resultados, faltando = _aguardar(saida, pasta_entrada, destino, relogio)
    assert [r.arquivo for r in resultados] == ["NOVA.md"] and resultados[0].situacao == "OK"
    assert faltando == []
    assert relogio.esperas == [10, 10]  # parou assim que a análise chegou, sem esperar o tempo todo
    assert (destino / "NOVA.validacao.txt").is_file()


def test_desiste_ao_fim_do_tempo_e_diz_o_que_faltou(tmp_path):
    pasta_entrada, saida, destino = _pastas(tmp_path, _entrada())
    relogio = _Relogio()
    resultados, faltando = _aguardar(saida, pasta_entrada, destino, relogio, espera=25)
    assert resultados == [] and faltando == [NUMERO]
    assert relogio.esperas == [10, 10, 5]  # a última espera é só o que sobrou


def test_analise_antiga_do_mesmo_processo_e_ignorada_e_espera_a_nova(tmp_path):
    entrada = _entrada()
    pasta_entrada, saida, destino = _pastas(tmp_path, entrada)
    (saida / "ANTIGA.md").write_text(_analise(entrada, contexto="Análise de uma execução anterior."), encoding="utf-8")
    ja_existentes = saidas.impressoes_existentes(saida)
    assert len(ja_existentes) == 1

    resultados, faltando = _aguardar(saida, pasta_entrada, destino, _Relogio(), ja_existentes=ja_existentes, espera=20)
    assert resultados == [] and faltando == [NUMERO]  # a antiga nem é analisada
    assert not (destino / "ANTIGA.validacao.txt").exists()

    resultados, faltando = _aguardar(saida, pasta_entrada, destino, _chega_na_espera(saida, entrada, 1), ja_existentes=ja_existentes)
    assert [r.arquivo for r in resultados] == ["NOVA.md"] and faltando == []


def test_nova_versao_com_o_mesmo_nome_da_antiga_e_analisada(tmp_path):
    entrada = _entrada()
    pasta_entrada, saida, destino = _pastas(tmp_path, entrada)
    (saida / "A.md").write_text(_analise(entrada, contexto="Versão antiga."), encoding="utf-8")
    ja_existentes = saidas.impressoes_existentes(saida)

    def ao_dormir(n):  # o fluxo sobrescreve o arquivo com a versão nova
        (saida / "A.md").write_text(_analise(entrada, contexto="Versão nova."), encoding="utf-8")

    resultados, faltando = _aguardar(saida, pasta_entrada, destino, _Relogio(ao_dormir), ja_existentes=ja_existentes)
    assert [r.arquivo for r in resultados] == ["A.md"] and faltando == []
    assert "Versão nova." in (destino / "A.md").read_text(encoding="utf-8")


def test_analise_de_outro_processo_e_ignorada(tmp_path):
    entrada = _entrada()
    pasta_entrada, saida, destino = _pastas(tmp_path, entrada)
    (saida / "OUTRO.md").write_text(_analise(entrada, processo="SEI-040005/999999/2026"), encoding="utf-8")
    resultados, faltando = _aguardar(saida, pasta_entrada, destino, _Relogio(), espera=15)
    assert resultados == [] and faltando == [NUMERO]
    assert not (destino / "OUTRO.validacao.txt").exists()


def test_sem_nada_a_aguardar_nao_analisa_nada_e_nao_dorme(tmp_path):
    entrada = _entrada()
    pasta_entrada, saida, destino = _pastas(tmp_path, entrada)
    (saida / "A.md").write_text(_analise(entrada), encoding="utf-8")
    relogio = _Relogio()
    resultados, faltando = _aguardar(saida, pasta_entrada, destino, relogio, aguardados=(), espera=0)
    assert resultados == [] and faltando == [] and relogio.esperas == []


def test_depois_de_receber_a_analise_do_processo_nao_analisa_outra_versao(tmp_path):
    entrada = _entrada()
    pasta_entrada, saida, destino = _pastas(tmp_path, entrada)

    def ao_dormir(n):
        if n == 1:  # chega a análise do processo aguardado...
            (saida / "A1.md").write_text(_analise(entrada), encoding="utf-8")
        if n == 2:  # ...e depois outra versão dele, enquanto ainda se espera pelo outro processo
            (saida / "A2.md").write_text(_analise(entrada, contexto="Outra versão."), encoding="utf-8")

    resultados, faltando = _aguardar(
        saida, pasta_entrada, destino, _Relogio(ao_dormir), aguardados=(NUMERO, "SEI-040005/888888/2026"), espera=40
    )
    assert [r.arquivo for r in resultados] == ["A1.md"] and faltando == ["SEI-040005/888888/2026"]


def test_arquivo_alterado_ha_pouco_fica_para_a_proxima_passada(tmp_path):
    entrada = _entrada()
    pasta_entrada, saida, destino = _pastas(tmp_path, entrada)
    (saida / "A.md").write_text(_analise(entrada), encoding="utf-8")  # acabou de ser gravado (o OneDrive ainda sincroniza)
    assert processar_pasta(saida, [pasta_entrada], destino, estavel_ha=60) == []
    os.utime(saida / "A.md", (1_000_000_000, 1_000_000_000))
    assert len(processar_pasta(saida, [pasta_entrada], destino, estavel_ha=60)) == 1
