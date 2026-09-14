# MythologyMuse (M-U-S-E)

Bilingual mythology text pipeline on the Meta Muse model (text outputs only).
Ramayana (Dutt) is the first mythology; each mythology is self-contained in
its own folder and shares nothing mutable with the others.

## Layout

```
MythologyMuse/
  IMPLEMENTATION_PLAN.md     approved plan (this repo's build contract)
  README.md                  this file
  .env.example               copy to .env, add your MUSE_API_KEY (never commit .env)
  requirements.txt
  tools/                     shared STATELESS pipeline code (read-only at runtime)
    muse_client.py           Muse text adapter (Muse Spark 1.3, xhigh thinking)
  prompts/                   versioned prompt texts (per-mythology overrides allowed)
  mythologies/
    ramayana_dutt/           self-contained: sources, outputs, entities, config
      mythology.yaml
      sources/               frozen inputs (7 narrative JSONs, 652 chapters + SOURCE/)
      outputs/               generated text only (per-chapter dirs)
      entities/              entity_repository.json OWNED by this folder
```

## Quick start

```bash
cp .env.example .env        # add your MUSE_API_KEY
python3 tools/muse_client.py --smoke            # dry-run, no key needed
python3 tools/muse_client.py --mythology mythologies/ramayana_dutt \
    --chapter Book_1_Bala_Kanda_Chapter_1 --dry-run
```

## Add a new mythology

1. `cp -r mythologies/ramayana_dutt mythologies/<new_name>/`
2. Replace `sources/` with the new corpus, edit `mythology.yaml`,
   reset `entities/entity_repository.json` to `{"corpus": "<new_name>", ...}`,
   clear `outputs/`.
3. Run with `--mythology mythologies/<new_name>`. No shared code changes.

## Text model

Muse Spark 1.3 (contributor tier), thinking budget `xhigh` — see `.env.example`
(`MUSE_MODEL`, `MUSE_THINKING_BUDGET`). Image rendering is out of scope:
the pipeline emits image-prompt *text*; you render images separately.
