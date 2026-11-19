"""Modelos Pydantic para Saída Estruturada (Structured Output), Extração e Tool Calling."""
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field


class FatosCaso(BaseModel):
    """Extração estruturada de fatos e variáveis trabalhistas a partir do relato livre (Stracting/Extraction)."""
    salario: Optional[float] = Field(default=None, description="Salário mensal bruto em reais, se mencionado.")
    data_admissao: Optional[str] = Field(default=None, description="Data de início do vínculo empregatício.")
    data_demissao: Optional[str] = Field(default=None, description="Data do término do contrato / demissão.")
    motivo_rescisao: Optional[str] = Field(default=None, description="Motivo (ex.: sem justa causa, pedido de demissão, justa causa).")
    horas_extras_habituais: Optional[bool] = Field(default=None, description="Se há relato de horas extras habituais ou jornada excessiva.")
    tem_ferias_vencidas: Optional[bool] = Field(default=None, description="Se possui períodos de férias vencidas pendentes de gozo/pagamento.")
    pedidos_mencionados: List[str] = Field(default_factory=list, description="Lista de direitos ou pedidos reclamados (ex.: aviso prévio, FGTS).")


class CalculoRescisaoInput(BaseModel):
    """Parâmetros de entrada para cálculo determinístico de verbas rescisórias."""
    salario_base: float = Field(..., description="Valor do salário base mensal em reais.")
    meses_trabalhados: int = Field(..., ge=0, description="Meses trabalhados no último ano contratual para cálculo proporcional.")
    tipo_rescisao: Literal[
        "sem_justa_causa", "pedido_demissao", "justa_causa", "rescisao_indireta", "acordo_mutuo"
    ] = Field(default="sem_justa_causa", description="Modalidade de encerramento do contrato de trabalho.")
    dias_saldo_salario: int = Field(default=0, ge=0, le=31, description="Dias trabalhados no mês da demissão.")
    tem_ferias_vencidas: bool = Field(default=False, description="Se há férias vencidas não gozadas.")


class CalculoRescisaoOutput(BaseModel):
    """Resultado determinístico do cálculo de verbas rescisórias (evita alucinação matemática da LLM)."""
    saldo_salario: float
    aviso_previo: float
    decimo_terceiro_proporcional: float
    ferias_proporcionais_mais_terco: float
    ferias_vencidas_mais_terco: float
    multa_fgts_estimada: float
    total_bruto_estimado: float
    fundamentacao: List[str]


class VerificarPrescricaoInput(BaseModel):
    """Parâmetros para verificação do prazo prescricional trabalhista."""
    data_demissao: str = Field(..., description="Data do término do contrato no formato AAAA-MM-DD ou DD/MM/AAAA.")
    data_ajuizamento: Optional[str] = Field(default=None, description="Data prevista ou efetiva da ação trabalhista.")


class VerificarPrescricaoOutput(BaseModel):
    """Resultado da análise de prescrição bienal e quinquenal."""
    prazo_bienal_limite: str
    prescrito_bienal: bool
    data_limite_quinquenal: str
    dias_restantes_estimados: Optional[int]
    fundamentacao: str


class RespostaEstruturada(BaseModel):
    """Formato de Saída Estruturada (Structured Output) obrigatório gerado pelo Agente."""
    resposta_direta: str = Field(..., description="Resposta objetiva e clara em 1 a 3 parágrafos.")
    fundamentacao_legal: List[str] = Field(default_factory=list, description="Lista de artigos de lei aplicados (ex.: 'Art. 477 da CLT').")
    jurisprudencia_aplicada: List[str] = Field(default_factory=list, description="Súmulas, Orientações Jurisprudenciais ou teses citadas.")
    fatos_extraidos: Optional[FatosCaso] = Field(default=None, description="Fatos e variáveis extraídas do caso (stracting).")
    calculos: Optional[Dict[str, Any]] = Field(default=None, description="Valores ou prazos calculados pelas ferramentas, se aplicável.")
    orientacao_ao_trabalhador: str = Field(..., description="Explicação em linguagem simples sobre como agir ou o que conferir.")
    alertas_e_ressalvas: List[str] = Field(default_factory=list, description="Ressalvas, limites da análise e documentos necessários.")
    precisa_advogado: bool = Field(default=False, description="Se a situação exige intervenção ou ajuizamento formal de ação.")
    aviso_legal: str = Field(
        default="Esta resposta tem caráter estritamente informativo e educativo com base na legislação e jurisprudência, não substituindo a consultoria de um advogado ou sindicato.",
        description="Aviso de isenção legal obrigatório."
    )
