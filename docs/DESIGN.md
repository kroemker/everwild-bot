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
| Death | Players are resurrected but lose part of their loot (details in §10). |
| Inventory display | No daily clutter: the bot edits one message per player in place in a character sheet channel (details in §15). |

---

## 2. Glossary

| Term | Meaning |
|---|---|
| **Turn** (*Runde*) | One daily bot run. Collects all actions since the last turn and resolves them. |
| **Action text** | Everything a player wrote in the adventure channel since the last turn. |
| **Action** (*Aktion*) | The one action type (with parameters) the LLM maps an action text to, executed by Python. |
| **Scene** (*Szene*) | What happens to one group of players during a turn. |
| **Group** (*Gruppe*) | All active players at the same location during a turn. |
| **Location** (*Ort*) | A node on the world map. |
| **World skeleton** | The fixed structure generated at game start: map, main quest, bosses, key NPCs, key items. |

---

## 3. The turn cycle ✅

### Timing

- One turn per day in the **evening, around 20:00 German time**. Players read
  the chapter in the evening and write their next action during the following day.
- GitHub cron is UTC, so the turn shifts by one hour with summer/winter time.
  Runs can also be delayed by 15–60 minutes. Both are acceptable.
- `workflow_dispatch` lets the game master trigger a turn manually (e.g. for testing).
- A `paused` flag in `state.json` skips turns (e.g. during holidays).

### What counts as an action

- Every message from a player in `#abenteuer` since the last turn is part of their action.
- Messages starting with `//` are ignored (out-of-character talk). Longer chats
  should go to a separate channel.
- All messages of one player since the last turn are combined in order. Later
  messages can add to or correct earlier ones ("Korrektur: …"); the LLM interprets that.
- Players with no messages are idle.

### One action = one thing

- The LLM maps each player's text to **exactly one action from a fixed list of
  action types** (e.g. move, attack, talk, use item, give item, search, rest).
  The action types and their exact rules are defined together with the
  mechanics in the following sections.
- The action is then carried out **deterministically by Python** (dice rolls,
  damage, item transfer, movement). The LLM only interprets the text beforehand
  and narrates the result afterwards.
