"""Prepara a geração v3.4: a v3.3 gerada em duas etapas, com no máximo 2 fontes na resposta (2026-11-23).

Parte dos pedidos da v3.3 (mesmas perguntas, mesmas 9 fontes, mesma data, modelo e opções) e muda só a forma de
gerar (src/integracao/duas_etapas.py):
  1. escolha: o modelo lê as 9 fontes e devolve, em JSON com esquema, até 2 números de fonte e o que falta;
  2. redação: o modelo escreve vendo só as fontes escolhidas (Fonte 1 e Fonte 2), com a regra 26 (no máximo 2
     fontes; "as fontes consultadas não tratam deste ponto") e exemplos de forma no prompt de sistema.
Depois da geração, as respostas bloqueadas pelo validador passam pela segunda passada com busca complementar
(scripts/preparar_revisao_complementar.py).

Controles (se algum falhar, nada é gravado): o complemento de cada pedido (ação de entrada, nota de caso concreto)
é o da v3.3; a etapa 1 cabe na janela de contexto; a etapa 2, no pior caso (as 2 maiores fontes), também.

Saída (fora do Git): output/kaggle/geracao_v3_4/{dataset,kernel}. O dataset leva também duas_etapas.py e
prompt_juridico.py, que o kernel importa. Kernel: scripts/kaggle/gerar_respostas_duas_etapas.py (versionado).
Uso: python scripts/preparar_geracao_v3_4.py
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.integracao import duas_etapas as de  # noqa: E402
from src.integracao.context_window import ContextWindowExceeded, validar_janela_contexto  # noqa: E402
from src.integracao.geracao import _hash  # noqa: E402
from src.integracao.prompt_juridico import build_rag_prompt  # noqa: E402

ORIGEM = ROOT / 'output/kaggle/geracao_v3_3'
DESTINO = ROOT / 'output/kaggle/geracao_v3_4'
KERNEL = ROOT / 'scripts/kaggle/gerar_respostas_duas_etapas.py'
USUARIO_KAGGLE = 'laisapaiva93'
DATASET, KERNEL_NOME = 'lexia-geracao-v3-4-pedidos', 'lexia-geracao-qwen3-v3-4'


def main():
    global ORIGEM, DESTINO
    ap = argparse.ArgumentParser()
    ap.add_argument('--origem', default=None, help='pasta em output/kaggle (padrão: geracao_v3_3)')
    ap.add_argument('--destino', default=None, help='pasta em output/kaggle (padrão: geracao_v3_4)')
    args = ap.parse_args()
    ORIGEM = ROOT / 'output/kaggle' / args.origem if args.origem else ORIGEM
    DESTINO = ROOT / 'output/kaggle' / args.destino if args.destino else DESTINO
    pedidos = [json.loads(l) for l in (ORIGEM / 'dataset/pedidos.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    novos, acima = [], []
    for p in pedidos:
        if not p.get('precisa_llm'):
            novos.append(p)
            continue
        _, usuario = build_rag_prompt(p['pergunta_sanitizada'], p['fontes'], versao='v3', data_atual=p['data_atual'])
        if not p['mensagens'][1]['content'].startswith(usuario):
            raise SystemExit(f"{p['pergunta_id']}: a mensagem do usuário da v3.3 não é reproduzida (nada gravado)")
        complemento = p['mensagens'][1]['content'][len(usuario):]
        mensagens_escolha, formato = de.montar_escolha(p['pergunta_sanitizada'], p['fontes'], p['data_atual'])
        maiores = sorted(range(1, len(p['fontes']) + 1), key=lambda n: -len(p['fontes'][n - 1]['conteudo']))[:2]
        pior_redacao, _ = de.montar_redacao(p['pergunta_sanitizada'], p['fontes'], maiores, p['data_atual'], complemento,
                                            'x' * 300)
        try:
            j1 = validar_janela_contexto(mensagens_escolha, max_context_tokens=p['opcoes']['num_ctx'],
                                         max_output_tokens=de.OPCOES_ESCOLHA['num_predict'])
            j2 = validar_janela_contexto(pior_redacao, max_context_tokens=p['opcoes']['num_ctx'],
                                         max_output_tokens=p['opcoes']['num_predict'])
        except ContextWindowExceeded as erro:
            acima.append(f"{p['pergunta_id']} ({erro.budget.estimated_input_tokens})")
            continue
        novo = {k: v for k, v in p.items() if k not in ('mensagens', 'janela_contexto')}
        novo.update(modo='duas_etapas', escolha=dict(mensagens=mensagens_escolha, formato=formato),
                    redacao=dict(complemento=complemento), acrescimo_sistema=de.acrescimo_sistema(),
                    pedido_v3_3_sha256=p['pedido_sha256'],
                    janela_contexto=dict(escolha=j1.para_dict(), redacao_pior_caso=j2.para_dict()))
        novo['pedido_sha256'] = _hash(p['modelo'], p['opcoes'], mensagens_escolha, formato, novo['acrescimo_sistema'],
                                      complemento, [(f['unidade'], f['conteudo']) for f in p['fontes']])
        novos.append(novo)
    if acima:
        raise SystemExit(f'pedidos acima da janela de contexto (nada gravado): {acima}')

    dataset = DESTINO / 'dataset'
    dataset.mkdir(parents=True, exist_ok=True)
    with (dataset / 'pedidos.jsonl').open('w', encoding='utf-8', newline='\n') as f:
        for p in novos:
            f.write(json.dumps(p, ensure_ascii=False) + '\n')
    for nome in ('duas_etapas.py', 'prompt_juridico.py'):
        shutil.copyfile(ROOT / 'src/integracao' / nome, dataset / nome)
    (dataset / 'dataset-metadata.json').write_text(json.dumps(dict(
        title=DATASET, id=f'{USUARIO_KAGGLE}/{DATASET}', licenses=[dict(name='unknown')],
        description=('Pedidos privados de geração do LexIA em duas etapas (escolha de até 2 fontes e redação), com o '
                     'código das etapas. Contém trechos de decisões não anonimizados integralmente; não redistribuir.')),
        indent=2, ensure_ascii=False), encoding='utf-8')
    kernel = DESTINO / 'kernel'
    kernel.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(KERNEL, kernel / 'gerar_respostas.py')
    meta = json.loads((ROOT / 'output/kaggle/geracao/kernel/kernel-metadata.json').read_text(encoding='utf-8'))
    meta.update(id=f'{USUARIO_KAGGLE}/{KERNEL_NOME}', title=KERNEL_NOME, dataset_sources=[f'{USUARIO_KAGGLE}/{DATASET}'])
    (kernel / 'kernel-metadata.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
    com_llm = [p for p in novos if p.get('precisa_llm')]
    print(f'{len(novos)} pedidos ({len(com_llm)} com LLM), em duas etapas')
    print('tokens estimados da escolha: máx', max(p['janela_contexto']['escolha']['estimated_input_tokens'] for p in com_llm),
          '· redação no pior caso: máx', max(p['janela_contexto']['redacao_pior_caso']['estimated_input_tokens'] for p in com_llm))
    print('dataset:', dataset.relative_to(ROOT), '· kernel:', kernel.relative_to(ROOT))


if __name__ == '__main__':
    main()
