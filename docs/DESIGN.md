# Everwild – Design Document

A German-language, text-based fantasy RPG played asynchronously in a Discord
channel. Players post their character's action during the day; once a day a
GitHub Actions cron job runs the bot, which resolves all actions with an LLM,
posts the next chapter of the story and commits the updated game state back
to this repository.

Legend for the status of each section:

- ✅ **Decided**: agreed on, build it this way.
- 💡 **Proposal**: suggested default, not yet discussed in detail.
- ❓ **Open**: needs a decision before it gets built.

---

## 1. Fixed decisions

| Topic | Decision |
|---|---|
| Language | All player-facing text is German. |
| Hosting | No always-on server. A GitHub Actions cron job runs once per day, plus `workflow_dispatch` for manual turns. |
| Discord access | Plain REST API calls (read messages, post, edit). No gateway connection. |
| LLM access | Same setup as [meme-bot](https://github.com/kroemker/meme-bot): a small `llm_client.ask()` wrapper that switches between Anthropic and OpenAI. |
| Persistence | Game state is JSON in this repo, committed by the workflow after each turn. |
| Repo visibility | Public. Spoilers in `world.json` are accepted. |
| Players | Any number, capped at **10**. Players can join late. |
| Classes | A fixed set of classes that we define upfront (see §4). |
| PvP | None. Players cannot attack each other. |
| Giving items | A player can give an item to another player at the same location, as a normal action. No trading system. |
| World clock | The world waits for the players. Nothing happens on its own between turns. |
| Tone | Narrator: classic, serious high fantasy. NPCs speak in their own voice; some are allowed to be funny. |
| Game end | After the final boss: an epilogue, then the game is over. The state stays in the repo. |
| Death | Players are resurrected but lose part of their loot (details in §9). |
| Inventory display | No daily clutter: the bot edits one message per player in place in a character sheet channel (details in §12). |

---

## 2. Glossary

| Term | Meaning |
|---|---|
| **Turn** (*Runde*) | One daily bot run. Collects all actions since the last turn and resolves them. |
| **Action** (*Aktion*) | Everything a player wrote in the adventure channel since the last turn. |
| **Scene** (*Szene*) | What happens to one group of players during a turn. |
| **Group** (*Gruppe*) | All active players at the same location during a turn. |
| **Location** (*Ort*) | A node on the world map. |
| **World skeleton** | The fixed structure generated at game start: map, main quest, bosses, key NPCs, key items. |

---

## 3. The turn cycle ❓

What happens in one bot run, in order. This is the core of the whole system.

1. Read all new messages in the adventure channel since `last_processed_message_id`.
2. Handle meta commands (join, etc.).
3. Merge each player's messages into one action. Players with no messages are idle.
4. Group players by location.
5. For each group: **Resolve** (LLM returns a structured JSON outcome) →
   **validate and apply** (Python checks it against the rules, rolls dice, updates the state).
6. For each group: **Narrate** (LLM writes the German text from the checked outcome).
7. Post the chapter to the adventure channel.
8. Edit the character sheets and the quest log message.
9. Commit the state and the chronicle.

Open questions:

- Time of day for the turn (keep in mind that GitHub cron is UTC and can be delayed).
- What counts as an action: every message in the channel, or only some? How do players chat out of character?
- How several messages from the same player are combined (all together, or the last one wins).
- Order of steps 7 and 9, so that a failed run can be safely repeated.

## 4. Characters, classes and stats ❓

💡 Keep it small:

- **HP** (*Lebenspunkte*), **level** (*Stufe*), **XP** (*Erfahrung*), **gold**.
- 3 attributes: *Stärke*, *Geschick*, *Verstand*.
- One class ability per class, maybe a second one at a higher level.

Open questions:

- The list of classes, their starting stats, starting gear and abilities.
- Whether there are resources like mana or stamina, or whether abilities are limited per turn or per rest.

## 5. Checks and dice ❓

💡 The LLM decides *whether* a check is needed and how hard it is; Python rolls
the dice. Rolls are shown in the text (🎲 17 + 2 = 19 → Erfolg).

Open questions:

- Which die (d20, 2d6, …) and how difficulty levels map to numbers.
- Critical successes and failures.

## 6. Combat ❓

💡 One turn = one scene. A normal fight is resolved in one turn based on each
player's stated tactics. A boss fight takes at most 2–3 turns.

Open questions:

- How enemy stats look and how damage is calculated.
- Whether players can flee.
- What idle players do in a fight.

## 7. Items, inventory and equipment ❓

Open questions:

- Item categories (weapon, armour, consumable, quest item, miscellaneous), and whether equipment slots exist.
- Inventory limit.
- Gold and shops.
- Which items the LLM may create freely and which must come from the world file.
- Giving items: already decided as a normal action. Is it limited to players at the same location?

## 8. Experience and levels ❓

Open questions:

- What gives XP (fights, quests, exploration, good ideas?).
- Whether XP is shared within a group.
- Level curve, max level, what a level-up gives.

## 9. Death and resurrection ❓

💡 Proposal from the brainstorm:

- Resurrection at the last visited rest point (*Rastplatz*), in the next turn.
- Half of the gold and non-quest items stay behind as a **grave** where the player died.
- The grave can be recovered; if the player dies again before that, it is lost. Other players can loot it too.
- Quest items are never lost, so the game stays winnable.
- Level is kept; progress toward the next level may be lost.

Open questions: confirm or change each point above.

## 10. World, map and movement ❓

💡 The skeleton is generated upfront and fixed; details of each location are
generated on first visit and then stored permanently.

Open questions:

- World size (number of regions and locations).
- How travel works (one location per turn? distances?).
- Whether a map is shown to players, and how.
- How split groups meet again.

## 11. NPCs and dialogue ❓

Open questions:

- How much an NPC remembers (a short memory field per NPC?).
- Whether NPCs can join the party as companions.
- How a conversation spanning several days works.

## 12. Quests and the path to the end ❓

Open questions:

- Structure of the main quest (e.g. 3 acts, key items that unlock the final area).
- Side quests: pre-generated or created on the fly.
- How the game recognizes that the final boss is beaten and the epilogue starts.

## 13. Joining, idling and leaving ❓

💡 Proposal from the brainstorm:

- Joining: `!beitreten <Name> <Klasse>`; the character is created at the next turn, placed near the party, starting at the party's level minus 1.
- Idle players go along passively with their group.
- After several idle days, the character goes to camp.

Open questions: confirm or change each point above; how a player leaves permanently.

## 14. Discord output ❓

💡 Channels:

- `#abenteuer`: player actions and the bot's daily chapter.
- `#charakterbögen` (read-only): one message per player, edited in place every turn.
- The quest log / world map as one pinned message that gets edited.

Open questions:

- Structure of the daily post (one message or one embed per group, headers, mentions).
- Discord's length limits (2000 characters per message, 4096 per embed description).
- Whether players get pinged when something important happens to them.

## 15. State files and technical setup 💡

Proposed repository layout:

```
data/
  world.json         # skeleton + locations discovered so far (mostly fixed)
  state.json         # turn counter, last message ID, groups, graves, message IDs
  players/<id>.json  # one file per player
chronik/
  tag-001.md         # readable chronicle, one file per turn
src/                 # bot code (Python)
.github/workflows/
  turn.yml           # daily cron + workflow_dispatch
```

- The context sent to the LLM stays small: the world skeleton (prompt caching),
  the current location, each player's last few turns and a running summary.
- A `concurrency:` group in the workflow prevents two runs at once.
- A dry-run mode for testing that posts nothing and commits nothing.

## 16. Prompting and LLM safety 💡

- Player text is always treated as an *attempt*, never as a fact ("Ich finde ein legendäres Schwert" does not create one).
- The Resolve step returns structured JSON only; Python validates all state changes.
- Prompts are written in German; names in the JSON are German too, so they stay consistent.
- The narrator uses "ihr" for the group and "du" for single players (to confirm).
