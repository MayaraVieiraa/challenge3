"""Comparação de três configurações sobre as 50 perguntas jurídicas da curadoria (notebook 05).

Configurações:
  llm_isolado   Qwen3 8B sem fontes (prompt sem as regras que exigem evidências: PROMPT_ISOLADO)
  busca_sem_llm a resposta é o texto dos 3 artigos de lei mais bem ranqueados pela busca híbrida
  rag_hibrido   busca híbrida (3 artigos + 3 decisões) + Qwen3 8B com o prompt jurídico do grupo

Métricas (por resposta):
  correcao       nota do juiz (0–2) contra a referência da curadoria (fonte sugerida + comportamento esperado)
  fundamentacao  nota de fidelidade do juiz (0–2) e se a resposta cita o dispositivo de referência
  aderencia      nota de comportamento do juiz (0–2): segue a ação esperada para a pergunta
  seguranca      sem alerta de segurança dos guardrails de saída (ALERTAS_SEGURANCA)
  recall@3       algum dispositivo de referência entre os 3 artigos de lei recuperados
  latencia       tempo total até a resposta; tempo_inferencia: só a geração da LLM
"""
from __future__ import annotations

import re
import unicodedata

from .prompt_juridico import SYSTEM_PROMPT_LEGAL

CONFIGURACOES = ('llm_isolado', 'busca_sem_llm', 'rag_hibrido')

# Alertas dos guardrails de saída que indicam risco à pessoa (os de citação/fonte medem fundamentação, não segurança).
ALERTAS_SEGURANCA = {'promessa_resultado', 'consulta_individual_sem_ressalva', 'consulta_individual_pede_dados',
                     'dados_pessoais_saida', 'resposta_alem_do_escopo'}

# Variante do prompt do grupo para o LLM sem recuperação: as regras 1, 2, 4, 6 e 8 exigem fontes fornecidas e fariam
# o modelo apenas recusar. Mantém linguagem, citação de dispositivos, segurança, dados pessoais e ordem da resposta.
PROMPT_ISOLADO = """Você é um assistente que explica questões de Direito do Trabalho brasileiro
em linguagem simples, clara e respeitosa, e explica os termos técnicos necessários.

REGRAS:
1. Indique a norma e o dispositivo (artigo, parágrafo, inciso ou alínea) que sustentam cada afirmação jurídica.
2. Não invente referências, decisões, números de processos ou links. Se não souber o dispositivo, diga isso.
3. Diga quando não souber e não prometa resultado de causa.
4. Quando a resposta depender de condições como data de admissão, tipo de contrato ou motivo do desligamento,
   verifique se esses dados foram fornecidos; se faltarem, faça perguntas objetivas antes de concluir.
5. Alerte para prazos de prescrição quando forem pertinentes, sem calcular datas-limite.
6. Quando a pergunta estiver fora do escopo de Direito do Trabalho, avise:
   "Essa não é uma pergunta ligada ao Direito do Trabalho".
7. Dados pessoais: não peça nem repita nomes, CPF ou dados sensíveis sem necessidade.
8. ORDEM DA RESPOSTA: primeiro a "Resposta direta" e depois a "Fundamentação".
"""
assert 'Utilize exclusivamente as evidências' in SYSTEM_PROMPT_LEGAL  # a diferença entre os prompts é deliberada


def _sem_acento(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto or '') if unicodedata.category(c) != 'Mn').lower()


def _artigo(valor):
    """'Art. 7º' → '7'; 'art. 58-A' → '58-A'; 'Art.194' → '194'."""
    m = re.search(r'(\d+)\s*[ºo°]?\s*(-\s*[A-Za-z])?', valor or '')
    return (m.group(1) + (m.group(2) or '').replace(' ', '').upper()) if m else None


def norma_do_caminho(caminho):
    """Chave da norma a partir do caminho do arquivo da base de legislação."""
    c = (caminho or '').lower()
    if 'consolidacao-das-leis-do-trabalho' in c:
        return 'clt'
    if 'constituicao' in c:
        return 'cf'
    if 'codigo-de-processo-civil' in c:
        return 'cpc'
    if 'codigo-civil' in c:
        return 'cc'
    m = re.search(r'lcp-(\d+)', c)
    if m:
        return f'lc-{m.group(1)}'
    m = re.search(r'lei-(\d+)', c)
    if m:
        return f'lei-{m.group(1)}'
    return None


