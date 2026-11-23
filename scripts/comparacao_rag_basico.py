"""Notebook 05: variantes de RAG com busca básica (só semântica + Qwen3 8B) nas mesmas 40 perguntas JUS.

Compara com as três configurações de `comparacao_kaggle.py` sem refazê-las. As variantes mudam só a recuperação:
  rag_basico      busca semântica com BGE-M3, sem lexical, sem RRF entre buscas e sem reranker; 5 artigos de lei
  rag_basico_jur  a mesma busca semântica, com a entrega do RAG híbrido: 3 artigos de lei + 3 decisões
Em ambas: mesmo LLM, mesmas opções e mesmo prompt do RAG híbrido (o pedido original é reaproveitado e só as fontes
mudam), mesmo juiz (Gemma 3 27B), mesma rubrica e mesma referência da curadoria.

Etapas (variante rag_basico por padrão; --variante rag_basico_jur para a outra):
  python scripts/comparacao_rag_basico.py buscar [--variante V]   busca local → pedidos de geração → kernel
  python scripts/comparacao_rag_basico.py julgar [--variante V]   baixa a geração → pedidos do juiz → kernel
  python scripts/comparacao_rag_basico.py importar                grava as métricas de todas as configurações
                                                                  (variantes ainda sem resultado ficam sem notas)
Depois de buscar/julgar: kaggle datasets create -p <dataset> e kaggle kernels push -p <kernel> (caminho do Windows).
Use --sem-download para reaproveitar saídas já baixadas.
"""
from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from src.integracao import comparacao as cmp
from src.integracao.geracao import MODELO_GERACAO, OPCOES_GERACAO, _hash, fonte_para_prompt, revisar
from src.integracao.prompt_juridico import build_rag_prompt
from src.integracao.context_window import ContextWindowExceeded
from src.integracao.juiz import pedido_kaggle, interpretar, TITULO_FONTES, SISTEMA_JUIZ_COMPARACAO

USUARIO = 'laisapaiva93'
BASE = ROOT / 'output/kaggle/comparacao'
GERACAO = ROOT / 'output/kaggle/geracao'
RELATORIOS = ROOT / 'reports/integracao/comparacao'
MODELO_JUIZ = 'gemma3:27b'
# Cada variante: busca (Configuracao), pasta e nomes no Kaggle. A busca 'basica_jur' entrega 3 + 3 como a híbrida.
VARIANTES = {
    'rag_basico': dict(busca='basica', pasta='rag_basico', pasta_juiz='juiz_basico',
                       kernel='lexia-comparacao-rag-basico', kernel_juiz='lexia-comparacao-juiz-basico',
                       config=dict(fontes=('legislacao',), usar_lexical=False, usar_semantica=True, usar_reranker=False,
                                   cota_por_fonte=50, top_k=5, entrega_por_fonte=None)),
    'rag_basico_jur': dict(busca='basica_jur', pasta='rag_basico_jur', pasta_juiz='juiz_basico_jur',
                           kernel='lexia-comparacao-rag-basico-jur', kernel_juiz='lexia-comparacao-juiz-basico-jur',
                           config=dict(fontes=('legislacao', 'jurisprudencia'), usar_lexical=False, usar_semantica=True,
                                       usar_reranker=False, cota_por_fonte=50,
                                       entrega_por_fonte={'legislacao': 3, 'jurisprudencia': 3})),
}
CONFIGURACOES = cmp.CONFIGURACOES + tuple(VARIANTES)


def variante():
    nome = sys.argv[sys.argv.index('--variante') + 1] if '--variante' in sys.argv else 'rag_basico'
    return nome, VARIANTES[nome]
MARCA_REF = 'RESPOSTA DE REFERÊNCIA (curadoria):\n'
MARCA_RESPOSTA = '\n\nRESPOSTA A AVALIAR:'


def jsonl(caminho):
    return [json.loads(l) for l in Path(caminho).read_text(encoding='utf-8').splitlines() if l.strip()]


def gravar(pedidos, destino):
    (destino / 'dataset').mkdir(parents=True, exist_ok=True)
    with (destino / 'dataset/pedidos.jsonl').open('w', encoding='utf-8', newline='\n') as f:
        for p in pedidos:
            f.write(json.dumps(p, ensure_ascii=False) + '\n')


