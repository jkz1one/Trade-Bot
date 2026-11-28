"""Create a separate, frozen two-play native fixture; never activate a trader."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path

import app
from app.mixed.portfolio_replay import PortfolioReplay, replay


def create(output):
    if "site-packages" not in Path(app.__file__).parts:
        raise ValueError("Isolated noneditable installed application required")
    seed = Path(__file__).resolve().parent.parent / "examples/portfolio-dashboard-review.json"
    request = PortfolioReplay.model_validate_json(seed.read_bytes())
    if (
        request.settings.limits.population_id != "ui-review-two-play-20261009"
        or request.settings.limits.provider != "fixture"
    ):
        raise ValueError("Exact synthetic, model-off review enrollment required")
    os.umask(0o077)
    result = asyncio.run(replay(output, request))
    if result["status"] != "OK" or result["held_plays"] != 2 or result["fills"] != 2:
        raise ValueError("Two actual native held plays and fill receipts required")
    manifest = {
        **result,
        "version": "portfolio-dashboard-review-v2",
        "purpose": "Synthetic historical two-play UI review. No market acceptance.",
        "worker_running": False,
        "native_fill_receipts": result["fills"],
        "equity_at_fixture_time": result["equity"],
        "seed_sha256": hashlib.sha256(seed.read_bytes()).hexdigest(),
        "journal_sha256": hashlib.sha256((output / "options.db").read_bytes()).hexdigest(),
    }
    with (output / "review.json").open("x") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(create(parser.parse_args().output)))


if __name__ == "__main__":
    main()
