"""Private JSON subprocess entry point; never executes the Streamlit app."""
import json
import sys

from .config import config_from_dict
from .engine import run_summary
from .limits import validate_batch


def main():
    if sys.argv[1:] == ["--stream"]:
        for line in sys.stdin:
            index, data = json.loads(line)
            cfg = config_from_dict(data)
            validate_batch([cfg])
            print(json.dumps([index, run_summary(cfg)], allow_nan=False), flush=True)
        return
    points = json.load(sys.stdin)
    configs = [config_from_dict(data) for _, data in points]
    validate_batch(configs)
    json.dump([(index, run_summary(cfg)) for (index, _), cfg in zip(points, configs)], sys.stdout, allow_nan=False)


if __name__ == "__main__":
    main()