def kernel(nome, dataset, destino):
    (destino / 'kernel').mkdir(parents=True, exist_ok=True)
    (destino / 'kernel/kernel-metadata.json').write_text(json.dumps(dict(
        id=f'{USUARIO}/{nome}', title=nome, code_file='gerar_respostas.py', language='python', kernel_type='script',
        is_private=True, enable_gpu=True, enable_tpu=False, enable_internet=True, machine_shape='NvidiaTeslaT4',
        dataset_sources=[f'{USUARIO}/{dataset}'], competition_sources=[], kernel_sources=[], model_sources=[]), indent=2),
        encoding='utf-8')
    (destino / 'kernel/gerar_respostas.py').write_text((ROOT / 'scripts/kaggle_gerar_respostas.py').read_text(encoding='utf-8'),
                                                      encoding='utf-8')
    (destino / 'dataset/dataset-metadata.json').write_text(json.dumps(dict(
        title=dataset, id=f'{USUARIO}/{dataset}', licenses=[dict(name='unknown')],
        description='Pedidos privados da comparação do LexIA (notebook 05, RAG básico). Não redistribuir.'), indent=2),
        encoding='utf-8')


def baixar_kernel(kernel_id, destino):
    destino.mkdir(parents=True, exist_ok=True)
    if '--sem-download' not in sys.argv:
        subprocess.run(['kaggle', 'kernels', 'output', kernel_id, '-p', str(destino), '-o'], check=True)
    arquivo = destino / 'respostas.jsonl'
    if not arquivo.exists():   # kernel ainda em execução
        print('sem respostas ainda:', kernel_id)
        return {}
    return {r['pergunta_id']: r for r in jsonl(arquivo)}


def pedidos_juiz_originais():
    """Os 120 pedidos de julgamento da comparação original (dataset privado), com a referência da curadoria."""
    arquivo = BASE / 'juiz/dataset/pedidos.jsonl'
    if not arquivo.exists():
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['kaggle', 'datasets', 'download', f'{USUARIO}/lexia-comparacao-juiz-pedidos', '-p',
                        str(arquivo.parent), '--unzip'], check=True)
    return {p['pergunta_id']: p for p in jsonl(arquivo)}


def conjunto():
    """As 40 perguntas JUS que foram à LLM: pedido de geração do RAG híbrido e referência da curadoria."""
    juiz = pedidos_juiz_originais()
    geracao = {p['pergunta_id']: p for p in jsonl(GERACAO / 'dataset/pedidos.jsonl')}
    itens = []
    for jid, pj in juiz.items():
        config, qid = jid.split('|', 1)
        if config != 'rag_hibrido':
            continue
        usuario = pj['mensagens'][1]['content']
        referencia = usuario.split(MARCA_REF, 1)[1].split(MARCA_RESPOSTA, 1)[0]
        sugerida = referencia.split('\n', 1)[0].removeprefix('Fonte jurídica sugerida pela curadoria: ')
        itens.append(dict(pedido=geracao[qid], referencia_texto=referencia, referencias=cmp.referencias(sugerida),
                          pedido_juiz_hibrido=pj))
    return sorted(itens, key=lambda i: i['pedido']['pergunta_id'])


def mensagens_com_fontes(pedido, fontes):
    """Remonta o prompt do RAG híbrido trocando só as fontes (o restante do texto do usuário é mantido).

    A geração do RAG híbrido foi feita em texto livre, antes da saída estruturada em JSON (INSTRUCAO_SAIDA_ESTRUTURADA
    e FORMATO_SAIDA); o RAG básico segue o mesmo formato para que só a recuperação mude.
    """
    original = pedido['mensagens']
    if pedido['pedido_sha256'] != _hash(MODELO_GERACAO, OPCOES_GERACAO, original):
        raise RuntimeError(f'o pedido de {pedido["pergunta_id"]} não tem o formato esperado (modelo, opções e mensagens)')
    sistema, usuario = build_rag_prompt(pedido['pergunta_sanitizada'], pedido['fontes'])
    if original[0]['content'] != sistema or not original[1]['content'].startswith(usuario):
        raise RuntimeError(f'o prompt de {pedido["pergunta_id"]} não é reproduzível com o código atual')
    sufixo = original[1]['content'][len(usuario):]
    sistema_novo, usuario_novo = build_rag_prompt(pedido['pergunta_sanitizada'], fontes)
    return [dict(role='system', content=sistema_novo), dict(role='user', content=usuario_novo + sufixo)]