- If a player writes several steps ("I go to the city, buy a sword and kill the
  dragon"), only the first reasonable step happens. The narrator stops there.
- If the text can't be mapped to any valid action (impossible, or the item
  doesn't exist), the action fails or becomes the closest sensible action, and
  the narrator explains why.

### Groups

- All active players at the same location form a group and are resolved
  together in one scene, so they can work together.
- If a player moves away, the group splits from the next turn on.

### Steps of one bot run

1. Read all new messages in `#abenteuer` since `last_processed_message_id`.
2. Handle meta commands (join, etc.).
3. Combine each player's messages into one action text. Players with no messages are idle.
4. Group players by location.
5. For each group: **Interpret** — the LLM maps each action text to one action
   type with parameters (structured JSON).
6. For each group: **Execute** — Python validates the actions, rolls dice and
   updates the state.
7. For each group: **Narrate** — the LLM writes the German text from the
   executed outcome.
8. **Commit the state** (including the turn number and the new
   `last_processed_message_id`).
9. Post the chapter to `#abenteuer`, marked with the turn number.
10. Edit the character sheets and the quest log message.

### Safe to re-run

The state is committed *before* posting. Each chapter post contains its turn
number. On start, the bot checks whether the chapter for the turn already in
the state was posted. If not, it posts that chapter (stored in
`chronik/tag-NNN.md`) instead of resolving a new turn. That way a crashed run
never resolves a turn twice or posts it twice.

### The daily post

- A short opening line with the day number (*Tag 12*).
- One section per group, headed by the location name.
- Each player's name is in bold where their part begins.
- Each active player is **@mentioned once per turn**, so they get a notification.

## 4. Characters, classes and stats ✅

### Stats

- **HP** (*Lebenspunkte*), **level** (*Stufe*), **XP** (*Erfahrung*), **gold**.
- 3 attributes: *Stärke* (STÄ), *Geschick* (GES), *Verstand* (VER). Each value
  is added directly to dice rolls, usually between 0 and +3. No 3–18 scale.
- Stats are fixed per class. No point-spending at character creation.

### Design rule: every class must work alone

Players' paths can split, so no class may depend on others to survive. Each
class can do a bit of everything and is especially good at one thing.

### Classes

| Class | STÄ / GES / VER | HP | Active ability | Passive trait |
|---|---|---|---|---|
| **Krieger** | +3 / +1 / 0 | 14 | *Wuchtschlag*: one attack that hits for sure and does double damage | +1 armour, can use heavy weapons and armour |
| **Waldläufer** | +1 / +3 / 0 | 11 | *Gezielter Schuss*: a ranged attack before the fight starts | Tracking and finding hidden paths, bonus when travelling |
| **Magier** | 0 / +1 / +3 | 8 | *Feuerball*: damage to all enemies, ignores armour | Can read runes, magic scrolls and arcane objects |
| **Kleriker** | +1 / 0 / +2 | 12 | *Heilung*: heals self or an ally at the same location | When the group rests, everyone recovers extra HP |
| **Schurke** | 0 / +3 / +1 | 10 | *Schattenschritt*: sneaking, stealing or a stab from behind succeeds automatically | Opens locks and spots traps |
| **Barde** | 0 / +1 / +2 | 10 | *Betören*: one conversation with an NPC succeeds automatically (convince, bluff, get a discount) | Knows legends; the narrator gives extra hints about the world |

- Players choose the word form of their class name (e.g. *Waldläuferin*, *Klerikerin*).
- The same class may be taken by several players.
- Starting gear per class: defined together with items (§8).
- Exact numbers (HP, damage) may still be adjusted once dice and combat (§5, §7) are decided.

### Abilities and cooldown

- No mana or stamina.
- Each active ability has a **cooldown of 3 turns** after use.
- Using an ability counts as the player's one action for the turn.
- The character sheet shows the state: *Feuerball: bereit* / *Feuerball: bereit in 2 Tagen*.
- A **second ability** is unlocked at a higher level (e.g. level 5), defined with §9.

### What a player chooses

- **Name**, **class**, and optionally **one sentence** about appearance or
  background. The sentence is pure flavour that the narrator uses; it has no
  effect on the rules. (Someone who wants to be "ein Drache in Menschengestalt"
  can be that here, as a Krieger.)

## 5. Checks and dice ✅

- **d20 + attribute** against a target number.
- Not every action needs a roll. A roll is only needed when the outcome is
  uncertain *and* failing would be interesting. Walking down a road or talking
  to a friendly innkeeper just happens.
- The LLM decides whether a roll is needed, **which attribute** is used (forcing
  a door: STÄ, picking a lock: GES, deciphering a scroll: VER) and picks **one of
  four difficulty levels**. Python looks up the number and rolls.

| Difficulty | Target number | Example |
|---|---|---|
| Leicht | 8 | Climbing a low wall |
| Mittel | 12 | Picking a simple lock |
| Schwer | 16 | Convincing a suspicious guard |
| Heroisch | 20 | Jumping across a gorge |

- **Criticals**: a natural 20 always succeeds and gives a bonus. A natural 1
  always fails with a mishap, which is unpleasant but never deadly on its own.
- **Advantage / disadvantage**: roll two d20 and keep the higher / lower. Used
  instead of many small modifiers:
  - a player helps another player;
  - class traits (e.g. the Waldläufer when travelling);
  - good items, element matchups (§6) or smart ideas give advantage;
  - bad conditions give disadvantage.
  - Advantage and disadvantage cancel each other out; they don't stack.
- **Erfolg mit Haken**: missing the target by 1–2 is a success with a
  complication (you get through the door, but the guards heard you).
- **Retrying**: a failed check can be retried the next day unless the story
  rules it out (the lock jammed, the guard now knows you). The LLM decides that
  as part of the consequence.
- **Showing rolls**: each player's part ends with one line in Discord subtext
  format, e.g. `-# 🎲 Brakka: 14 + 3 = 17 gegen 12 → Erfolg`.

## 6. Elements ✅

Elements are a shared vocabulary for places, peoples, creatures, items and
characters. They give the world generator structure (a consistent world
instead of random details) and give players a reason to explore and prepare
("the boss of the Glutberge is a fire creature, so we need a water weapon").

### The elements

| Element | Emoji | Also covers |
|---|---|---|
| Feuer | 🔥 | Hitze, Lava, Glut |
| Wasser | 💧 | Eis, Frost, Meer, Nebel |
| Erde | 🪨 | Stein, Pflanzen, Gift |
| Luft | 🌪️ | Sturm, Blitz, Klang |
| Licht | ☀️ | Heiliges, Heilung, Sonne |
| Schatten | 🌑 | Dunkelheit, Tod, Fluch |
| Stahl (no element) | ⚔️ | Plain weapons and mundane things |

The "also covers" column lets the narrator say *Frostklinge* or *Blitzpfeil*
while the rules only know the six elements.

### Matchups

Three pairs of opposites: **Feuer ↔ Wasser, Erde ↔ Luft, Licht ↔ Schatten**.

- Attacking with the **opposite** element of the target: advantage on the attack
  and +50 % damage.
- Attacking with the **same** element as the target: half damage.
- **Stahl** is neutral against everything: never strong, never resisted.
- Python looks up the matchup. The LLM only tags things with an element from the fixed list.

### Characters

- At joining, each player picks a **starting element** (or Stahl). Together with
  the class this gives 6 × 7 combinations (*Schattenkrieger*, *Lichtmagierin*, …).
- A character's **class ability takes their element**: a water Magier's
  *Feuerball* becomes a wave, a shadow Krieger's *Wuchtschlag* is a blow of
  darkness. Same rules, different flavour and matchups.
- **Affinity** per element, level 0–3:
  - +affinity on rolls where that element is used;
  - damage of that element against the character is halved from affinity 2;
  - at most 2 elements with affinity per character, and never two opposites.
- Affinity grows through the world (shrines, teachers, quests), not by
  grinding. Details with experience and levels (§9).

### World

- Every **region** has 1–2 elements, which decide its look and contents:
  Feuer + Erde = volcanic mountains, Wasser + Schatten = swamp or deep sea,
  Luft + Licht = sky islands, Erde + Schatten = caves and the underworld, …
- With 6 elements there are 6 single regions and 12 pairs (the 3 pairs of
  opposites excluded). Opposite combinations (Feuer + Wasser = steam springs)
  are reserved for special places, e.g. the final area.
- **Peoples and creatures** are generated from element combinations as well and
  usually live in regions of their elements. Each people has an attitude toward
  the players.
- **Items** (weapons, armour, scrolls, potions) can carry an element. Enemies have 1–2 elements.

### Decided

- Exactly the 6 elements above plus Stahl. No further elements.
- Matchups use the three pairs of opposites, not a cycle.
- Each player picks a starting element (or Stahl) when joining. The starting
  element begins at affinity 1.
- A region's elements only decide what is **generated** there (look, peoples,
  creatures, items). They have no effect on fights or checks in that region.

