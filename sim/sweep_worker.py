"""Private JSON subprocess entry point; never executes the Streamlit app."""
import json
import sys

from .config import config_from_dict
from .engine import run_summary
from .limits import validate_batch


def main():
    points = json.load(sys.stdin)
    configs = [config_from_dict(data) for _, data in points]
    validate_batch(configs)
    json.dump([(index, run_summary(cfg)) for (index, _), cfg in zip(points, configs)], sys.stdout, allow_nan=False)


if __name__ == "__main__":
    main()
