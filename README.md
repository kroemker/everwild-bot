# Everwild

Ein asynchrones Fantasy-Textabenteuer für Discord: Die Spieler schreiben
tagsüber, was ihre Figuren tun, und einmal am Abend erzählt der Bot (über
einen GitHub-Actions-Cronjob und ein LLM), wie es weitergeht.

The full design is in [`docs/DESIGN.md`](docs/DESIGN.md); Discord layout
mockups are in [`docs/mockups/discord-output.html`](docs/mockups/discord-output.html).

## Status

Build steps 1–3 of 4 are done: the rules engine, the local play mode and world generation.

| Part | Where |
|---|---|
| Rules data (classes, abilities, items, enemies, item name words) | `catalog/` |
| Rules engine (dice, elements, characters, items, combat, death) | `src/everwild/rules/` |
| Tests | `tests/` |
| Combat balancing simulation | `sim/combat_sim.py` |
| Turn engine (joins, actions, fights, rewards, camp) | `src/everwild/engine.py` |
| Interpret / narrate (OpenAI or offline fallback) | `src/everwild/interpret.py`, `narrate.py`, `prompts/` |
| Local play mode | `src/everwild/play_local.py` |
| Hand-written test world | `examples/testwelt.json` |
| World generation (skeleton, naming, checks), quests, seal, finale | `src/everwild/worldgen.py`, `catalog/worldgen.json` |

Next: Discord and the GitHub workflows.

## Playing locally

```sh
PYTHONPATH=src python -m everwild play            # uses OpenAI if OPENAI_API_KEY is set
PYTHONPATH=src python -m everwild play --offline  # keyword interpreter + plain narration
PYTHONPATH=src python -m everwild play --neu --generieren --length kurz --thema "eine Inselwelt"
```

Type `name: what the character does` (a new name joins the game), an empty
line ends the day. `:bogen NAME` shows a character sheet, `:karte` the map,
`:quests` the quest log, `:hilfe` all commands. The game is saved in `lokales-spiel/`; `--neu` starts over.
`examples/testrunde.txt` is a scripted example (`--script examples/testrunde.txt`).

Settings (environment variables): `LLM_PROVIDER` (`openai` or `anthropic`),
`OPENAI_API_KEY`, `OPENAI_MODEL`, `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`.

## Development

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
.venv/bin/python sim/combat_sim.py --fights 1000
```