## 7. Combat ✅

All numbers in this section are a first draft. Before launch they get tuned
with a small simulation script that plays thousands of fights.

### When a fight happens

- Hostile creatures at a location attack when players arrive, unless the
  players sneak past (GES check) or talk their way out.
- Players can also start a fight themselves (attack action).
- Hostile creatures are part of the world file, not invented on the spot.

### Fight rounds

- A fight runs for **up to 3 rounds per turn**, simulated by Python.
- Each player's action for the turn is their **tactic for the whole fight**
  ("Ich greife den Oger mit der Axt an", "Ich schütze Mira mit dem Schild").
  It is repeated every round.
- An active ability is used in the first round (then the cooldown starts).
- If enemies are still standing after 3 rounds, the fight continues next
  turn. Players can change tactics or flee. Bosses have enough HP that they
  usually take 2–3 turns; no special rule needed.

### Combat actions

| Action | Effect |
|---|---|
| **Angreifen** | Attack one enemy every round with the equipped weapon (or a basic spell). |
| **Fähigkeit** | Use the class ability in round 1, then attack normally. |
| **Verteidigen** | Attacks against yourself and one chosen ally have disadvantage. |
| **Heilen / Gegenstand** | Use a potion, scroll or healing in round 1, then defend. |
| **Fliehen** | GES check (Mittel). Success: back to the previous location. Failure: enemies get one free round against you. |

