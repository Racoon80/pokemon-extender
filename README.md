# Pokemon-Extender

Extends the artwork of a Pokémon card (scan or photo) with AI outpainting (FLUX.1 Fill) to the
size of a **PSA slab**, so it can be printed and placed in an acrylic display case.
**The card area and the label area stay white.**

Output: `print.pdf` / `print.png` at exact physical size (260 dpi by default), plus a
`preview.jpg` showing the card and a label in place.

Web UI in **English, Deutsch, Français and Lëtzebuergesch** (follows the browser language,
switchable in the top corner), with a progress bar (stage, step, time left) and a preview of the
uploaded image.

## Install
Needs an NVIDIA GPU with **≥ 12 GB VRAM** and a free Hugging Face account: FLUX.1 Fill dev is
*gated*, so accept its licence at
[huggingface.co/black-forest-labs/FLUX.1-Fill-dev](https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev)
and create a token with read access. Everything is set in the compose file — no `.env` needed.

The first start downloads the AI model (**~15 GB**: GGUF transformer 8.3 GB + T5 nf4 6.3 GB +
CLIP/VAE) into the data volume; the web page shows the progress. After that the token and the
internet are no longer needed. After every start the model needs a few minutes to load into the GPU.

### Unraid (Compose Manager plugin)
1. Apps: install **Nvidia Driver** and **Docker Compose Manager**.
2. Docker → *Compose* → *Add New Stack* → name `Pokemon-Extender`.
3. *Edit Stack* → *Compose File*: paste [`unraid/docker-compose.yml`](unraid/docker-compose.yml),
   put your token into `HF_TOKEN`, save.
4. *Compose Up*. Docker builds the image straight from this GitHub repo; nothing to clone.
5. Open `http://<unraid-ip>:8000` (or *WebUI* in the Docker tab).

Update: *Update Stack* — it rebuilds the latest version from GitHub (`pull_policy: build`); the
AI model in appdata is kept.

### Linux / Windows (Docker)
1. NVIDIA driver and Docker with GPU support
   - Linux: Docker + [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
   - Windows: Docker Desktop (WSL2 backend)
   - Check: `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`
2. ```bash
   git clone https://github.com/Racoon80/pokemon-extender.git && cd pokemon-extender
   # put your token into HF_TOKEN in docker-compose.yml
   docker compose up -d --build
   ```
3. Open `http://localhost:8000`

   The port only listens on the local machine (`127.0.0.1`). For your LAN, change it to
   `"8000:8000"` in `docker-compose.yml`. There is **no login** — never expose it to the internet.

## How it works
1. Find the card in the photo, straighten it, crop to 63:88 (`app/card.py`).
2. Place it on a slab-sized sheet (measurements from `templates/*.json`, all in mm).
3. Mask = everything except the card. The card's own border (`inset_mm`, 2.5 mm by default)
   is repainted too, so the **illustration** continues rather than the card frame.
4. Outpaint on the GPU with FLUX.1 Fill (`app/backends.py`, 12 steps). Only the card's
   illustration is shown to the model, at its exact place and size, so the scenery lines up with
   the real card. The T5 text encoder is only loaded briefly and freed again, so it never shares
   VRAM with the transformer.
5. Scale to print resolution and paint the card and label areas white (+ `white_margin_mm`).

## Slab formats (`templates/*.json`)
Pick the format in the web UI (or `--template` on the CLI). All values in mm.

| Template | Outer size | Label | Card |
|---|---|---|---|
| `psa` — PSA | 81 × 136 | 68 × 18.3, 5.6 from the top | 63 × 88, 35.5 from the top |
| `bgs` — Beckett | 84 × 131 | 63 × 20, 6 from the top | 63 × 88, 31 from the top |

Outer sizes are the most widely quoted figures — neither PSA nor Beckett publishes an official
spec. Label and card positions are measured from product photos (PSA) or estimated (BGS):
check them against a real slab. To correct one or add a format, put a `*.json` into
`templates/` inside the data volume (Unraid: `/mnt/user/appdata/pokemon-extender/templates/`); a
file there wins over the built-in one with the same name. It is read for every job.

## Settings (`docker-compose.yml`)
| Variable | |
|---|---|
| `HF_TOKEN` | Your Hugging Face token, only needed for the first download |
| `FLUX_GGUF_FILE` | `flux1-fill-dev-Q5_K_S.gguf` (8.3 GB). Less VRAM → `…-Q4_K_S.gguf` (6.8 GB); better quality → `…-Q8_0.gguf` (12.7 GB, > 16 GB VRAM). Downloaded on the next start |
| `TORCH_DTYPE` | `auto` = bf16 on Ampere (RTX 30xx) and newer, float32 on older cards (fp16 makes FLUX overflow into black images) |
| `CPU_OFFLOAD` | `auto` switches on below 12 GB free VRAM |
| `MAX_UPLOAD_MB` / `MAX_PENDING` | Upload limit (25 MB) and max. jobs in the queue (5) |
| `OUTPUT_TTL_HOURS` | Results are deleted after 72 h |

## Troubleshooting
| Problem | Fix |
|---|---|
| `CUDA out of memory` | `FLUX_GGUF_FILE: flux1-fill-dev-Q4_K_S.gguf`, restart |
| Black image | `TORCH_DTYPE: float32` (fp16 overflows) |
| Page shows *HF_TOKEN is missing* or `401` / `gated repo` | FLUX licence not accepted, or wrong token in the compose file |

## Print then cut (Bambu Lab cutting module, other cutters)
Every job also writes the cut lines — the slab outline plus the card and label windows (cut
along the edge of the white areas) — in millimetres, with the same origin (top left) as `print.png`:

| File | Use |
|---|---|
| `cut.dxf` | Cut lines only. Recommended for Bambu Suite — DXF imports at true size |
| `cut.svg` | Cut lines only (red, `0.1 mm`) |
| `print-cut.svg` | Print image and cut lines in one file, already aligned |

On Bambu Lab printers (H2D/H2S with the cutting module) print-then-cut runs in **Bambu Suite**:
import the print image and **one** of the cut files (`cut.dxf`), set it to *Basic Cut*, check the size in mm.
Use **2 mm bleed** so the blade never runs along the edge of white paper.

## CLI
```bash
docker compose exec pokemon-extender python -m app.cli /data/card.jpg -o /data/out --bleed-mm 2 --guides
# locally without a GPU, layout only:
python -m app.cli card.jpg -o out --backend preview
```

## Licence
Code: MIT (`LICENSE`). The FLUX.1-Fill-dev model has its own
[non-commercial licence](https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev/blob/main/LICENSE.md).
Pokémon and card images are © Nintendo / Creatures / GAME FREAK — this project is not
affiliated with them.
