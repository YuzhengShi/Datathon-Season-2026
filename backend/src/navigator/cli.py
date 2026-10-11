import argparse
import json
from pathlib import Path

import uvicorn

from .config import ROOT, Settings
from .db import import_demo, upgrade


def main():
    parser = argparse.ArgumentParser(description="Funding Navigator local backend")
    parser.add_argument("command", choices=["init-demo", "publish-live", "upgrade", "serve"])
    parser.add_argument("--mode", choices=["demo", "live"], default=None)
    parser.add_argument(
        "--dataset", type=Path, default=None, help="Override the source dataset path"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    settings = Settings()
    if args.mode:
        settings = settings.model_copy(update={"data_mode": args.mode})
    if args.command == "init-demo":
        if settings.data_mode != "demo":
            parser.error("init-demo requires --mode demo")
        dataset = args.dataset or Path(ROOT.parent / "dist/data/demo-opportunities.json")
        upgrade(settings)
        result = import_demo(settings, dataset)
        print(json.dumps({"data_mode": "demo", **result}))
    elif args.command == "publish-live":
        if settings.data_mode != "live":
            parser.error("publish-live requires --mode live")
        from .publish import DEFAULT_DATASET, publish

        upgrade(settings)
        result = publish(settings, args.dataset or DEFAULT_DATASET)
        print(json.dumps(result))
    elif args.command == "upgrade":
        upgrade(settings)
        print(json.dumps({"data_mode": settings.data_mode, "migration": "complete"}))
    else:
        from .main import create_app

        uvicorn.run(create_app(settings), host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