Idle players in a fight automatically **defend** themselves.

### Attacks and damage

- **Player attack**: d20 + attribute against the enemy's *Abwehr*. Melee uses
  STÄ, ranged GES, spells VER.
- **Damage**: weapon die + attribute. Draft dice: Dolch d4, Bogen d6,
  Schwert d8, Streitaxt d10 (two-handed).
- **Magier basic spell**: *Arkaner Blitz*, d6 + VER in the character's element.
  So the Magier can always attack without a weapon.
- **Elements** (§6): opposite element → advantage and +50 % damage; same
  element → half damage.
- **Enemy attack**: d20 + enemy attack bonus against the player's
  *Rüstungswert* = 10 + armour (+1 for Krieger).
- Enemies pick a random target in the group.

### Enemy stats

Enemies don't get freely invented numbers. The world file gives each enemy a
**tier**; Python looks up the stats and scales them by region level.

| Tier | Example | HP | Abwehr | Attack | Damage |
|---|---|---|---|---|---|
| Schwach | Ratte, Goblin | 4 | 10 | +2 | d4 |
| Normal | Wolf, Bandit | 8 | 12 | +3 | d6 |
| Stark | Oger | 16 | 13 | +4 | d8 |
| Elite | Hauptmann der Wache | 24 | 14 | +5 | d10 |
| Boss | Region boss | 40 per player | 15 | +6 | 2d6 |

- **Scaling with group size**: the number of enemies (and boss HP) scales
  with the number of players present, so a solo player and a group of six
  both get a fair fight.
- Enemy health is shown in words, not numbers ("Der Oger taumelt, schwer verwundet").

### 0 HP: down, not dead

- A character at 0 HP is **kampfunfähig** (down) and drops out of the fight.
- If the group wins (or flees successfully), down characters wake up with 1 HP.
- A healer can bring a down character back into the fight.
- A character only **dies** (§10) if the whole group is down, or if they are
  alone.

### Healing outside fights

- Resting (*Rasten*) is an action: recover half of max HP.
- At a rest point or inn: full HP. The Kleriker passive adds extra HP to a group rest.

## 8. Items, inventory and equipment ✅

### Where items come from

The LLM never invents an item with free stats. All items are built from an
**item catalog** (a JSON file we write by hand, like the classes): base types
with fixed rules. The LLM only gives them a name and a description.

1. **Unique items** (legendary items, quest items) are placed in the world
   file at world generation: at a location, with an NPC or carried by a boss.
2. **Loot** after fights and from chests: Python rolls gold and maybe an item
   from the catalog, based on enemy tier and the elements of the region. The
   LLM names it ("Rostiger Krummsäbel der Sumpfbanditen" = catalog *Schwert*,
   common, Stahl).
3. **Shops**: merchants in towns sell catalog items.

### Categories and equipment slots

Three equipment slots:

| Slot | Contents |
|---|---|
| **Waffe** | One weapon. A one-handed weapon can be combined with a shield (+1 Rüstungswert). |
| **Rüstung** | One armour. |
| **Talisman** | Amulet or ring: +1 affinity for one element (§6) or another small bonus. |

Everything else is carried in the bag:

- **Verbrauchsgut**: potions, scrolls, bombs. Used up on use.
- **Questgegenstand**: keys, artifacts, letters. Never lost, never sold.
- **Wertsachen**: gems, trophies. Only good for selling.

### Weapons and armour

| Weapon | Damage | Attribute | Notes |
|---|---|---|---|
| Dolch | d4 | STÄ or GES | Light |
| Rapier | d6 | STÄ or GES | Light |
| Streitkolben | d6 | STÄ | |
| Schwert | d8 | STÄ | |
| Streitaxt | d10 | STÄ | Two-handed, Krieger only |
| Bogen | d6 | GES | Ranged |
| Stab | d4 | STÄ | Magier: +1 on the Arkaner Blitz |