def buscar():
    from src.storage.pgvector_store import load_database_url
    from src.integracao.recuperacao import Recuperador, configuracao_duas_bases
    nome, v = variante()
    config = configuracao_duas_bases(**v['config'])   # medido antes das 3 bases
    recuperador = Recuperador(load_database_url(ROOT / '.env.pgvector.local'), device='cpu', carregar_reranker=False)
    pedidos = []
    for i, item in enumerate(conjunto(), 1):
        p = item['pedido']
        entregues, diag = recuperador.buscar(p['pergunta_sanitizada'], config)
        fontes = [fonte_para_prompt(u) for u in entregues]
        mensagens = mensagens_com_fontes(p, fontes)
        pedidos.append(dict(pergunta_id=p['pergunta_id'], precisa_llm=True, acao=p['acao'],
                            pergunta_sanitizada=p['pergunta_sanitizada'], fontes=fontes, mensagens=mensagens,
                            modelo=MODELO_GERACAO, opcoes=OPCOES_GERACAO, think=False,
                            segundos_recuperacao=round(diag['segundos'], 1),
                            pedido_sha256=_hash(MODELO_GERACAO, OPCOES_GERACAO, mensagens)))
        print(f'{i:2d} {p["pergunta_id"]} {diag["segundos"]:.1f} s',
              [f.get('artigo_ref') or f.get('tribunal') for f in fontes], flush=True)
    destino = BASE / v['pasta']
    gravar(pedidos, destino)
    kernel(v['kernel'], v['kernel'] + '-pedidos', destino)
    print(len(pedidos), f'pedidos de {nome} →', destino.relative_to(ROOT))


def julgar():
    nome, v = variante()
    respostas = baixar_kernel(f'{USUARIO}/{v["kernel"]}', BASE / v['pasta'] / 'resultados')
    gerados = {p['pergunta_id']: p for p in jsonl(BASE / v['pasta'] / 'dataset/pedidos.jsonl')}
    pedidos = []
    for item in conjunto():
        p = item['pedido']
        # Confere que o código atual monta o mesmo pedido de julgamento da comparação original.
        refeito = pedido_kaggle(f'rag_hibrido|{p["pergunta_id"]}', p['pergunta_sanitizada'], p['acao'], p['fontes'],
                                item['pedido_juiz_hibrido']['mensagens'][1]['content'].split(MARCA_RESPOSTA + '\n', 1)[1],
                                item['referencia_texto'], modelo=MODELO_JUIZ, titulo_fontes=TITULO_FONTES,
                                sistema=SISTEMA_JUIZ_COMPARACAO)
        if refeito['mensagens'] != item['pedido_juiz_hibrido']['mensagens']:
            raise RuntimeError(f'o pedido do juiz de {p["pergunta_id"]} mudou em relação à comparação original')
        g, r = gerados[p['pergunta_id']], respostas.get(p['pergunta_id'])
        if not r or r.get('pedido_sha256') != g['pedido_sha256']:
            print('sem resposta válida:', p['pergunta_id'])
            continue
        argumentos = (f'{nome}|{p["pergunta_id"]}', p['pergunta_sanitizada'], p['acao'], g['fontes'], r['resposta'],
                      item['referencia_texto'])
        opcoes = dict(modelo=MODELO_JUIZ, titulo_fontes=TITULO_FONTES, sistema=SISTEMA_JUIZ_COMPARACAO)
        try:
            pedido = pedido_kaggle(*argumentos, **opcoes)
        except ContextWindowExceeded as erro:
            pedido = pedido_acima_da_estimativa(argumentos, opcoes, erro)
        pedidos.append(dict(pedido, config=nome))
    destino = BASE / v['pasta_juiz']
    gravar(pedidos, destino)
    kernel(v['kernel_juiz'], v['kernel_juiz'] + '-pedidos', destino)
    print(len(pedidos), f'julgamentos de {nome} →', destino.relative_to(ROOT))


