from pathlib import Path
import sys
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    from src.jurisprudencia.light_nlp import run
    run(root)
