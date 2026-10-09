"""Serve a separate loopback-only stored options observer; never enroll a trader."""

import argparse

import uvicorn

from app.web.options import create_options_app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", required=True)
    parser.add_argument("--population-id", required=True)
    parser.add_argument("--password-file", required=True)
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("A nonprivileged bounded port is required")
    app = create_options_app(args.journal, args.population_id, args.password_file)
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