def pedido_acima_da_estimativa(argumentos, opcoes, erro):
    """Aceita um pedido do juiz recusado só pelo fator de segurança da estimativa de contexto, sem truncar fontes.

    A estimativa usa cl100k_base × 1,25. Nos 120 julgamentos originais, os tokens reais do Gemma 3 ficaram entre
    0,90 e 0,98 da contagem cl100k bruta. O pedido é aceito se a contagem bruta (sem o fator), somada à saída máxima
    e à margem, couber no num_ctx; caso contrário, o erro original é mantido.
    """
    orcamento = erro.budget
    total = orcamento.raw_estimated_tokens + orcamento.max_output_tokens + orcamento.safety_tokens
    if total > orcamento.max_context_tokens:
        raise erro
    from unittest import mock
    from src.integracao import juiz
    with mock.patch.object(juiz, 'validar_janela_contexto', lambda *a, **k: orcamento):
        pedido = pedido_kaggle(*argumentos, **opcoes)
    pedido['janela_contexto'] = dict(orcamento.para_dict(), aceito_pela_contagem_bruta=True)
    print(f'{argumentos[0]}: estimativa {orcamento.estimated_input_tokens} > {orcamento.max_input_tokens}; aceito pela '
          f'contagem bruta ({orcamento.raw_estimated_tokens} + saída {orcamento.max_output_tokens} + margem '
          f'{orcamento.safety_tokens} = {total} ≤ {orcamento.max_context_tokens})')
    return pedido


def metricas_busca(refs, fontes_legislacao):
    """Hit@1/3/5, RR@3 (para o MRR@3) e precisão@3 dos artigos de lei recuperados contra as referências da curadoria."""
    if not refs:
        return {}
    ranking = [(cmp.norma_do_caminho(f.get('caminho_relativo')), cmp._artigo(f.get('artigo_ref'))) for f in fontes_legislacao]
    relevante = [any((n, a) == r if a else n == r[0] for n, a in refs) for r in ranking]
    primeira = next((i for i, v in enumerate(relevante, 1) if v), None)
    m = dict(artigos_entregues=len(ranking), hit_1=int(any(relevante[:1])), hit_3=int(any(relevante[:3])),
             rr_3=1 / primeira if primeira and primeira <= 3 else 0.0,
             precisao_3=sum(relevante[:3]) / max(1, min(3, len(ranking))))
    m['hit_5'] = int(any(relevante[:5])) if len(ranking) >= 5 else None
    return m


