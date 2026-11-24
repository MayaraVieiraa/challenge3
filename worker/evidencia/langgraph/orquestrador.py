"""Fluxo de dois agentes com fontes congeladas e no máximo uma revisão.

O grafo mantém somente dados da execução. Clientes, conexões e modelos permanecem
fora do estado; nenhum checkpoint ou envio a serviço de observabilidade é criado.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import time
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from worker.evidencia import guardas as g
from worker.evidencia.context_window import ContextWindowExceeded, validar_janela_contexto
from worker.evidencia.explicador import RESPOSTAS_FIXAS
from .analista import VERSAO_PROMPT_JURIDICO, Analista
from .cliente_llm import ErroLLM
from .contratos import ErroContrato, MAX_PROBLEMAS
from .validador import Validador


MENSAGEM_INSUFICIENTE = (
    "As fontes disponíveis nesta execução não permitem fundamentar uma resposta "
    "à pergunta. Não é possível concluir com esse material. " + g.AVISO_LEGAL
)
MENSAGEM_BLOQUEADA = (
    "A resposta não passou pelos controles deste protótipo e precisa de revisão. "
    "Não é possível apresentar uma conclusão com segurança nesta execução. " + g.AVISO_LEGAL
)
MENSAGEM_FALHA = (
    "Não foi possível concluir a execução por uma falha técnica. "
    "Tente novamente após verificar o ambiente."
)
# A formulação antiga usa "Direito" na própria recusa e aciona a heurística
# sem_fontes. Esta resposta fixa comunica o escopo sem afirmar uma regra jurídica.
RESPOSTAS_ENCAMINHAMENTO = {
    **RESPOSTAS_FIXAS,
    "fora_escopo": (
        "Esse assunto está fora do escopo deste assistente. "
        "Procure orientação com um profissional da área correspondente."
    ),
    "outra_jurisdicao": (
        "Atendo questões trabalhistas do Brasil. Sobre outro país, "
        "consulte um profissional habilitado na respectiva jurisdição."
    ),
}


def _hash(valor):
    dados = json.dumps(valor, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return hashlib.sha256(dados.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ConfiguracaoSistema:
    max_chamadas_llm: int = 6
    max_revisoes: int = 1
    max_tentativas_tecnicas: int = 1
    timeout_segundos: float = 180
    tempo_maximo_segundos: float = 900
    # Reserva contexto para instruções, candidato e feedback da revisão.
    max_bytes_fontes: int = 5000
    modelo_analista: str = "qwen3:8b-q8_0"
    modelo_validador: str = "gemma3:12b"

    def __post_init__(self):
        for nome, minimo, maximo in (
            ("max_chamadas_llm", 1, 6),
            ("max_revisoes", 0, 1),
            ("max_tentativas_tecnicas", 0, 1),
            ("max_bytes_fontes", 1, 9000),
        ):
            valor = getattr(self, nome)
            if type(valor) is not int or not minimo <= valor <= maximo:
                raise ValueError(f"Configuração inválida: {nome}.")
        for nome in ("timeout_segundos", "tempo_maximo_segundos"):
            valor = getattr(self, nome)
            if type(valor) not in (int, float) or not math.isfinite(valor) or valor <= 0:
                raise ValueError(f"Configuração inválida: {nome}.")
        for nome in ("modelo_analista", "modelo_validador"):
            valor = getattr(self, nome)
            if not isinstance(valor, str) or not valor.strip():
                raise ValueError(f"Configuração inválida: {nome}.")


class EstadoExecucao(TypedDict, total=False):
    run_id: str
    modo: str
    caso: str | None
    pergunta: str
    entrada: dict
    configuracao: dict
    inicio_monotonic: float
    iniciado_em: str
    terminado_em: str
    segundos: float
    etapa: str
    agente: str
    status: str
    motivo: str
    consulta: str
    fontes_snapshot: dict
    fontes_omitidas: list
    diagnostico_busca: dict
    redacao: dict
    historico: list
    feedback: dict
    eventos: list
    chamadas_llm: int
    buscas_usadas: int
    revisoes_usadas: int
    tentativas_tecnicas: int
    tokens_entrada: int
    tokens_saida: int
    falha_injetada: bool
    resposta_final: str


class _FalhaExecucao(RuntimeError):
    def __init__(self, codigo, *, limitada=False):
        self.codigo = codigo
        self.limitada = limitada
        super().__init__(codigo)


class SistemaMultiagentes:
    def __init__(self, cliente, busca, *, config=None):
        self.cliente = cliente
        self.busca = busca
        self.config = config or ConfiguracaoSistema()
        grafo = StateGraph(EstadoExecucao)
        nos = {
            "entrada": self._entrada,
            "planejar": self._planejar,
            "buscar": self._buscar,
            "redigir": self._redigir,
            "preparar": self._preparar,
            "validar": self._validar,
            "revisar": self._revisar,
            "finalizar": self._finalizar,
        }
        for nome, funcao in nos.items():
            grafo.add_node(nome, self._proteger(nome, funcao))
        grafo.add_edge(START, "entrada")
        for nome, proximo in (
            ("entrada", "planejar"), ("planejar", "buscar"),
            ("buscar", "redigir"), ("redigir", "preparar"),
            ("preparar", "validar"), ("revisar", "preparar"),
        ):
            grafo.add_conditional_edges(
                nome,
                lambda estado, destino=proximo: (
                    "finalizar" if estado.get("status") != "em_andamento" else destino
                ),
                {proximo: proximo, "finalizar": "finalizar"},
            )
        grafo.add_conditional_edges(
            "validar",
            lambda estado: "revisar" if estado.get("status") == "em_andamento" else "finalizar",
            {"revisar": "revisar", "finalizar": "finalizar"},
        )
        grafo.add_edge("finalizar", END)
        self.grafo = grafo.compile()

    @staticmethod
    def _evento(estado, etapa, agente="orquestrador", **dados):
        estado["eventos"].append(dict(
            numero=len(estado["eventos"]) + 1,
            etapa=etapa, agente=agente, **dados,
        ))

    def _proteger(self, nome, funcao):
        def executar(estado):
            estado = deepcopy(estado)
            estado["etapa"] = nome
            try:
                if nome != "finalizar":
                    self._conferir_tempo(estado)
                return funcao(estado)
            except _FalhaExecucao as erro:
                estado["status"] = "limitada" if erro.limitada else "falha_tecnica"
                estado["motivo"] = erro.codigo
            except Exception as erro:
                # Não registrar str(erro): adaptadores externos podem conter
                # credenciais ou evidências em suas mensagens de exceção.
                estado["status"] = "falha_tecnica"
                estado["motivo"] = "erro_na_etapa"
                self._evento(estado, "erro", tipo=type(erro).__name__)
            self._evento(estado, nome, status=estado["status"], motivo=estado["motivo"])
            return estado
        return executar

    def _conferir_tempo(self, estado):
        restante = self.config.tempo_maximo_segundos - (
            time.monotonic() - estado["inicio_monotonic"]
        )
        if restante <= 0:
            raise _FalhaExecucao("tempo_esgotado")
        return restante

    def _chamar_llm(self, estado, **pedido):
        restante = self._conferir_tempo(estado)
        if estado["chamadas_llm"] >= self.config.max_chamadas_llm:
            raise _FalhaExecucao("orcamento_llm_esgotado")
        # Limite sem cortar texto: a seleção de fontes acontece antes do snapshot. Até multiagentes-v2 o limite
        # contava bytes como tokens; com o prompt v3 (8,4 KB) isso estourava. Agora usa a mesma estimativa de
        # tokens da geração (cl100k_base x 1,25, margem de 512), que também reserva a saída.
        opcoes = pedido["opcoes"]
        try:
            validar_janela_contexto(pedido["mensagens"], max_context_tokens=opcoes.get("num_ctx", 16384),
                                    max_output_tokens=opcoes.get("num_predict", 1800))
        except ContextWindowExceeded:
            raise _FalhaExecucao("contexto_excedido", limitada=True) from None
        estado["chamadas_llm"] += 1
        self._evento(
            estado, "chamada_llm", estado["agente"],
            chamada=estado["chamadas_llm"], modelo=pedido["modelo"],
        )
        resultado = self.cliente.gerar(
            **pedido, timeout=min(self.config.timeout_segundos, restante),
        )
        self._conferir_tempo(estado)
        if not isinstance(resultado, dict) or not isinstance(resultado.get("dados"), dict):
            raise ErroContrato("Retorno do cliente sem objeto de dados.")
        for campo in ("tokens_entrada", "tokens_saida"):
            valor = resultado.get("uso", {}).get(campo, 0)
            if type(valor) is int and valor >= 0:
                estado[campo] += valor
        self._evento(
            estado, "retorno_llm", estado["agente"],
            modelo=resultado.get("modelo", pedido["modelo"]),
            segundos=resultado.get("segundos"),
        )
        return resultado["dados"]

    def _com_tentativa_tecnica(self, estado, funcao):
        while True:
            try:
                return funcao()
            except (ErroContrato, ErroLLM) as erro:
                repetivel = isinstance(erro, ErroContrato) or erro.retryable
                if (
                    not repetivel
                    or estado["tentativas_tecnicas"] >= self.config.max_tentativas_tecnicas
                    or estado["chamadas_llm"] >= self.config.max_chamadas_llm
                ):
                    codigo = "contrato_invalido" if isinstance(erro, ErroContrato) else "llm_indisponivel"
                    raise _FalhaExecucao(codigo) from None
                estado["tentativas_tecnicas"] += 1
                self._evento(
                    estado, "tentativa_tecnica", estado["agente"],
                    tentativa=estado["tentativas_tecnicas"], tipo=type(erro).__name__,
                )

    def _analista(self, estado):
        estado["agente"] = "analista"
        return Analista(
            lambda **pedido: self._chamar_llm(estado, **pedido),
            modelo=self.config.modelo_analista,
        )

    def _entrada(self, estado):
        acao = estado["entrada"]["acao"]
        self._evento(estado, "entrada", acao=acao, sinais=estado["entrada"]["sinais"])
        if acao in RESPOSTAS_ENCAMINHAMENTO:
            entrada = g.ResultadoEntrada(**estado["entrada"])
            resultado = g.verificar_saida(RESPOSTAS_ENCAMINHAMENTO[acao], [], entrada)
            if resultado.aprovada:
                estado["resposta_final"] = resultado.resposta_final
                estado["status"] = "resposta_fixa"
                estado["motivo"] = acao
            else:
                estado["status"] = "limitada"
                estado["motivo"] = "resposta_fixa_bloqueada"
        return estado

    def _planejar(self, estado):
        analista = self._analista(estado)
        plano = self._com_tentativa_tecnica(
            estado, lambda: analista.planejar(estado["pergunta"], estado["entrada"]["acao"]),
        )
        consulta, _ = g.mascarar(plano["argumentos"]["consulta"])
        estado["consulta"] = consulta
        self._evento(estado, "consulta", "analista", consulta=consulta, ferramenta="buscar_evidencias")
        return estado

    def _buscar(self, estado):
        if estado["buscas_usadas"]:
            raise _FalhaExecucao("limite_busca")
        estado["buscas_usadas"] += 1
        recebidas = self.busca.buscar(estado["consulta"])
        if not isinstance(recebidas, list):
            raise _FalhaExecucao("retorno_busca_invalido")
        diagnostico = getattr(self.busca, "diagnostico", None)
        if isinstance(diagnostico, dict):
            # Somente contadores e identidade do corpus entram no rastro. Não
            # copie caminhos, consultas ou campos extras de uma ferramenta.
            seguro = {}
            for nome in ("quantidade_artigos", "dimensao", "max_tokens"):
                valor = diagnostico.get(nome)
                if type(valor) is int and valor >= (0 if nome == "quantidade_artigos" else 1):
                    seguro[nome] = valor
            reutilizado = diagnostico.get("cache_reutilizado")
            if type(reutilizado) is bool:
                seguro["cache_reutilizado"] = reutilizado
            identidade = diagnostico.get("corpus_sha256")
            if isinstance(identidade, str) and re.fullmatch(r"[0-9a-f]{64}", identidade):
                seguro["corpus_sha256"] = identidade
            for nome, padrao in (("modelo", r"[A-Za-z0-9][A-Za-z0-9_./-]{0,255}"),
                                 ("revisao", r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")):
                valor = diagnostico.get(nome)
                if isinstance(valor, str) and re.fullmatch(padrao, valor):
                    seguro[nome] = valor
            if seguro:
                estado["diagnostico_busca"] = seguro
                self._evento(estado, "indice_local", "ferramenta", **seguro)
        # Cópia antes de entregar o contexto aos agentes; nenhuma ordenação
        # posterior poderá mudar o significado de [Fonte N].
        selecionadas, omitidas, tamanho = [], [], 0
        for indice, fonte in enumerate(deepcopy(recebidas), 1):
            if not isinstance(fonte, dict) or not isinstance(fonte.get("conteudo"), str) or not fonte["conteudo"].strip():
                raise _FalhaExecucao("fonte_sem_texto")
            peso = len(json.dumps(fonte, ensure_ascii=False, allow_nan=False).encode("utf-8"))
            if len(selecionadas) >= 6 or tamanho + peso > self.config.max_bytes_fontes:
                omitidas.append(dict(posicao_original=indice, motivo="orcamento_contexto"))
                continue
            selecionadas.append(fonte)
            tamanho += peso
        estado["fontes_snapshot"] = {"fontes": selecionadas, "sha256": _hash(selecionadas)}
        estado["fontes_omitidas"] = omitidas
        self._evento(
            estado, "busca", "ferramenta", fontes=len(selecionadas),
            omitidas=len(omitidas), snapshot_sha256=estado["fontes_snapshot"]["sha256"],
        )
        if not selecionadas:
            estado["status"] = "limitada"
            estado["motivo"] = "contexto_excedido" if omitidas else "evidencia_insuficiente"
        return estado

    @staticmethod
    def _fontes(estado):
        snapshot = estado["fontes_snapshot"]
        if _hash(snapshot["fontes"]) != snapshot["sha256"]:
            raise _FalhaExecucao("fontes_alteradas")
        return deepcopy(snapshot["fontes"])

    def _redigir(self, estado):
        analista = self._analista(estado)
        estado["redacao"] = self._com_tentativa_tecnica(
            estado, lambda: analista.redigir(
                estado["pergunta"], estado["entrada"]["acao"], self._fontes(estado),
            ),
        )
        self._evento(estado, "redacao", "analista", versao=0)
        self._insuficiencia_analista(estado)
        return estado

    @staticmethod
    def _insuficiencia_analista(estado):
        if estado["redacao"]["acao"] == "evidencia_insuficiente":
            estado["historico"].append(dict(
                versao=estado["revisoes_usadas"],
                acao_analista="evidencia_insuficiente",
                rascunho=estado["redacao"]["resposta"],
                candidato=None, guardrails=None,
            ))
            estado["status"] = "limitada"
            estado["motivo"] = "evidencia_insuficiente"

    def _preparar(self, estado):
        original = estado["redacao"]["resposta"]
        candidato = original
        if estado["caso"] == "revisao_controlada" and not estado["historico"]:
            candidato, quantidade = re.subn(r"\[Fonte\s+\d+\]", "[Fonte 99]", candidato, count=1)
            if not quantidade:
                candidato += " [Fonte 99]"
            estado["falha_injetada"] = True
            self._evento(estado, "falha_controlada", tipo="citacao_inexistente", falha_injetada=True)
        # Prompt v3 é revisado pelo validador v3, como na geração (geracao.versao_guardrail): o v3 precisa do
        # tipo, do caminho e do nome de citação das fontes.
        fontes = [
            dict(texto=f["conteudo"], artigo_ref=f.get("artigo_ref"), processo=f.get("processo"),
                 tipo=f.get("fonte"), caminho=f.get("caminho_relativo"), contexto=f.get("contexto"),
                 nome_citacao=f.get("nome_citacao"), situacao=f.get("situacao"),
                 alerta_vigencia=f.get("alerta_vigencia"), alerta_lei_posterior=f.get("alerta_lei_posterior"))
            for f in self._fontes(estado)
        ]
        verificacao = g.verificar_saida(
            candidato, fontes, g.ResultadoEntrada(**estado["entrada"]), versao=VERSAO_PROMPT_JURIDICO,
        )
        estado["historico"].append(dict(
            versao=estado["revisoes_usadas"],
            acao_analista=estado["redacao"]["acao"],
            rascunho=original,
            candidato=verificacao.resposta_final,
            guardrails=dict(aprovada=verificacao.aprovada, alertas=verificacao.alertas),
        ))
        self._evento(
            estado, "guardrails", aprovada=verificacao.aprovada,
            codigos=[a["codigo"] for a in verificacao.alertas],
        )
        return estado

    def _validar(self, estado):
        estado["agente"] = "validador"
        validador = Validador(
            lambda **pedido: self._chamar_llm(estado, **pedido),
            modelo=self.config.modelo_validador,
        )
        versao = estado["historico"][-1]
        feedback = self._com_tentativa_tecnica(
            estado, lambda: validador.validar(
                estado["pergunta"], estado["entrada"]["acao"],
                self._fontes(estado), versao["candidato"], versao["guardrails"]["alertas"],
            ),
        )
        versao["feedback"] = deepcopy(feedback)
        estado["feedback"] = deepcopy(feedback)
        self._evento(estado, "validacao", "validador", decisao=feedback["decisao"], versao=versao["versao"])
        if feedback["decisao"] == "evidencia_insuficiente" or versao["acao_analista"] == "evidencia_insuficiente":
            estado["status"] = "limitada"
            estado["motivo"] = "evidencia_insuficiente"
        elif feedback["decisao"] == "aprovar" and versao["guardrails"]["aprovada"]:
            estado["resposta_final"] = versao["candidato"]
            estado["status"] = "aprovada"
            estado["motivo"] = "controles_aprovados"
        elif estado["revisoes_usadas"] >= self.config.max_revisoes:
            estado["status"] = "limitada"
            estado["motivo"] = "revisao_esgotada"
        else:
            # O Validador não pode sobrepor uma regra determinística bloqueante.
            obrigatorios = []
            for alerta in versao["guardrails"]["alertas"]:
                if alerta["codigo"] in g.BLOQUEANTES:
                    obrigatorios.append(dict(
                        codigo=alerta["codigo"],
                        trecho=alerta.get("frase", ""),
                        fontes=[],
                        correcao_solicitada="Corrija o problema indicado pelo controle: " + alerta["detalhe"],
                    ))
            combinados, vistos = [], set()
            for problema in obrigatorios + estado["feedback"]["problemas"]:
                identidade = _hash(problema)
                if identidade not in vistos:
                    combinados.append(problema)
                    vistos.add(identidade)
            # O histórico guarda o feedback completo do modelo e os alertas.
            # O pedido de revisão mantém o contrato e prioriza os bloqueantes.
            estado["feedback"]["problemas"] = combinados[:MAX_PROBLEMAS]
            estado["feedback"]["decisao"] = "revisar"
            estado["feedback"]["evidencia_suficiente"] = True
        return estado

    def _revisar(self, estado):
        estado["revisoes_usadas"] += 1
        analista = self._analista(estado)
        estado["redacao"] = self._com_tentativa_tecnica(
            estado, lambda: analista.redigir(
                estado["pergunta"], estado["entrada"]["acao"], self._fontes(estado),
                rascunho_anterior=estado["historico"][-1]["candidato"],
                feedback=deepcopy(estado["feedback"]),
            ),
        )
        self._evento(estado, "revisao", "analista", versao=estado["revisoes_usadas"])
        self._insuficiencia_analista(estado)
        return estado

    def _finalizar(self, estado):
        if not estado.get("resposta_final"):
            if estado["status"] == "falha_tecnica":
                estado["resposta_final"] = MENSAGEM_FALHA
            elif estado.get("motivo") in ("evidencia_insuficiente", "contexto_excedido"):
                estado["resposta_final"] = MENSAGEM_INSUFICIENTE
            else:
                estado["resposta_final"] = MENSAGEM_BLOQUEADA
        estado["segundos"] = round(time.monotonic() - estado["inicio_monotonic"], 3)
        estado["terminado_em"] = datetime.now(timezone.utc).isoformat()
        self._evento(estado, "finalizado", status=estado["status"], motivo=estado["motivo"])
        return estado

    def executar(self, pergunta, *, modo="sintetico", caso=None, run_id=None):
        if not isinstance(pergunta, str):
            raise ValueError("A pergunta deve ser um texto.")
        if modo not in ("real", "sintetico", "corpus", "local"):
            raise ValueError("Modo deve ser real, corpus, local ou sintetico.")
        if caso == "revisao_controlada" and modo != "sintetico":
            raise ValueError("Falha controlada só pode ser usada no modo sintetico.")
        run_id = run_id or uuid4().hex
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
            raise ValueError("Identificador de execução inválido.")
        # A pergunta original nunca entra no estado ou nos arquivos de execução.
        entrada = g.verificar_entrada(pergunta)
        estado = EstadoExecucao(
            run_id=run_id, modo=modo, caso=caso,
            pergunta=entrada.pergunta_sanitizada, entrada=asdict(entrada),
            configuracao=asdict(self.config), inicio_monotonic=time.monotonic(),
            iniciado_em=datetime.now(timezone.utc).isoformat(),
            status="em_andamento", motivo="", etapa="entrada", agente="orquestrador",
            historico=[], eventos=[], chamadas_llm=0, buscas_usadas=0,
            revisoes_usadas=0, tentativas_tecnicas=0,
            tokens_entrada=0, tokens_saida=0, falha_injetada=False,
            resposta_final="",
        )
        # O limite do grafo é adicional; os limites de chamadas são explícitos.
        # callbacks=[] sozinho não desativa tracing habilitado por ambiente.
        with tracing_context(enabled=False):
            return self.grafo.invoke(
                estado, config={"recursion_limit": 24, "callbacks": []},
            )
