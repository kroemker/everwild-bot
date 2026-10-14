# Everwild

Ein asynchrones Fantasy-Textabenteuer für Discord: Die Spieler schreiben
tagsüber, was ihre Figuren tun, und einmal am Abend erzählt der Bot (über
einen GitHub-Actions-Cronjob und ein LLM), wie es weitergeht.

The full design is in [`docs/DESIGN.md`](docs/DESIGN.md); Discord layout
mockups are in [`docs/mockups/discord-output.html`](docs/mockups/discord-output.html).

## Status

Build step 1 of 4 is done: the rules data and the rules engine.

| Part | Where |
|---|---|
| Rules data (classes, abilities, items, enemies, item name words) | `catalog/` |
| Rules engine (dice, elements, characters, items, combat, death) | `src/everwild/rules/` |
| Tests | `tests/` |
| Combat balancing simulation | `sim/combat_sim.py` |

Next: local play mode, world generation, then Discord and the workflows.

## Development

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
.venv/bin/python sim/combat_sim.py --fights 1000
```