def importar():
    """Grava, só com identificadores, notas e tempos (sem texto de perguntas, fontes ou respostas):
      reports/integracao/comparacao/metricas_rag_llm_por_resposta.csv   uma linha por pergunta × configuração
      reports/integracao/comparacao/recuperacao_rag_por_pergunta.csv    métricas de recuperação por pergunta × busca
    """
    pedidos_juiz = pedidos_juiz_originais()
    saidas = baixar_kernel(f'{USUARIO}/lexia-comparacao-juiz', BASE / 'juiz/resultados')
    isolado = baixar_kernel(f'{USUARIO}/lexia-comparacao-isolado', BASE / 'isolado/resultados')
    hibrido = baixar_kernel(f'{USUARIO}/lexia-geracao-qwen3', GERACAO / 'resultados')
    variantes = {}   # nome → (pedidos de geração, respostas); só as variantes que já têm pedidos montados
    for nome, v in VARIANTES.items():
        arquivo = BASE / v['pasta'] / 'dataset/pedidos.jsonl'
        if not arquivo.exists():
            continue
        variantes[nome] = ({p['pergunta_id']: p for p in jsonl(arquivo)},
                           baixar_kernel(f'{USUARIO}/{v["kernel"]}', BASE / v['pasta'] / 'resultados'))
        juiz = BASE / v['pasta_juiz'] / 'dataset/pedidos.jsonl'
        if juiz.exists():
            pedidos_juiz.update({p['pergunta_id']: p for p in jsonl(juiz)})
            saidas.update(baixar_kernel(f'{USUARIO}/{v["kernel_juiz"]}', BASE / v['pasta_juiz'] / 'resultados'))
    linhas, busca = [], []
    for item in conjunto():
        p, refs = item['pedido'], item['referencias']
        qid = p['pergunta_id']
        leg_h = [f for f in p['fontes'] if f['fonte'] == 'legislacao']
        n_jur = sum(f['fonte'] == 'jurisprudencia' for f in p['fontes'])
        busca.append(dict(pergunta_id=qid, acao=p['acao'], busca='hibrida', n_referencias=len(refs),
                          segundos=p.get('segundos_recuperacao'), decisoes_entregues=n_jur, **metricas_busca(refs, leg_h)))
        gerada = {'llm_isolado': (isolado.get(qid), [], 0.0),
                  'busca_sem_llm': (None, leg_h, p.get('segundos_recuperacao') or 0.0),
                  'rag_hibrido': (hibrido.get(qid), p['fontes'], p.get('segundos_recuperacao') or 0.0)}
        for nome, (ped, resp) in variantes.items():
            g = ped[qid]
            busca.append(dict(pergunta_id=qid, acao=p['acao'], busca=VARIANTES[nome]['busca'], n_referencias=len(refs),
                              segundos=g['segundos_recuperacao'],
                              decisoes_entregues=sum(f['fonte'] == 'jurisprudencia' for f in g['fontes']),
                              **metricas_busca(refs, [f for f in g['fontes'] if f['fonte'] == 'legislacao'])))
            r = resp.get(qid)
            gerada[nome] = (r if r and r.get('pedido_sha256') == g['pedido_sha256'] else None, g['fontes'],
                            g['segundos_recuperacao'])
        for config in [c for c in CONFIGURACOES if c in gerada]:
            rec, fontes, busca_s = gerada[config]
            texto = cmp.resposta_busca(leg_h) if config == 'busca_sem_llm' else (rec or {}).get('resposta') or ''
            inferencia = 0.0 if config == 'busca_sem_llm' else (rec or {}).get('segundos')
            saida = revisar(dict(p, fontes=fontes), texto) if texto else None
            linha = dict(pergunta_id=qid, acao=p['acao'], config=config, n_referencias=len(refs), tem_resposta=bool(texto),
                         seguranca=cmp.seguro(saida.alertas) if saida else None,
                         alertas=len(saida.alertas) if saida else None,
                         cita_referencia=cmp.cita_referencia(texto, refs) if config != 'busca_sem_llm' and texto else None,
                         tokens_saida=(rec or {}).get('tokens_saida'), inferencia_s=inferencia,
                         latencia_s=(inferencia or 0.0) + busca_s if texto else None)
            jid = f'{config}|{qid}'
            s = saidas.get(jid)
            if s and pedidos_juiz.get(jid) and s.get('pedido_sha256') == pedidos_juiz[jid]['pedido_sha256']:
                try:
                    j = interpretar(s['resposta'])
                    afirmacoes = j.get('afirmacoes') or []
                    suporte = [a.get('suporte') for a in afirmacoes]
                    jur = [d for d in j.get('jurisprudencia_pertinente') or [] if isinstance(d, dict)]
                    linha.update(correcao=j.get('correcao'), fidelidade=j.get('fidelidade'), aderencia=j.get('comportamento'),
                                 clareza=j.get('clareza'), veredito_modelo=j.get('veredito'),
                                 veredito_regra=j['veredito_regra'], afirmacoes=len(afirmacoes),
                                 **{f'afirmacoes_{k}': suporte.count(k) for k in ('apoiada', 'parcial', 'sem_apoio', 'contradita')},
                                 decisoes_julgadas=len(jur), decisoes_pertinentes=sum(bool(d.get('pertinente')) for d in jur))
                except (ValueError, TypeError) as e:
                    linha['erro_juiz'] = str(e)[:120]
            linhas.append(linha)
    RELATORIOS.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(linhas)
    df.to_csv(RELATORIOS / 'metricas_rag_llm_por_resposta.csv', index=False, encoding='utf-8')
    rb = pd.DataFrame(busca)
    rb.to_csv(RELATORIOS / 'recuperacao_rag_por_pergunta.csv', index=False, encoding='utf-8')
    print(rb.groupby('busca')[['hit_1', 'hit_3', 'hit_5', 'rr_3', 'precisao_3', 'segundos']].mean().round(2))
    print(df.groupby('config')[['correcao', 'fidelidade', 'aderencia', 'clareza', 'seguranca', 'cita_referencia',
                                'latencia_s']].mean().round(2).T)
    print('julgamentos válidos:', df.dropna(subset=['veredito_regra']).groupby('config').size().to_dict())


if __name__ == '__main__':
    {'buscar': buscar, 'julgar': julgar, 'importar': importar}[sys.argv[1]]()
