"""Extração estruturada de fatos explícitos e classificação determinística de intenção."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import re
import unicodedata


_PADRAO_DATA = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
_PADRAO_SALARIO = re.compile(
    r"(?:\br\$\s*|\bsal[aá]rio(?:\s+(?:mensal|bruto))?(?:\s+(?:de|é|:))?\s*)"
    r"(\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
    r"|\b(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?)\s*(?:reais|por\s+m[eê]s)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FatosTrabalhistas:
    salario_mensal: float | None = None
    data_admissao: str | None = None
    data_demissao: str | None = None
    motivo_rescisao: str | None = None
    horas_extras_mencionadas: bool | None = None
    ferias_vencidas_mencionadas: bool | None = None
    pedidos_mencionados: tuple[str, ...] = ()

    def para_dict(self) -> dict:
        dados = asdict(self)
        dados["pedidos_mencionados"] = list(self.pedidos_mencionados)
        return dados


@dataclass(frozen=True)
class AnaliseIntencao:
    intencao: str
    justificativa: str


def _normalizar(texto: str) -> str:
    sem_acentos = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in sem_acentos if unicodedata.category(c) != "Mn")


def _converter_salario(valor: str) -> float | None:
    valor = valor.strip().replace(" ", "")
    if "," in valor:
        valor = valor.replace(".", "").replace(",", ".")
    elif valor.count(".") > 1 or (valor.count(".") == 1 and len(valor.rsplit(".", 1)[1]) == 3):
        valor = valor.replace(".", "")
    try:
        salario = float(valor)
    except ValueError:
        return None
    return salario if 100 <= salario <= 500_000 else None


def _converter_data(valor: str) -> str | None:
    for formato in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(valor, formato).date().isoformat()
        except ValueError:
            continue
    return None


def _tipo_data(texto: str, inicio: int, fim: int) -> str | None:
    padroes = {
        "admissao": re.compile(r"\b(admit|admiss|contrat|comecei|inicio|entrei|registr)\w*"),
        "demissao": re.compile(r"\b(demit|dispens|rescis|sa[ií]|encer|deslig|demiss)\w*"),
    }
    distancias = {}
    distancias_anteriores = {}
    for tipo, padrao in padroes.items():
        matches = list(padrao.finditer(texto))
        distancias_anteriores[tipo] = min(
            (inicio - match.end() for match in matches if match.end() <= inicio),
            default=None,
        )
        distancias[tipo] = min((
            inicio - match.end() if match.end() <= inicio
            else match.start() - fim if match.start() >= fim
            else 0
            for match in matches
        ), default=None)
    if any(distancia is not None and distancia <= 60 for distancia in distancias_anteriores.values()):
        distancias = distancias_anteriores
    disponiveis = {tipo: distancia for tipo, distancia in distancias.items() if distancia is not None}
    if not disponiveis:
        return None
    tipo, distancia = min(disponiveis.items(), key=lambda item: item[1])
    outro = "demissao" if tipo == "admissao" else "admissao"
    if distancia > 60 or distancias[outro] == distancia:
        return None
    return tipo


def extrair_fatos(texto: str) -> FatosTrabalhistas:
    """Extrai apenas valores literais reconhecidos; não calcula nem completa fatos ausentes."""
    normalizado = _normalizar(texto)

    salario = None
    for match in _PADRAO_SALARIO.finditer(texto):
        candidato = match.group(1) or match.group(2)
        if candidato:
            salario = _converter_salario(candidato)
            if salario is not None:
                break

    datas = []
    for match in _PADRAO_DATA.finditer(normalizado):
        data = _converter_data(match.group())
        if data:
            datas.append((_tipo_data(normalizado, match.start(), match.end()), data))

    data_admissao = next((data for tipo, data in datas if tipo == "admissao"), None)
    data_demissao = next((data for tipo, data in datas if tipo == "demissao"), None)
    datas_sem_rotulo = [data for tipo, data in datas if tipo is None]
    if not data_admissao and not data_demissao and len(datas_sem_rotulo) == 1:
        if re.search(r"\b(admit|admiss|contrat|comecei|inicio|entrei|registr)", normalizado):
            data_admissao = datas_sem_rotulo[0]
        elif re.search(r"\b(demit|dispens|rescis|sa[ií]|encer|deslig|demiss)", normalizado):
            data_demissao = datas_sem_rotulo[0]
    elif not data_admissao and not data_demissao and len(datas_sem_rotulo) >= 2:
        if re.search(r"\b(admit|admiss|contrat|comecei|inicio|entrei|registr)", normalizado) and re.search(
            r"\b(demit|dispens|rescis|sa[ií]|encer|deslig|demiss)", normalizado
        ):
            data_admissao, data_demissao = datas_sem_rotulo[:2]

    if "acordo mutuo" in normalizado or "484-a" in normalizado:
        motivo = "acordo_mutuo"
    elif "sem justa causa" in normalizado:
        motivo = "sem_justa_causa"
    elif "com justa causa" in normalizado or "por justa causa" in normalizado:
        motivo = "justa_causa"
    elif "rescisao indireta" in normalizado:
        motivo = "rescisao_indireta"
    elif "pedi demiss" in normalizado or "pedir demiss" in normalizado or "pedi para sair" in normalizado:
        motivo = "pedido_demissao"
    else:
        motivo = None

    menciona_horas = bool(re.search(r"\b(horas? extras?|sobrejornada|trabalhava a mais)\b", normalizado))
    horas_negadas = bool(re.search(r"\b(nao|nunca)\s+(?:fazia|faco|fiz|trabalhava)\b.{0,30}\b(horas? extras?|sobrejornada)\b", normalizado))
    horas = False if horas_negadas else (True if menciona_horas else None)

    menciona_ferias = "ferias vencidas" in normalizado or "nunca tirei ferias" in normalizado or "sem tirar ferias" in normalizado
    ferias_negadas = bool(re.search(r"\b(nao|nunca)\s+(?:tenho|possuo|tive)\b.{0,30}\bferias vencidas\b", normalizado))
    ferias = False if ferias_negadas else (True if menciona_ferias else None)

    pedidos = []
    if "aviso previo" in normalizado:
        pedidos.append("aviso_previo")
    if "fgts" in normalizado or "fundo de garantia" in normalizado:
        pedidos.append("fgts")
    if "13º" in texto or "decimo terceiro" in normalizado:
        pedidos.append("decimo_terceiro")
    if "ferias" in normalizado:
        pedidos.append("ferias")

    return FatosTrabalhistas(
        salario_mensal=salario,
        data_admissao=data_admissao,
        data_demissao=data_demissao,
        motivo_rescisao=motivo,
        horas_extras_mencionadas=horas,
        ferias_vencidas_mencionadas=ferias,
        pedidos_mencionados=tuple(pedidos),
    )


def rotear_intencao(texto: str) -> AnaliseIntencao:
    """Classifica a intenção por regras explícitas; não substitui os guardrails de entrada."""
    normalizado = _normalizar(texto)
    termos_calculo = (
        "quanto vou receber", "quanto receberei", "quanto tenho direito", "calcular minha rescisao",
        "calcular rescisao", "fazer o calculo", "simular rescisao", "valor a receber", "quais verbas",
        "tenho direito ao aviso", "tenho direito ao 13", "tenho direito a receber",
    )
    tem_salario = bool(re.search(r"(?:\br\$\s*|\bsal[aá]rio\b|\b[\d.,]+\s*(?:reais|por\s+m[eê]s))", texto, re.IGNORECASE))
    tem_rescisao = any(t in normalizado for t in ("demiss", "demitid", "rescis", "acordo", "aviso previo", "fgts"))
    if any(termo in normalizado for termo in termos_calculo) or (tem_salario and tem_rescisao):
        return AnaliseIntencao("CALCULO", "Pergunta sobre cálculo ou verbas rescisórias; nenhum cálculo automático é executado.")

    termos_prescricao = (
        "quanto tempo tenho para entrar", "prazo para entrar com processo", "prazo para processar",
        "prescricao", "perdi o prazo", "posso processar depois de",
    )
    if any(termo in normalizado for termo in termos_prescricao):
        return AnaliseIntencao("PRESCRICAO", "Pergunta sobre prazo prescricional.")

    termos_triagem = ("qual o status do meu processo", "como voce foi criado", "receita de bolo", "direito penal")
    if any(termo in normalizado for termo in termos_triagem):
        return AnaliseIntencao("TRIAGEM", "Pergunta de triagem ou fora do escopo de consulta jurídica.")

    return AnaliseIntencao("CONSULTA_JURIDICA", "Consulta interpretativa sobre direitos ou normas trabalhistas.")
