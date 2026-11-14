"""Serve a separate loopback-only stored options observer; never enroll a trader."""

import argparse

import uvicorn

from app.web.options import create_options_app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", required=True)
    parser.add_argument("--population-id", required=True)
    parser.add_argument("--password-file", required=True)
    parser.add_argument("--comparison-file", help="Optional explicit historical comparison view")
    parser.add_argument("--mixed", action="store_true", help="Explicit stored mixed-account desk")
    parser.add_argument(
        "--operator-key-file", help="Optional signed portfolio-control inbox authority"
    )
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("A nonprivileged bounded port is required")
    app = create_options_app(
        args.journal,
        args.population_id,
        args.password_file,
        comparison_file=args.comparison_file,
        operator_key_file=args.operator_key_file,
        **({"mixed": True} if args.mixed else {}),
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
