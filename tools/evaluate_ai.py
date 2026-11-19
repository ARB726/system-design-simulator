"""Generate engine evidence and score recorded JSONL responses or offline controls."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fullstack.backend.ai import evidence
from fullstack.backend.ai_evaluation import cases, score
from fullstack.backend.ai_benchmarks import summarize
from fullstack.backend.jobs import execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--generate', action='store_true')
    parser.add_argument('--responses', type=Path, help='JSONL: case_id, variant, answer, latency_ms, input_tokens, output_tokens')
    parser.add_argument('--prices', type=Path, help='JSON: variant -> input_per_million, output_per_million (USD)')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.generate:
        corpus = []
        for case in cases():
            result = execute(dict(config=case['config'], kind='simulate'))
            encoded, metrics = evidence(dict(status='completed', payload=dict(config=case['config']), result=result))
            corpus.append(case | dict(metrics=metrics, evidence=json.loads(encoded)))
        args.corpus.parent.mkdir(parents=True, exist_ok=True)
        args.corpus.write_text(json.dumps(corpus, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    corpus = json.loads(args.corpus.read_text(encoding='utf-8'))
    by_id = {case['id']:case for case in corpus}
    rows = []
    if args.responses:
        records = [json.loads(line) for line in args.responses.read_text(encoding='utf-8').splitlines() if line.strip()]
        seen = set()
        for row in records:
            identity = (row['variant'], row['case_id'])
            if identity in seen:
                parser.error('Duplicate variant/case response.')
            seen.add(identity)
            evaluation = score(row['answer'], by_id[row['case_id']]['metrics'])
            rows.append({k:row.get(k) for k in ('variant','case_id','latency_ms','input_tokens','output_tokens')} | evaluation)
        for variant in {row['variant'] for row in rows}:
            if {row['case_id'] for row in rows if row['variant'] == variant} != set(by_id):
                parser.error('Every variant must cover the complete corpus for a paired comparison.')
    else:
        # These test the scorer, not model quality. No provider calls or token estimates.
        for case in corpus:
            for variant, offset in [('grounded-control',0), ('fabricated-control',10000)]:
                answer = dict(summary='Synthetic scorer control.', observations=[dict(metric='p95_ms', interpretation=f"Latency is {case['metrics']['p95_ms'] + offset:.2f} ms.")], next_experiment='Hold seed and workload fixed; change workers.', limitations='Scorer control; not model output.')
                started = time.perf_counter()
                evaluation = score(answer, case['metrics'])
                rows.append(dict(case_id=case['id'], variant=variant, latency_ms=(time.perf_counter()-started)*1000, input_tokens=None, output_tokens=None, **evaluation))
    prices = json.loads(args.prices.read_text(encoding='utf-8')) if args.prices else None
    report = dict(mode='recorded-responses' if args.responses else 'offline-scorer-controls', latency_scope='recorded-provider-latency' if args.responses else 'scorer-only', summary=summarize(rows, prices), results=rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