| Armour | Rüstungswert bonus | Who |
|---|---|---|
| Stoff | 0 | Everyone |
| Leder | +1 | Everyone |
| Kettenhemd | +2 | Krieger, Kleriker, Waldläufer |
| Plattenpanzer | +3 | Krieger only |

### Rarity

| Rarity | Bonus |
|---|---|
| Gewöhnlich | none |
| Selten | +1 to hit and damage (weapons) or +1 Rüstungswert (armour) |
| Legendär | +2, plus one special effect; only placed in the world file |

Weapons and armour can have an element (§6). Plain ones are Stahl.

### Consumables (draft)

- **Heiltrank**: restores half of max HP.
- **Schriftrolle** (Magier only): a one-time spell in the scroll's element,
  e.g. a damage spell against all enemies.
- **Elementöl**: coats a weapon with an element for one fight.
- No food, hunger or weight rules.

### Inventory limit

- **10 bag slots**. Consumables of the same kind stack up to 5 per slot.
- Equipped items and quest items don't count toward the limit.
- Gold has no limit.
- If the bag is full, new loot stays where it was found until the player
  makes room.

### Using, equipping, giving

- **Equipping** or swapping equipment is free and doesn't use the action
  ("Ich ziehe das Kettenhemd an und gehe zum Tor").
- **Using** a consumable is the action (in fights: in round 1, §7).
- **Giving** an item to a player at the same location is the giver's action.
  The receiver doesn't need to do anything.
- **Dropping** an item is free.

### Gold and shops

- Gold comes from loot, quests and selling.
- Merchants buy items at half their price. The Barde's *Betören* can get a discount.
- Prices come from the catalog by type and rarity.

### Starting gear

Every character also starts with **10 gold** and **1 Heiltrank**.

| Class | Weapon | Armour | Extra |
|---|---|---|---|
| Krieger | Schwert + Schild | Kettenhemd | |
| Waldläufer | Bogen, Dolch (in the bag) | Leder | |
| Magier | Stab | Stoff | 1 Schriftrolle in the character's element |
| Kleriker | Streitkolben | Kettenhemd | 1 extra Heiltrank |
| Schurke | Dolch | Leder | Dietriche (needed for locks) |
| Barde | Rapier | Leder | Laute |

## 9. Experience and levels 💡

### Game length

All numbers below assume a game of roughly **60 turns** (about two months).
They get tuned with the simulation script once the length is fixed.

### XP sources

Python hands out fixed amounts. The LLM only reports *what* happened (fight
won, quest done, location discovered, check passed).

| Event | XP | Who gets it |
|---|---|---|
| Fight won, per enemy tier | Schwach 5, Normal 10, Stark 20, Elite 40, Boss 100 | Every player who took part, full amount (not split) |
| Side quest completed | 30 | Every player who took part |
| Main quest step completed | 60 | Every player who took part |
| New location discovered | 5 | Every player in the group |
| Hard check passed | Schwer 5, Heroisch 10 | The player who rolled |

- Fights scale with group size (§7), so every player gets the full XP of the
  fight. Playing together is never worse than playing alone.
- Idle players get **no XP**.
- **Catch-up bonus**: players below the average level of all active players
  get +50 % XP. Helps late joiners and players who were away.

### Level curve

- **Flat**: every level needs 100 XP. Level = 1 + XP / 100, so 340 XP is level 4.
- **Max level 10** (900 XP). At level 10 the character gets a title in their
  element (*Meisterin des Feuers*).

### What a level-up gives

- **HP**: Krieger +4, Magier +2, all others +3.
- **Attributes**: +1 at levels 3, 6 and 9. The player can name the attribute
  in any message; otherwise the class's main attribute is raised. Max +5.
- **Level 5**: second class ability (with a 3-turn cooldown, like the first).

