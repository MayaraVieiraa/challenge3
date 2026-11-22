"""Prepara a nova geração com o prompt v3 (notebook 06): mesmos pedidos da geração atual, trocando só o prompt.

Para cada pedido de output/kaggle/geracao/dataset/pedidos.jsonl que precisa de LLM:
  1. confere que build_rag_prompt (v1) reproduz o prompt original (o pedido antigo é reproduzível com o código atual);
  2. monta o prompt v3 com as MESMAS fontes e a mesma pergunta, preserva o que vinha depois do prompt do usuário
     (nota de caso concreto) e recalcula o hash. Modelo, opções e formato (texto livre) não mudam.
Pedidos sem LLM (respostas fixas) seguem iguais.

Saída (fora do Git): output/kaggle/geracao_v3/dataset/ (pedidos.jsonl + metadados do dataset privado)
                     output/kaggle/geracao_v3/kernel/  (mesmo script do kernel da geração atual)
Uso: python scripts/preparar_geracao_v3.py [--data 2026-11-22]
"""
import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.integracao.context_window import ContextWindowExceeded, validar_janela_contexto  # noqa: E402
from src.integracao.geracao import _hash  # noqa: E402
from src.integracao.prompt_juridico import build_rag_prompt  # noqa: E402

ORIGEM = ROOT / 'output/kaggle/geracao'
DESTINO = ROOT / 'output/kaggle/geracao_v3'
USUARIO_KAGGLE = 'laisapaiva93'
DATASET = 'lexia-geracao-v3-pedidos'
KERNEL = 'lexia-geracao-qwen3-v3'


def pedido_v3(p, data_atual):
    sistema, usuario = build_rag_prompt(p['pergunta_sanitizada'], p['fontes'])
    if p['mensagens'][0]['content'] != sistema or not p['mensagens'][1]['content'].startswith(usuario):
        raise ValueError(f"{p['pergunta_id']}: o prompt v1 não reproduz o pedido original")
    complemento = p['mensagens'][1]['content'][len(usuario):]
    sistema3, usuario3 = build_rag_prompt(p['pergunta_sanitizada'], p['fontes'], versao='v3', data_atual=data_atual)
    mensagens = [dict(role='system', content=sistema3), dict(role='user', content=usuario3 + complemento)]
    janela = validar_janela_contexto(mensagens, max_context_tokens=p['opcoes']['num_ctx'],
                                     max_output_tokens=p['opcoes']['num_predict'])
    novo = dict(p, mensagens=mensagens, versao_prompt='v3', data_atual=data_atual,
                pedido_sha256=_hash(p['modelo'], p['opcoes'], mensagens), pedido_v1_sha256=p['pedido_sha256'],
                janela_contexto=janela.para_dict())
    return novo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=date.today().isoformat())
    args = ap.parse_args()
    pedidos = [json.loads(l) for l in (ORIGEM / 'dataset/pedidos.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    novos, acima = [], []
    for p in pedidos:
        try:
            novos.append(pedido_v3(p, args.data) if p.get('precisa_llm') else p)
        except ContextWindowExceeded as erro:
            acima.append(f"{p['pergunta_id']} ({erro.budget.estimated_input_tokens} > {erro.budget.max_input_tokens})")
    if acima:
        raise SystemExit(f'pedidos acima da janela de contexto estimada (nada foi gravado): {acima}')

    dataset = DESTINO / 'dataset'
    dataset.mkdir(parents=True, exist_ok=True)
    with (dataset / 'pedidos.jsonl').open('w', encoding='utf-8') as f:
        for p in novos:
            f.write(json.dumps(p, ensure_ascii=False) + '\n')
    (dataset / 'dataset-metadata.json').write_text(json.dumps(dict(
        title=DATASET, id=f'{USUARIO_KAGGLE}/{DATASET}', licenses=[dict(name='unknown')],
        description=('Pedidos privados de geração do LexIA com o prompt v3 (mesmas perguntas e fontes da geração '
                     'anterior). Contém trechos de decisões não anonimizados integralmente; não redistribuir.')),
        indent=2, ensure_ascii=False), encoding='utf-8')

    kernel = DESTINO / 'kernel'
    kernel.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ORIGEM / 'kernel/gerar_respostas.py', kernel / 'gerar_respostas.py')
    meta = json.loads((ORIGEM / 'kernel/kernel-metadata.json').read_text(encoding='utf-8'))
    meta.update(id=f'{USUARIO_KAGGLE}/{KERNEL}', title=KERNEL, dataset_sources=[f'{USUARIO_KAGGLE}/{DATASET}'])
    (kernel / 'kernel-metadata.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')

    llm = [p for p in novos if p.get('precisa_llm')]
    maior = max(p['janela_contexto']['estimated_input_tokens'] for p in llm)
    print(f'{len(novos)} pedidos ({len(llm)} com LLM) · data atual {args.data} · maior prompt estimado: {maior} tokens')
    print('dataset:', dataset.relative_to(ROOT), '· kernel:', kernel.relative_to(ROOT))


if __name__ == '__main__':
    main()