_NORMA = [(r'\bclt\b', lambda m: 'clt'), (r'\bcf\b|constitui', lambda m: 'cf'), (r'\badct\b', lambda m: 'cf-adct'),
          (r'\bcpc\b', lambda m: 'cpc'), (r'\blc\s*(\d+)', lambda m: f'lc-{m.group(1)}'),
          (r'\blei\s*(?:complementar\s*)?(\d[\d.]*)', lambda m: f'lei-{m.group(1).replace(".", "")}')]


def referencias(texto):
    """Dispositivos de lei citados na fonte sugerida pela curadoria: lista de (norma, artigo).

    'CLT arts. 130 e 134' → [('clt','130'), ('clt','134')]; 'Lei 8.036/1990, art. 18 (...) e art. 20' →
    [('lei-8036','18'), ('lei-8036','20')]; norma sem artigo → (norma, None). Súmulas, NRs, ADI e textos sem norma
    são ignorados (não estão na base de legislação).
    """
    saida = []
    for trecho in re.split(r';', texto or ''):
        t = _sem_acento(re.sub(r'\([^)]*\)', ' ', trecho))   # descarta explicações entre parênteses
        norma = None
        for padrao, chave in _NORMA:
            m = re.search(padrao, t)
            if m:
                norma = chave(m)
                break
        if norma is None or norma == 'cf-adct':
            continue
        artigos = []
        for bloco in re.finditer(r'\barts?\.?\s*((?:\d+[ºo]?(?:-[a-z])?(?:\s*,\s*|\s+e\s+|\s+a\s+)?)+)', t):
            artigos += [_artigo(a) for a in re.findall(r'\d+[ºo]?(?:-[a-z])?', bloco.group(1))]
        if artigos:
            saida += [(norma, a) for a in artigos if a]
        elif not re.search(r'\bsumula|\bnr-|\badi\b', t):
            saida.append((norma, None))
    return list(dict.fromkeys(saida))


def recall_em_3(refs, fontes_legislacao):
    """1 se algum dos 3 primeiros artigos recuperados corresponde a uma referência; None se não há referência."""
    if not refs:
        return None
    recuperados = {(norma_do_caminho(f.get('caminho_relativo')), _artigo(f.get('artigo_ref'))) for f in fontes_legislacao[:3]}
    normas = {n for n, _ in recuperados}
    return int(any((n, a) in recuperados if a else n in normas for n, a in refs))


def cita_referencia(resposta, refs):
    """1 se a resposta menciona algum artigo de referência (número do artigo; a norma não é conferida)."""
    if not refs:
        return None
    texto = _sem_acento(resposta)
    artigos = {a.lower() for _, a in refs if a}
    if not artigos:
        return None
    citados = {(m.group(1) + (m.group(2) or '')).lower() for m in re.finditer(r'\bart(?:igo)?s?\.?\s*(\d+)[ºo°]?(-[a-z])?\b', texto)}
    return int(bool(artigos & citados))


def resposta_busca(fontes_legislacao):
    """Resposta da configuração sem LLM: os 3 artigos de lei mais bem ranqueados, com a referência."""
    partes = []
    for i, f in enumerate(fontes_legislacao[:3], 1):
        # Rótulo legível da norma: o nome do arquivo (ex.: 'clt-del-5452-1943') casava com a regra de telefone.
        norma = (norma_do_caminho(f.get('caminho_relativo')) or 'norma').upper().replace('-', ' ')
        texto = re.sub(r'^\s*\[[^\]]*\]\s*', '', f.get('conteudo') or '')   # cabeçalho com o caminho do arquivo
        partes.append(f"[Fonte {i}] {norma}, {f.get('artigo_ref') or ''}\n{texto}".strip())
    return '\n\n'.join(partes)


def seguro(alertas):
    """1 se nenhum alerta de segurança foi disparado pelos guardrails de saída."""
    return int(not ({a['codigo'] for a in alertas} & ALERTAS_SEGURANCA))
