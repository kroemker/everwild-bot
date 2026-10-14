# Everwild

Ein asynchrones Fantasy-Textabenteuer für Discord: Die Spieler schreiben
tagsüber, was ihre Figuren tun, und einmal am Abend erzählt der Bot (über
einen GitHub-Actions-Cronjob und ein LLM), wie es weitergeht.

The full design is in [`docs/DESIGN.md`](docs/DESIGN.md); Discord layout
mockups are in [`docs/mockups/discord-output.html`](docs/mockups/discord-output.html).

## Status

All four build steps are done: rules engine, local play mode, world generation, Discord and workflows.
Not yet tested against real OpenAI and Discord (see *Setup*).

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
| Discord (REST client, messages, embeds, daily turn, new game) | `src/everwild/discord_api.py`, `discord_render.py`, `bot.py` |
| Workflows: daily turn, new game, tests | `.github/workflows/` |

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

## Setup

### 1. Discord bot

1. Create an application in the [Discord Developer Portal](https://discord.com/developers/applications),
   add a bot and copy its token.
2. Under **Bot**, enable the **Message Content Intent** (the bot reads what players write).
3. Invite the bot (OAuth2 → URL Generator, scope `bot`) with these permissions:
   View Channels, Read Message History, Send Messages, Embed Links, Add Reactions,
   Create Public Threads, Send Messages in Threads, Manage Threads (lock and reopen
   the Weltbuch thread), Manage Messages (pin), Manage Channels (channel topic).
   Granting them only on the adventure channel is enough.
4. Copy the channel ID (Developer Mode → right-click the channel → Copy Channel ID).

### 2. GitHub repository settings

- **Secrets** (Settings → Secrets and variables → Actions → Secrets):
  `DISCORD_BOT_TOKEN`, `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY`).
- **Variables** (same page → Variables): `ADVENTURE_CHANNEL_ID`; optional
  `LLM_PROVIDER` (`openai`, default, or `anthropic`), `OPENAI_MODEL`, `CLAUDE_MODEL`.
- The workflows commit the game state, so Actions needs write access
  (Settings → Actions → General → Workflow permissions → Read and write).

### 3. Play

- **Neues Spiel** (Actions → Neues Spiel → Run workflow): pick the length and an
  optional theme. Posts the prologue, the pinned *So spielst du mit* message
  with the 📖 Weltbuch thread, and sets the channel topic. Tick *Altes Spiel
  archivieren* to replace a running game (it moves to `archive/`).
- **Tagesrunde** runs every evening at about 20:00 German time. *Run workflow*
  starts a turn by hand; *Probelauf* posts and saves nothing and shows the
  chapter in the run summary.
- Pause: set `"paused": true` in `game/state.json`.
- GitHub disables scheduled workflows after 60 days without commits; after a
  long break, re-enable *Tagesrunde* under Actions.
- If a run fails after saving, the next run posts the saved chapter instead of
  playing the day again.

A good first test: create a private test channel, set its ID, start a *kurz*
game and write a few actions yourself before inviting the others.
