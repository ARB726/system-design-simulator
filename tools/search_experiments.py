"""Local bounded search; --ai explicitly opts into configured paid provider calls."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fullstack.backend.ai import provider_config
from fullstack.backend.experiment_search import search, model_proposer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--budget', type=float, required=True)
    parser.add_argument('--target-rps', type=float, required=True)
    parser.add_argument('--max-runs', type=int, default=4)
    parser.add_argument('--ai', action='store_true')
    args = parser.parse_args()
    proposal = None
    if args.ai:
        settings = provider_config()
        if not settings:
            parser.error('Configure AI_PROVIDER, provider model and API key before using --ai.')
        provider, model = settings
        proposal = model_proposer(model, provider, budget=args.budget, target_rps=args.target_rps)
    result = search(json.loads(args.config.read_text(encoding='utf-8')), budget=args.budget,
                    target_rps=args.target_rps, max_runs=args.max_runs, propose=proposal)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
