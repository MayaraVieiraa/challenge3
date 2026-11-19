"""Módulo de Roteamento Semântico e Extração de Fatos do Caso (Stracting / Routing / Extraction)."""
from typing import Tuple, Dict, Any, Optional
import re
from src.agente.schemas import FatosCaso


class RouterEExtrator:
    """Roteia a intenção do usuário e extrai entidades do relato trabalhista (Stracting)."""

    PADROES_SALARIO = [
        r'(?:r\$\s*|sal[aá]rio\s+(?:de\s+)?(?:r\$\s*)?)([\d\.,]+)',
        r'([\d\.,]+)\s*(?:reais|por\s+m[eê]s)'
    ]

    PADROES_DATA = r'(\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b)'

    @classmethod
    def extrair_fatos(cls, texto: str) -> FatosCaso:
        """Extração estruturada de fatos do caso a partir de linguagem natural (Stracting)."""
        texto_norm = texto.lower()

        # 1. Extração de Salário
        salario: Optional[float] = None
        for padrao in cls.PADROES_SALARIO:
            match = re.search(padrao, texto_norm)
            if match:
                raw_val = match.group(1).replace('.', '').replace(',', '.')
                try:
                    val = float(raw_val)
                    if 100 <= val <= 500000:
                        salario = val
                        break
                except ValueError:
                    pass

        # 2. Extração de Datas
        datas = re.findall(cls.PADROES_DATA, texto)
        data_admissao = datas[0] if len(datas) >= 1 else None
        data_demissao = datas[1] if len(datas) >= 2 else None

        # 3. Extração do Motivo da Rescisão
        motivo = None
        if 'sem justa causa' in texto_norm or 'fui demitido' in texto_norm or 'me mandaram embora' in texto_norm:
            motivo = 'sem_justa_causa'
        elif 'com justa causa' in texto_norm or 'por justa causa' in texto_norm:
            motivo = 'justa_causa'
        elif 'pedi demiss' in texto_norm or 'pedir demiss' in texto_norm or 'pedi para sair' in texto_norm:
            motivo = 'pedido_demissao'
        elif 'rescisão indireta' in texto_norm or 'rescisao indireta' in texto_norm:
            motivo = 'rescisao_indireta'

        # 4. Sinais adicionais
        horas_extras = any(term in texto_norm for term in ['hora extra', 'horas extras', 'trabalhava a mais', 'sobrejornada'])
        ferias_vencidas = any(term in texto_norm for term in ['férias vencidas', 'ferias vencidas', 'nunca tirei férias', 'sem tirar férias'])

        # 5. Pedidos identificados
        pedidos = []
        if any(t in texto_norm for t in ['aviso prévio', 'aviso previo']):
            pedidos.append('aviso_previo')
        if 'fgts' in texto_norm or 'fundo de garantia' in texto_norm:
            pedidos.append('fgts')
        if any(t in texto_norm for t in ['13º', 'décimo terceiro', 'decimo terceiro']):
            pedidos.append('decimo_terceiro')
        if 'férias' in texto_norm or 'ferias' in texto_norm:
            pedidos.append('ferias')

        return FatosCaso(
            salario=salario,
            data_admissao=data_admissao,
            data_demissao=data_demissao,
            motivo_rescisao=motivo,
            horas_extras_habituais=horas_extras if horas_extras else None,
            tem_ferias_vencidas=ferias_vencidas if ferias_vencidas else None,
            pedidos_mencionados=pedidos
        )

    @classmethod
    def rotear_intencao(cls, texto: str) -> Tuple[str, Optional[str]]:
        """Roteia a pergunta para a melhor estratégia/ferramenta (Intent Routing).

        Retorna:
            (intencao, justificativa)
            intencao: 'CALCULO', 'PRESCRICAO', 'CONSULTA_JURIDICA', 'TRIAGEM'
        """
        texto_norm = texto.lower()

        # Roteamento 1: Cálculo rescisório / valores
        termos_calculo = ['quanto vou receber', 'quanto tenho direito', 'calcular minha rescisão', 'calcular rescisao',
                          'fazer o cálculo', 'fazer calculo', 'simular rescisão', 'simular rescisao', 'valor a receber']
        if any(t in texto_norm for t in termos_calculo):
            return ('CALCULO', 'Detectada intenção explícita de cálculo de verbas rescisórias.')

        # Roteamento 2: Prescrição e prazos para processar
        termos_prescricao = ['quanto tempo tenho para entrar', 'prazo para entrar com processo', 'prazo para processar',
                             'prescrição', 'prescricao', 'perdi o prazo', 'posso processar depois de']
        if any(t in texto_norm for t in termos_prescricao):
            return ('PRESCRICAO', 'Detectada dúvida sobre prazo prescricional para ajuizamento de ação.')

        # Roteamento 3: Triagem / fora de escopo / institucional
        termos_triagem = ['qual o status do meu processo', 'como você foi criado', 'receita de bolo', 'direito penal']
        if any(t in texto_norm for t in termos_triagem):
            return ('TRIAGEM', 'Encaminhado para resposta determinística de triagem.')

        # Roteamento padrão: Consulta jurídica rica (legislação + jurisprudência)
        return ('CONSULTA_JURIDICA', 'Consulta interpretativa de normas e precedentes trabalhistas.')
