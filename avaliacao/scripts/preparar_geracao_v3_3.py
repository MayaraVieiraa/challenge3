"""Prepara a geração v3.3: a v3.2 com a lei posterior prevalecendo sobre o precedente anterior (2026-11-23).

Parte dos pedidos da v3.2 e muda só três coisas:
  1. prompt v3 com a regra 25 reescrita (ordem entre lei posterior, precedente e tema repetitivo; data dos fatos);
  2. precedentes com o "[Alerta de lei posterior: …]" (worker/evidencia/precedentes_lei_posterior.json);
  3. legislação na versão `ec141_2026_notas_divisor` (nota no divisor 220 da LC 150, art. 2º, § 2º): as 3 fontes de
     legislação de cada pedido são buscadas de novo nessa versão.
Continuam iguais: as perguntas, as 3 decisões judiciais, os precedentes escolhidos, a data atual (2026-11-22), o
modelo (Qwen3 8B q8_0) e as opções (temperatura 0, seed 42).

Controles (se algum falhar, nada é gravado):
  1. o prompt da v3.2 é reproduzido com o código atual (regra 25 antiga, REGRA_25_V3_2);
  2. a busca de legislação na versão `ec141_2026_notas` reproduz as fontes de legislação da v3.2;
  3. a busca de precedentes escolhe os mesmos precedentes da v3.2, e o texto deles, sem a linha do alerta de lei
     posterior, é idêntico ao da v3.2;
  4. todos os pedidos cabem na janela de contexto. Se a juris_011 (a maior, que já ficou sem precedentes na v3.2)
     não couber, ela sai do conjunto (decisão da usuária); em qualquer outro pedido, sai o precedente de pior posição.

Saída (fora do Git): dados/output/kaggle/geracao_v3_3/{dataset,kernel}; resumo das mudanças em
dados/relatorios/integracao/correcoes/geracao_v3_3_mudancas.csv (só identificadores).
Uso: python avaliacao/scripts/preparar_geracao_v3_3.py
"""
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from worker.evidencia.context_window import ContextWindowExceeded, validar_janela_contexto  # noqa: E402
from worker.evidencia.explicador import _hash, fonte_para_prompt  # noqa: E402
from worker.evidencia.prompt_juridico import REGRA_25_V3_2, REGRAS_V3, build_rag_prompt  # noqa: E402
from worker.evidencia.recuperador import (Recuperador, configuracao_com_precedentes,  # noqa: E402
                                        configuracao_duas_bases)
from worker.evidencia.indices.pgvector_store import load_database_url  # noqa: E402

ORIGEM = ROOT / 'dados/output/kaggle/geracao_v3_2'
KERNEL_ORIGEM = ROOT / 'dados/output/kaggle/geracao/kernel'
DESTINO = ROOT / 'dados/output/kaggle/geracao_v3_3'
RELATORIO = ROOT / 'dados/relatorios/integracao/correcoes/geracao_v3_3_mudancas.csv'
USUARIO_KAGGLE = 'laisapaiva93'
DATASET = 'lexia-geracao-v3-3-pedidos'
KERNEL = 'lexia-geracao-qwen3-v3-3'
VERSAO_ANTERIOR, VERSAO_NOVA = 'ec141_2026_notas', 'ec141_2026_notas_divisor'
REGRA_25 = REGRAS_V3[REGRAS_V3.index('\n25. ') + 1:]
CONFIG_LEG = configuracao_duas_bases(fontes=('legislacao',), entrega_por_fonte={'legislacao': 3}, top_k=10)
CONFIG_PREC = configuracao_com_precedentes(fontes=('precedentes',), entrega_por_fonte={'precedentes': 3})
SEM_ALERTA = re.compile(r'\n\[Alerta de lei posterior: [^\n]*\]')
RETIRAVEL = 'juris_011'


def chave(fontes):
    return [(f['unidade'], f['conteudo']) for f in fontes]


