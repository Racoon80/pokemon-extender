# Pokemon-Extender

Eng Pokémon-Kaart (Scan oder Foto) gëtt mat KI-Outpainting (FLUX.1 Fill) op d'Gréisst vun
engem **PSA-Slab** erweidert, fir als Drock an en Acryl-Case ze leeën.
**D'Plaz fir d'Kaart an d'Plaz fir de Label bleiwe wäiss.**

Resultat: `print.pdf` / `print.png` an exakter Gréisst (Standard 300 dpi), plus eng
`preview.jpg` mat der Kaart an engem Label dran.

## Installéieren
Brauch eng NVIDIA-Kaart mat **≥ 12 GB VRAM**.

1. NVIDIA-Treiber an Docker mat GPU-Support
   - Linux: Docker + [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
   - Windows: Docker Desktop (WSL2-Backend)
   - Test: `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`
2. FLUX.1-Fill-dev ass *gated*: op [huggingface.co/black-forest-labs/FLUX.1-Fill-dev](https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev)
   d'Lizenz akzeptéieren an e Read-Token erstellen.
3. ```bash
   git clone https://github.com/Racoon80/pokemon-extender.git && cd pokemon-extender
   cp .env.example .env      # HF_TOKEN aspillen
   docker compose up -d --build
   ```
4. `http://localhost:8000`

   Den Port ass nëmmen um eegene Computer op (`127.0.0.1`). Fir am LAN: an
   `docker-compose.yml` op `"8000:8000"` stellen. Et gëtt **kee Login** — net am Internet opmaachen.

Den éischte Start lued **~15 GB** an `./data` (GGUF-Transformer 8,3 GB + T5 nf4 6,3 GB +
CLIP/VAE). Fortschrëtt: `docker logs -f pokemon-extender`.

## Ablaf
1. Kaart erkennen, riicht zéien, op 63:88 schneiden (`app/card.py`).
2. Op e Slab-Blat setzen (Mooss aus `templates/*.json`, alles a mm).
3. Mask = alles ausser der Kaart. De Kaarte-Rand (`inset_mm`, Standard 2,5 mm) gëtt mat
   iwwermoolt, fir datt d'**Illustratioun** weidergeet an net de Rumm vun der Kaart.
4. Outpaint op der GPU (`app/backends.py`).
5. Op Drock-Opléisung bréngen, Kaart- a Label-Beräich wäiss (+ `white_margin_mm`).

## Mooss (`templates/psa.json`)
| | mm |
|---|---|
| Slab baussen | 81 × 136 (meescht zitéiert Gréisst; PSA publizéiert keng offiziell Spec) |
| Label | 68 × 18,3, 5,6 vun uewen, zentréiert |
| Kaart | 63 × 88, 35,5 vun uewen, zentréiert |

Label- a Kaartepositioun si vun engem Produktbild ausgemooss — mat engem richtege Slab
nomoossen. D'JSON gëtt bei all Job nei gelueden, kee Rebuild néideg.

## Astellungen (`docker-compose.yml`)
| Variabel | |
|---|---|
| `DEFAULT_BACKEND` | `flux` (Standard) / `sdxl` / `preview` (CPU, ouni Modell, nëmme fir Layout-Tester) |
| `FLUX_GGUF_FILE` | `flux1-fill-dev-Q5_K_S.gguf` (8,3 GB). Ze wéineg VRAM → `…-Q4_K_S.gguf` (6,8 GB); méi Qualitéit → `…-Q8_0.gguf` (12,7 GB, > 16 GB VRAM) |
| `TORCH_DTYPE` | `auto` = bf16 ab Ampere (RTX 30xx), fp16 op méi alen Kaarten. Schwaarz Biller → `float32` |
| `CPU_OFFLOAD` | `auto` schalt sech an, wann < 12 GB VRAM fräi sinn |
| `MAX_UPLOAD_MB` / `MAX_PENDING` | Upload-Limit (25 MB) a max. Jobs an der Schlaang (5) |
| `OUTPUT_TTL_HOURS` | Resultater ginn no 72 h geläscht |

## Wann eppes net geet
| Problem | Léisung |
|---|---|
| `CUDA out of memory` | `FLUX_GGUF_FILE: flux1-fill-dev-Q4_K_S.gguf` |
| Schwaarzt Bild | `TORCH_DTYPE: float32` |
| `401` / `gated repo` | FLUX-Lizenz net akzeptéiert oder Token falsch |

## CLI
```bash
docker compose exec pokemon-extender python -m app.cli /data/kaart.jpg -o /data/out --bleed-mm 2 --guides
# lokal ouni GPU, nëmmen d'Layout:
python -m app.cli kaart.jpg -o out --backend preview
```

## Lizenz
Code: MIT (`LICENSE`). D'Modell FLUX.1-Fill-dev huet seng eege
[Non-Commercial-Lizenz](https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev/blob/main/LICENSE.md).
Pokémon an d'Kaartebiller sinn © Nintendo / Creatures / GAME FREAK — dëse Projet huet näischt mat hinnen ze dinn.
