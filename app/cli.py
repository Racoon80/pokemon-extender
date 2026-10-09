"""python -m app.cli picture.jpg -o out/ [--template psa|bgs]"""
from __future__ import annotations

import argparse
import json
from dataclasses import fields
from pathlib import Path

from PIL import Image

from .pipeline import Options, run


def main() -> None:
    p = argparse.ArgumentParser(description="Print sheet and cut line for a finished slab picture")
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

    opts = Options(**{f.name: getattr(args, f.name) for f in fields(Options)})
    meta = run(Image.open(args.image), opts, args.out)
    print(json.dumps(meta, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