def legislacao(rec, pergunta):
    entregues, _ = rec.buscar(pergunta, CONFIG_LEG)
    return [fonte_para_prompt(u) for u in entregues]


def main():
    pedidos = [json.loads(l) for l in (ORIGEM / 'dataset/pedidos.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    com_llm = [p for p in pedidos if p.get('precisa_llm')]
    url = load_database_url(ROOT / '.env.pgvector.local')

    # Controle 1: o prompt da v3.2 é reproduzido com o código atual.
    for p in com_llm:
        s, u = build_rag_prompt(p['pergunta_sanitizada'], p['fontes'], versao='v3', data_atual=p['data_atual'])
        if s.replace(REGRA_25, REGRA_25_V3_2, 1) != p['mensagens'][0]['content'] or not p['mensagens'][1]['content'].startswith(u):
            raise SystemExit(f"{p['pergunta_id']}: o prompt da v3.2 não é reproduzido (nada gravado)")

    # Controle 2: a versão anterior da legislação reproduz as fontes de legislação da v3.2.
    rec = Recuperador(url, device='cpu', carregar_reranker=True, versao_legislacao=VERSAO_ANTERIOR)
    divergentes = [p['pergunta_id'] for p in com_llm if chave(legislacao(rec, p['pergunta_sanitizada']))
                   != chave([f for f in p['fontes'] if f['fonte'] == 'legislacao'])]
    rec.fechar()
    if divergentes:
        raise SystemExit(f'a legislação {VERSAO_ANTERIOR} não reproduz {len(divergentes)} pedidos (nada gravado): {divergentes[:10]}')
    print(f'controles 1 e 2 ok: prompt e legislação da v3.2 reproduzidos nos {len(com_llm)} pedidos', flush=True)

    rec = Recuperador(url, device='cpu', carregar_reranker=True, versao_legislacao=VERSAO_NOVA)
    novos, linhas, acima, retiradas = [], [], [], []
    for p in pedidos:
        if not p.get('precisa_llm'):
            novos.append(p)
            continue
        pid = p['pergunta_id']
        antigos_prec = [f for f in p['fontes'] if f['fonte'] == 'precedentes']
        jur = [f for f in p['fontes'] if f['fonte'] == 'jurisprudencia']
        leg = legislacao(rec, p['pergunta_sanitizada'])
        prec = []
        if antigos_prec:
            entregues, _ = rec.buscar(p['pergunta_sanitizada'], CONFIG_PREC)
            encontrados = [fonte_para_prompt(u) for u in entregues]
            # Controle 3: mesmos precedentes, e o texto sem a linha do alerta é o da v3.2.
            v32 = [(f['unidade'], f['conteudo']) for f in antigos_prec]
            agora = [(f['unidade'], SEM_ALERTA.sub('', f['conteudo'])) for f in encontrados[:len(antigos_prec)]]
            if agora != v32:
                raise SystemExit(f'{pid}: os precedentes não reproduzem a v3.2 (nada gravado)')
            prec = encontrados[:len(antigos_prec)]
        complemento = p['mensagens'][1]['content'][len(build_rag_prompt(p['pergunta_sanitizada'], p['fontes'], versao='v3',
                                                                          data_atual=p['data_atual'])[1]):]
        janela = None
        for n in range(len(prec), -1, -1):
            fontes = leg + jur + prec[:n]
            sistema, usuario = build_rag_prompt(p['pergunta_sanitizada'], fontes, versao='v3', data_atual=p['data_atual'])
            mensagens = [dict(role='system', content=sistema), dict(role='user', content=usuario + complemento)]
            try:
                janela = validar_janela_contexto(mensagens, max_context_tokens=p['opcoes']['num_ctx'],
                                                 max_output_tokens=p['opcoes']['num_predict'])
                break
            except ContextWindowExceeded as erro:
                excedeu = erro.budget.estimated_input_tokens
            if pid == RETIRAVEL:
                break          # a juris_011 não perde mais fontes: sai do conjunto
        if janela is None:
            if pid == RETIRAVEL:
                retiradas.append(f'{pid} ({excedeu} tokens estimados)')
                continue
            acima.append(f'{pid} ({excedeu})')
            continue
        prec = prec[:n]
        novos.append(dict(p, fontes=fontes, mensagens=mensagens, versao_legislacao=VERSAO_NOVA,
                          pedido_sha256=_hash(p['modelo'], p['opcoes'], mensagens), pedido_v3_2_sha256=p['pedido_sha256'],
                          janela_contexto=janela.para_dict()))
        antigos_leg = [f for f in p['fontes'] if f['fonte'] == 'legislacao']
        linhas.append(dict(pergunta_id=pid,
                           legislacao_mudou=chave(leg) != chave(antigos_leg),
                           com_nota_divisor=sum('Súmula 431 do TST' in f['conteudo'] for f in leg),
                           precedentes=len(prec),
                           com_alerta_lei_posterior=sum('[Alerta de lei posterior:' in f['conteudo'] for f in prec),
                           precedentes_com_alerta=';'.join(f['unidade'] for f in prec if '[Alerta de lei posterior:' in f['conteudo']),
                           tokens_v3_2=p['janela_contexto']['estimated_input_tokens'], tokens_v3_3=janela.estimated_input_tokens))
    rec.fechar()
    if acima:
        raise SystemExit(f'pedidos acima da janela de contexto (nada gravado): {acima}')

    dataset = DESTINO / 'dataset'
    dataset.mkdir(parents=True, exist_ok=True)
    with (dataset / 'pedidos.jsonl').open('w', encoding='utf-8', newline='\n') as f:
        for p in novos:
            f.write(json.dumps(p, ensure_ascii=False) + '\n')
    (dataset / 'dataset-metadata.json').write_text(json.dumps(dict(
        title=DATASET, id=f'{USUARIO_KAGGLE}/{DATASET}', licenses=[dict(name='unknown')],
        description=('Pedidos privados de geração do LexIA, prompt v3 com a regra 25 reescrita (lei posterior), '
                     'precedentes do TST com alerta de lei posterior e legislação com a nota do divisor 220 da LC 150. '
                     'Contém trechos de decisões não anonimizados integralmente; não redistribuir.')), indent=2,
        ensure_ascii=False), encoding='utf-8')
    kernel = DESTINO / 'kernel'
    kernel.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(KERNEL_ORIGEM / 'gerar_respostas.py', kernel / 'gerar_respostas.py')
    meta = json.loads((KERNEL_ORIGEM / 'kernel-metadata.json').read_text(encoding='utf-8'))
    meta.update(id=f'{USUARIO_KAGGLE}/{KERNEL}', title=KERNEL, dataset_sources=[f'{USUARIO_KAGGLE}/{DATASET}'])
    (kernel / 'kernel-metadata.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')

    t = pd.DataFrame(linhas)
    RELATORIO.parent.mkdir(parents=True, exist_ok=True)
    t.to_csv(RELATORIO, index=False, encoding='utf-8')
    print(f"{len(novos)} pedidos ({len(t)} com LLM) · retirada(s): {retiradas or 'nenhuma'}")
    print(f"legislação mudou em {int(t.legislacao_mudou.sum())} pedidos (com a nota do divisor: {int((t.com_nota_divisor > 0).sum())}) · "
          f"pedidos com precedente com alerta de lei posterior: {int((t.com_alerta_lei_posterior > 0).sum())} · "
          f"precedentes por pedido: {t.precedentes.value_counts().to_dict()}")
    print(f'tokens de entrada (estimados): v3.2 máx {t.tokens_v3_2.max()} · v3.3 média {t.tokens_v3_3.mean():.0f}, máx {t.tokens_v3_3.max()} (limite 14.672)')
    print('dataset:', dataset.relative_to(ROOT), '· kernel:', kernel.relative_to(ROOT), '· relatório:', RELATORIO.relative_to(ROOT))


if __name__ == '__main__':
    main()