| Class | Second ability (level 5) |
|---|---|
| Krieger | *Unerschütterlich*: can't drop below 1 HP this turn; enemies attack the Krieger instead of the allies. |
| Waldläufer | *Spurlos*: the whole group moves past hostile creatures without a fight, no roll needed. |
| Magier | *Elementarbarriere*: the group takes half damage in this turn's fight. |
| Kleriker | *Gruppenheilung*: heals every group member by half their max HP and wakes down characters. |
| Schurke | *Hinterhalt*: the group gets a free surprise round before the fight starts. |
| Barde | *Heldenlied*: the whole group has advantage on all attacks and checks this turn. |

### Element affinity

Affinity (§6) is a second, separate progression track. It does not come from
XP but from the world: shrines, teachers and quests of an element raise it
by 1 (max 3). The starting element begins at 1.

## 10. Death and resurrection ❓

💡 Proposal from the brainstorm:

- Resurrection at the last visited rest point (*Rastplatz*), in the next turn.
- Half of the gold and non-quest items stay behind as a **grave** where the player died.
- The grave can be recovered; if the player dies again before that, it is lost. Other players can loot it too.
- Quest items are never lost, so the game stays winnable.
- Level is kept; progress toward the next level may be lost.

Open questions: confirm or change each point above.

## 11. World, map and movement ❓

💡 The skeleton is generated upfront and fixed; details of each location are
generated on first visit and then stored permanently.

Open questions:

- World size (number of regions and locations).
- How travel works (one location per turn? distances?).
- Whether a map is shown to players, and how.
- How split groups meet again.

## 12. NPCs and dialogue ❓

Open questions:

- How much an NPC remembers (a short memory field per NPC?).
- Whether NPCs can join the party as companions.
- How a conversation spanning several days works.

## 13. Quests and the path to the end ❓

Open questions:

- Structure of the main quest (e.g. 3 acts, key items that unlock the final area).
- Side quests: pre-generated or created on the fly.
- How the game recognizes that the final boss is beaten and the epilogue starts.

## 14. Joining, idling and leaving ❓

### Joining 💡

Problem: the bot only reads messages once a day, so it can't answer a wrong
join message right away. A typo or a class that doesn't exist must not cost
the player a whole day.

- A pinned message in `#abenteuer`, *So spielst du mit*, lists the classes
  and an example join message.
- Joining is written in plain language, no strict syntax ("Ich bin Brakka,
  eine Kriegerin. Eine vernarbte Söldnerin aus dem Norden."). The LLM extracts
  name, class and the background sentence.
- Synonyms are mapped to the nearest class ("Zauberer" → Magier,
  "Paladin" → Krieger). If the name is missing, the Discord display name is used.
- If no class matches ("Drache"), the character still joins **in this turn**
  as a *Wanderer* without a class: average stats, no ability. The narrator
  includes the player in the scene and adds a short out-of-character note
  listing the classes. The player names a class in any later message.
- **Class change**: during their first 3 turns, a player can switch class
  freely (also covers "I regret my choice"). After that the class is fixed.
- A join message can also contain the first action; it is carried out in the
  same turn.
- New characters start near the party, at the party's level minus 1.
- The join message also names a starting element (§6). If none is given, the
  LLM picks one that fits the background sentence, or Stahl. It can be changed
  during the first 3 turns, like the class.

### Idling and leaving 💡

- Idle players go along passively with their group.
- After several idle days, the character goes to camp.

Open questions: confirm or change the joining rules above; idle details; how a
player leaves permanently.

## 15. Discord output ❓

💡 Channels:

- `#abenteuer`: player actions and the bot's daily chapter.
- `#charakterbögen` (read-only): one message per player, edited in place every turn.
- The quest log / world map as one pinned message that gets edited.

Open questions:

- Structure of the daily post (one message or one embed per group, headers, mentions).
- Discord's length limits (2000 characters per message, 4096 per embed description).
- Whether players get pinged when something important happens to them.

## 16. State files and technical setup 💡

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

## 17. Prompting and LLM safety 💡

- Player text is always treated as an *attempt*, never as a fact ("Ich finde ein legendäres Schwert" does not create one).
- The Resolve step returns structured JSON only; Python validates all state changes.
- Prompts are written in German; names in the JSON are German too, so they stay consistent.
- The narrator uses "ihr" for the group and "du" for single players (to confirm).
