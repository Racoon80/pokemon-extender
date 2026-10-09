# Pokemon-Extender

Turns a **finished picture** — a Pokémon card already extended to slab size (by hand or with any AI
tool), the card itself still in it — into a print sheet in the exact size of a **PSA slab** plus
**one cut line**: the slab outline plus the label window, as one path. Print it, cut it, put it into the acrylic case.

The program does no painting. It finds the card in the picture, takes its size as the scale (a card
is 63 × 88 mm), and places the slab outline around it so the printed card lands exactly where the
real card lies in the slab.

Web UI in **English, Deutsch, Français and Lëtzebuergesch** (follows the browser language,
switchable in the top corner). A job takes a second or two; no GPU needed.

## Install
### Unraid (Compose Manager plugin)
1. Apps: install **Docker Compose Manager**.
2. Docker → *Compose* → *Add New Stack* → name `Pokemon-Extender`.
3. *Edit Stack* → *Compose File*: paste [`unraid/docker-compose.yml`](unraid/docker-compose.yml), save.
4. *Compose Up*. It pulls the image `ghcr.io/racoon80/pokemon-extender:latest`.
5. Open `http://<unraid-ip>:8000` (or *WebUI* in the Docker tab).

Update: *Update Stack* — it pulls the latest image.

### Linux / Windows / macOS (Docker)
Put [`docker-compose.yml`](docker-compose.yml) into an empty folder, then:
```bash
docker compose up -d                              # update: docker compose pull && docker compose up -d
```
Or without compose: `docker run -d -p 127.0.0.1:8000:8000 -v ./data:/data ghcr.io/racoon80/pokemon-extender:latest`.
Open `http://localhost:8000`.

The image (`linux/amd64` and `linux/arm64`, so Raspberry Pi and Apple Silicon too) is built by
GitHub Actions on every push to `main`. To build it yourself: clone the repo and
`docker build -t pokemon-extender .`.

The port only listens on the local machine (`127.0.0.1`). For your
LAN, change it to `"8000:8000"` in `docker-compose.yml`. There is **no login** — never expose it to
the internet.

## The picture
- The **whole card** has to be visible, upright, with background around it on every side.
- Any size or aspect ratio. The card's resolution decides the print quality: at 260 dpi the card
  needs about 650 × 900 px. Below 200 dpi the UI warns.
- Where the picture does not reach the cut line, it is filled with blurred, mirrored background
  and the UI says how many mm were missing on which side.

**Card and label position** are fixed by the template, as in the real case: PSA card 35.5 mm from
the top, label window 5.6 mm from the top, 11.6 mm of picture between them. Leave enough
background above the card (PSA: about 36 mm at card scale, i.e. 40 % of the card height).

## How it works
1. Find the card: the largest card-shaped (63:88) rectangle inside the picture (`app/card.py`),
   slight rotation included.
2. Scale = card width in pixels / 63 mm. Place the slab outline and label window from
   `templates/*.json` around it.
3. Resample the picture to the sheet at print resolution (`app/pipeline.py`).
4. Write the sheet and the cut line (`app/cutfile.py`).

## Slab formats (`templates/*.json`)
Pick the format in the web UI (or `--template` on the CLI). All values in mm.

| Template | Outer size | Label window | Card |
|---|---|---|---|
| `psa` — PSA | 81 × 136 | 68 × 18.3, 5.6 from the top | 63 × 88, 9 from the left, 35.5 from the top |
| `bgs` — Beckett | 84 × 131 | 63 × 20, 6 from the top | 63 × 88, 10.5 from the left, 31 from the top |

Outer sizes are the most widely quoted figures — neither PSA nor Beckett publishes an official
spec. Label and card positions are measured from product photos (PSA) or estimated (BGS):
check them against a real slab. To correct one or add a format, put a `*.json` into
`templates/` inside the data volume (Unraid: `/mnt/user/appdata/pokemon-extender/templates/`); a
file there wins over the built-in one with the same name. It is read for every job.

## Settings (`docker-compose.yml`)
| Variable | |
|---|---|
| `MAX_UPLOAD_MB` | Upload limit (25 MB) |
| `MAX_JOBS` | Pictures processed at the same time (2); more wait up to 30 s, then get *busy* |
| `OUTPUT_TTL_HOURS` | Results are deleted after 72 h |

## Print then cut (Bambu Lab cutting module, other cutters)
The cut is **one path** with two closed shapes — the slab outline and the label window — in
millimetres, with the same origin (top left) as the print image. The card is not cut: it is part of
the picture.

| File | Use |
|---|---|
| `cutout.png` | **Bambu Suite:** only the slab (81 × 136 mm), transparent outside its rounded outline and inside the label window. Import, set to *Print Then Cut*: the Suite traces the edge itself, no cut file needed. No bleed |
| `print-cut.svg` | Print image and cut line in one file, already aligned |
| `print.pdf` / `print.png` | Print image only, exact size incl. bleed |
| `cut.dxf` | Cut line only, for software that wants the cut as a separate DXF |

On Bambu Lab printers (H2D/H2S with the cutting module) print-then-cut runs in **Bambu Suite**
(not Bambu Studio). The Suite makes the cut lines itself from the outline of the picture and they
cannot be edited by hand, so `cutout.png` is the simplest way in. For other cutters use
`print-cut.svg` or `cut.dxf` and keep the default **2 mm bleed** so the blade never runs along the
edge of the picture.

## CLI
```bash
docker compose exec pokemon-extender python -m app.cli /data/picture.jpg -o /data/out
# locally: pip install -r requirements.txt, then
python -m app.cli picture.jpg -o out
```

## Licence
Code: MIT (`LICENSE`).
Pokémon and card images are © Nintendo / Creatures / GAME FREAK — this project is not
affiliated with them.
