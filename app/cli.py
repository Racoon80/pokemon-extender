"""python -m app.cli kaart.jpg -o out/ [--backend flux|sdxl|preview]"""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import fields
from pathlib import Path

from PIL import Image

from .pipeline import Options, run


def main() -> None:
    p = argparse.ArgumentParser(description="Pokémon-Kaart op PSA-Slab-Gréisst erweideren")
    p.add_argument("image", type=Path)
    p.add_argument("-o", "--out", type=Path, default=Path("out"))
    defaults = Options()
    for f in fields(Options):
        flag = "--" + f.name.replace("_", "-")
        value = getattr(defaults, f.name)
        if isinstance(value, bool):
            p.add_argument(flag, action=argparse.BooleanOptionalAction, default=value)
        else:
            p.add_argument(flag, type=type(value), default=value)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    opts = Options(**{f.name: getattr(args, f.name) for f in fields(Options)})
    meta = run(Image.open(args.image), opts, args.out)
    print(json.dumps(meta, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
