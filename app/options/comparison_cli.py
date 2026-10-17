"""Materialize a private historical observer view from a completed native export."""

import argparse
import json

from app.options.comparison_view import build_comparison, read_private_json, write_comparison


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", required=True)
    parser.add_argument("--arm", choices=("A", "B", "C", "D"), required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        view = build_comparison(read_private_json(args.result, 16 * 1024 * 1024), args.arm)
        write_comparison(args.output, view)
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError):
        print(
            json.dumps(
                {
                    "status": "UNAVAILABLE",
                    "reason": "COMPARISON_MATERIALIZATION_FAILED",
                    "execution_authority": False,
                }
            )
        )
        return 2
    print(
        json.dumps(
            {
                "status": "CREATED",
                "population_id": view.population_id,
                "through": view.through.isoformat(),
                "execution_authority": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
