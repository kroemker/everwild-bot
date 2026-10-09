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
| Inventory display | No daily clutter: the bot edits one message per player in place in a character sheet channel (details in §16). |

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

## 9. Experience and levels ✅

### Game length

The game length is a setting chosen when a game is started (§15). XP amounts
stay the same; the length changes how much XP a level costs, so characters
reach the top level around the end of the game. World size and main quest
length scale with it too (§11, §13).

| Length | Target turns | XP per level | Level 10 at |
|---|---|---|---|
| Kurz | ~30 | 50 | 450 XP |
| Mittel | ~60 | 100 | 900 XP |
| Lang | ~100 | 170 | 1530 XP |

Exact numbers get tuned with the simulation script.

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

- **Flat**: every level costs the same XP (see the table above).
- **Max level 10**. At level 10 the character gets a title in their element
  (*Meisterin des Feuers*).

### What a level-up gives

Level-ups differ a lot between classes:

| Class | HP per level | Extra |
|---|---|---|
| Krieger | +5 | |
| Kleriker | +3 | |
| Waldläufer | +3 | |
| Schurke | +2 | |
| Barde | +2 | |
| Magier | +1 | *Arkaner Blitz* grows: d6 → d8 at level 4 → d10 at level 8 |

- **Attributes**: +1 at levels 3, 6 and 9. The player can name the attribute
  in any message; otherwise the class's main attribute is raised. Max +5.
- **Level 5**: second class ability (below).
- Risk to check in the simulation: a level-10 Magier has far fewer HP than a
  Krieger (17 vs. 59). Bosses must not kill the Magier in one hit.

### Second ability: choose 1 of 3

At level 5 each player picks one of three second abilities of their class.
All of them have a 3-turn cooldown, like the first ability.

- The player can name their choice in any message, also before level 5.
- When a character reaches level 5 without a choice, the chapter lists the
  three options. If the player hasn't chosen by the next turn, one is picked
  at random.

| Class | Option 1 | Option 2 | Option 3 |
|---|---|---|---|
| Krieger | *Unerschütterlich*: can't drop below 1 HP this turn; enemies attack the Krieger instead of the allies | *Wirbelwind*: attacks every enemy each round this fight | *Schlachtruf*: the whole group has advantage on attacks this fight |
| Waldläufer | *Spurlos*: the group moves past hostile creatures without a fight | *Pfeilhagel*: in round 1, a bow attack against every enemy | *Abkürzung*: the group travels two locations in one turn |
| Magier | *Elementarbarriere*: the group takes half damage in this turn's fight | *Teleport*: the group returns to any rest point they have visited | *Erkenntnis*: ask the narrator one question about the world and get a true answer |
| Kleriker | *Gruppenheilung*: heals every group member by half their max HP and wakes down characters | *Schutzsegen*: one ally can't drop below 1 HP this turn | *Bannkreis*: weak and normal enemies flee instead of fighting |
| Schurke | *Hinterhalt*: a free surprise round before the fight | *Meisterdieb*: steals one item from an NPC or enemy, guaranteed (the consequences come later) | *Rauchbombe*: the whole group escapes any fight, even a boss fight |
| Barde | *Heldenlied*: the whole group has advantage on all attacks and checks this turn | *Spottlied*: enemies have disadvantage on all attacks this fight | *Freund der Völker*: one people's attitude toward the group improves by one step, permanently |

### Element affinity

Affinity (§6) is a second, separate progression track. It does not come from
XP but from the world: shrines, teachers and quests of an element raise it
by 1 (max 3). The starting element begins at 1.

## 10. Death and resurrection ✅

A character dies when they reach 0 HP while alone, or when their whole group
is down (§7).

### Resurrection

- The character comes back **in the next turn** at the **last rest point
  they visited** (*Rastplatz*: settlements and shrines, §11), with full HP and
  all cooldowns reset.
- Their group may be somewhere else by then, so dying also costs the way back.
- If the whole group dies, enemies at that location recover fully.

### The grave

- **Half of the gold** (rounded up) and **half of the bag slots** (rounded up,
  chosen at random) stay behind as a **grave** at the place of death.
- **Not affected**: equipped items (weapon, armour, talisman) and quest items.
- Only the **owner** can recover the grave, by going there (a normal action
  at that location). Other players cannot loot it.
- If the owner dies again before recovering it, the old grave and its
  contents are **gone for good**; the new death creates a new grave.
- The grave is shown on the owner's character sheet (*Grab: Nebelsumpf, 23
  Gold, 3 Gegenstände*).

### Experience

- The level is kept. XP is reset to the start of the current level, so only
  the progress toward the next level is lost.

### No protection from death

No ability prevents death directly. The down-not-dead rule (§7) and the
healing abilities already work before it gets that far.

## 11. World, map and movement ✅

### Structure

- The world is a **graph**: locations connected by paths, grouped into **regions**.
- Each region has 1–2 elements (§6) and **4–6 locations**, among them at least
  one **rest point**.
- Plus a **start region** without element (a village and its surroundings)
  and a **final area** with an opposite element combination.
- World size scales with the game length (§9):

| Length | Regions (without start and final area) | Locations (approx.) |
|---|---|---|
| Kurz | 3 | ~20 |
| Mittel | 5 | ~32 |
| Lang | 8 | ~50 |

### Location types

| Type | What it offers |
|---|---|
| **Siedlung** | Safe. Merchants, inn (full HP), NPCs. Always a rest point. |
| **Schrein** | Rest point. Often raises affinity for its element (§6). |
| **Wildnis** | Paths, creatures, hidden things. |
| **Dungeon** | Ruins, caves, towers. Enemies, traps, loot. |
| **Hort** | The lair of a region boss. |

### Movement

- Moving to a **neighbouring location** is one action (one turn).
- No random encounters on the way. Creatures belong to locations.
- When players arrive at a location with hostile creatures, the narrator
  describes the threat. The **fight starts in the next turn**, so players can
  choose: fight, sneak past, talk, or go back. Exception: creatures marked as
  an ambush in the world file attack right away.
- **Following**: "Ich folge Mira" moves a player to wherever Mira goes this
  turn. Helps groups stay together.
- *Abkürzung* (Waldläufer, §9) moves the group two locations.

### Locked paths

A path between two locations can have a **requirement**, checked by Python:

- an item (key, artifact),
- a completed quest step or a defeated boss,
- an element affinity ("only someone at one with the air can cross the bridge of wind"),
- a class trait (the Schurke opens locks, the Magier reads runes),
- a check (a collapsed tunnel: STÄ, Schwer).

That is how the main quest controls the order of the regions (§13).

### Hidden paths and fog of war

- Players only know **discovered locations**, plus the names of neighbouring
  locations ("Ein Pfad führt nach Norden, zu den Nebelsümpfen").
- Some paths are **hidden** and only found by searching. The Waldläufer's
  passive trait gives advantage on it.
- The map knowledge is **shared by all players**. What one discovers, everyone knows.

### Generation and fixed descriptions

Everything is generated **once, when the game starts**, and then stays fixed.
The narrator describes from these texts instead of inventing a new look for a
location on every visit.

1. Python builds the **graph**: regions, locations, types, elements,
   connections, requirements, hidden paths. It checks that the main quest can
   be completed (§13).
2. The LLM fills it in, **one call per region**, so the locations of a region
   feel like they belong together:
   - **Region mood**: 3–4 sentences about landscape, colours, light, weather,
     sounds and smells, shared by all locations of the region.
   - Per location, a **fixed description**: 3–5 sentences of what it looks like.
   - Per location, **3–5 features** (*Merkmale*): concrete things that are
     permanently there ("ein eingestürzter Glockenturm", "ein Brunnen mit einer
     Bronzefigur", "ein Altar aus schwarzem Glas"). Hidden items and hidden
     paths are tied to a feature, so searching means searching *something*.
   - Creatures, important NPCs (§12) and important items, with names and descriptions.
3. Python validates the result (all fields present, names unique) and saves
   it in `world.json`.

### Rules for the narrator

- The narrator gets the region mood, the location description and the
  features, and must **reuse them**. It must not add new permanent features.
- It may add **passing details** (weather, sounds, a passing cart) that are
  not stored.
- **Changes from events** are stored as a **state note** on the location
  ("Die Brücke ist eingestürzt", "Das Dorf brennt"). The narrator gets the
  fixed description plus the state notes.
- Only the features, NPCs and items in the world file can be interacted with.
  The Interpret step maps "Ich untersuche den Brunnen" to the feature *Brunnen*.

### Map display

- Text first: the quest log message lists the discovered regions and
  locations and who is where.
- Later, as an optional addition: a generated map image (e.g. with Graphviz)
  that the bot attaches to the quest log message.

## 12. NPCs and dialogue ✅

### Important and minor NPCs

- **Important NPCs** are generated with the world (§11): about 2–4 per
  settlement, plus quest givers, teachers at shrines and figures from the
  lore. They are stored in `world.json`.
- **Minor NPCs** (passers-by, guards, customers in the inn) are invented by
  the narrator on the spot and not stored. If a player keeps talking to one,
  they are stored as a minor NPC from then on.

### What an important NPC has

| Field | Example |
|---|---|
| Name, people, location | Ulma Krähenfeder, Aschvolk, Glutmarkt |
| Role | Händlerin, Questgeberin, Lehrerin, Wächterin, … |
| Appearance | One or two sentences, fixed |
| Personality | "Gierig, aber ehrlich. Hasst Magier." |
| **Way of speaking** | "Redet ohne Punkt und Komma, verkauft alles als *Rarität*." |
| **Knowledge** | A list of facts the NPC can reveal ("Der Schlüssel zum Turm liegt beim Sumpfkönig") |
| Wants | What the NPC wants (a reason for side quests) |
| Attitude | Toward the players, on a 5-step scale (below) |
| Memory | Short notes about what happened with players |

The **way of speaking** is where humour comes in: some NPCs are funny, but the
narrator around them stays serious (§1).

### Knowledge controls what NPCs can say

An NPC can only reveal facts from their **knowledge** list, plus general
local colour. This stops the narrator from inventing hints that contradict
the world file. The Barde's passive trait gives extra hints from the lore.

### Attitude

- 5 steps: *feindlich*, *misstrauisch*, *neutral*, *freundlich*, *verbündet*.
- The default comes from the NPC's people (§6).
- It changes through events and checks (persuading, helping, insulting).
  The Barde's *Betören* and *Freund der Völker* (§9) work on it.
- Effects: hostile NPCs don't talk and may attack; friendly ones give
  discounts and more knowledge; allies give help or items.

### Conversations

- Talking is an action: the player writes what they say or ask.
- The NPC answers in the chapter, **one exchange per turn**. A conversation
  can go on over several days.
- Because each exchange takes a day, NPCs answer **generously and
  completely**: no "come back tomorrow" teasers, and as many facts per answer
  as the question allows.

### Memory

- After each scene, the LLM can add short memory notes to an NPC ("Brakka
  hat ihn beim Würfelspiel betrogen"). Python stores the last 10 per NPC.
- The notes are sent along when a player meets the NPC again.

### Companions

No NPC companions in the first version. They would need their own combat
and decision rules. Possible later.

### Can NPCs die?

- Players can attack NPCs (no PvP only means player against player). It has
  consequences: the attitude of the NPC's people drops, guards react.
- NPCs that the main quest depends on are **indispensable**: they flee or
  are knocked out, but never die.

### Merchants

- Each merchant has a fixed **stock list** from the item catalog (§8),
  chosen at generation to fit the region and its elements.
- The stock never runs out.

## 13. Quests and the path to the end ✅

### The main quest: element shards

- At game start, the LLM writes the **premise**: a threat to the world and
  why it can only be stopped in the final area. Example: the old seal that
  holds back a dark power is breaking; it can only be renewed with the
  shards of the elements.
- Every element region (§11) has a **region boss** in its *Hort*, who guards
  a **shard** (*Splitter*), a quest item of the region's element.
- A shard is **not carried by a player**. When a boss is defeated, its shard
  goes straight to the shared **seal** (*Siegel*) and counts for everyone. So a
  player who stops playing can never block the main quest with a shard in
  their bag. (💡 proposed together with §14, to be confirmed.)
- Locks that need shards check the shared count ("Die Brücke erscheint erst,
  wenn zwei Splitter im Siegel ruhen").
- The **gate to the final area** opens when enough shards are in the seal. Not all shards are required, so players can skip a region that is
  too hard:

| Length | Element regions | Shards needed |
|---|---|---|
| Kurz | 3 | 3 |
| Mittel | 5 | 4 |
| Lang | 8 | 6 |

### Order of the regions

- **Act 1**: the start region. A short intro quest that teaches the basics
  (talking, a first fight, a first check) and ends with learning the premise.
  Then **two regions** are open.
- **Act 2**: the element regions. Each region has a **level** that scales its
  enemies (§7). Shards of earlier regions (or items found there) unlock paths
  to later ones (§11). The order is a branching tree, not a line, so split
  groups can work on different regions at the same time.
- **Act 3**: the final area and the final boss.
- Python generates the region order and checks that the game can be won:
  every requirement can be met before the lock it opens, and no shard is
  locked behind itself.
- The danger of a region is shown in words, not as a number ("Die Wesen
  hier wirken uralt und gefährlich").

### Quest steps

Every quest is a list of **steps**, each with a condition that Python can check:

| Condition | Example |
|---|---|
| Have an item | "Besitze den Mondschlüssel" |
| Defeat a creature | "Besiege den Sumpfkönig" |
| Reach a location | "Erreiche die Wolkenbrücke" |
| Talk to an NPC | "Sprich mit Ulma Krähenfeder" (the Interpret step reports it) |
| Bring an item to an NPC | "Bringe das Siegel zu Bruder Orm" |

A typical region main quest has 2–3 steps: learn where the boss is (from an
NPC's knowledge, §12), get past the requirement on the way to the *Hort*,
defeat the boss and take the shard.

### Side quests

- **Generated with the world**, from the NPCs' wishes (§12): 1–2 per region.
  No side quests invented during the game.
- Rewards come from a fixed table: gold, a catalog item, **an affinity
  increase** (§6) or a better attitude of a people.
- A side quest is accepted by talking to the NPC. Every player in the group
  takes part.

### The quest log

The pinned quest log message (§16) shows, for all players together:

- shards collected (x of y needed);
- the known steps of the main quest;
- known side quests, and who has accepted them;
- the discovered map (§11).

### The finale

- When the gate opens, **every active player** is brought to the rest point
  of the final area in the next turn ("Die Splitter rufen euch"). Everyone
  takes part in the finale, wherever they were.
- The **final boss** has 2–3 phases, each in a different element, so the
  group needs varied elements. Each phase is a normal fight (§7) of up to 3
  rounds, so the finale takes several turns.
- If the whole group dies, the normal death rules apply (§10) and they try again.

### The end

- When the final boss is defeated, Python marks the game as **finished**.
- The LLM writes the **epilogue**: what became of the world and of each
  character, based on the chronicle.
- After that, a **statistics post**: most enemies defeated, most deaths, most
  gold, most items given away, most idle days, …
- The daily workflow stops resolving turns. The state stays in the repo.

## 14. Joining, idling and leaving 💡

### Joining

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

### Idling

A player is **idle** in a turn if they wrote nothing since the last turn.

- **In a group**: the idle character goes along when the group moves. If the
  group splits, the idle character stays where they are.
- **In a fight**: they defend themselves (§7).
- **Alone**: nothing happens. The world waits (§1), so an idle character on
  their own is never attacked.
- Idle characters get no XP (§9) and use no items or abilities.
- Idle players in a group are still mentioned in the chapter (§3), as a
  gentle reminder.

### Camp

- After **3 idle turns in a row**, the character goes to **camp**: they leave
  their group, are safe, don't appear in the chapter and are not mentioned.
- The character sheet shows *Im Lager*.
- **Coming back**: as soon as the player writes again, the character returns
  in the same turn, and the action is carried out right away. The player
  chooses where: where they left, or **with another player** ("Ich stoße
  wieder zu Mira"). This one-time return to a friend is free, so coming back
  after a holiday is easy.
- Together with the catch-up bonus (§9), a returning player is never stuck far behind.

### Leaving for good

- A player can leave by writing it in plain language ("Ich verlasse das
  Abenteuer"). The character gets a short farewell scene in the next chapter.
- Their items stay with the character. Shards are never in a player's bag
  (§13), so leaving can't block the main quest.
- The character is kept in the repo. The player can come back any time, like
  coming back from camp.

### Player limit

- At most **10 characters** that have not left. Characters in camp count.
- An 11th join attempt gets a short out-of-character note in the chapter:
  *Das Abenteuer ist voll.*

## 15. Starting a game 💡

Details of world generation follow in §11–§13. The flow:

- A separate GitHub workflow **"Neues Spiel"**, started by hand with the
  "Run workflow" button. Inputs:
  - **Spiellänge**: Kurz / Mittel / Lang (§9).
  - **Thema** (optional): a short hint for the world generator ("eine
    Inselwelt", "ein Reich im ewigen Winter"). Empty = the generator decides.
- If a game is still running, the workflow refuses to start unless the
  "Altes Spiel archivieren" checkbox is set. The old game is then moved to
  `archive/<date>/`, so nothing is lost.
- The workflow generates the world (`world.json`), commits it and posts:
  - a **prologue** in `#abenteuer` that sets the scene;
  - the pinned **So spielst du mit** message (classes, elements, an example
    join message);
  - the quest log message.
- Players join in plain language (§14) any time after the prologue. The first
  regular turn runs the next evening.

## 16. Discord output ❓

💡 Channels:

- `#abenteuer`: player actions and the bot's daily chapter.
- `#charakterbögen` (read-only): one message per player, edited in place every turn.
- The quest log / world map as one pinned message that gets edited.

Open questions:

- Structure of the daily post (one message or one embed per group, headers, mentions).
- Discord's length limits (2000 characters per message, 4096 per embed description).
- Whether players get pinged when something important happens to them.

## 17. State files and technical setup 💡

Proposed repository layout:

```
data/
  world.json         # the whole generated world, fixed (plus state notes on locations)
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

## 18. Prompting and LLM safety 💡

- Player text is always treated as an *attempt*, never as a fact ("Ich finde ein legendäres Schwert" does not create one).
- The Resolve step returns structured JSON only; Python validates all state changes.
- Prompts are written in German; names in the JSON are German too, so they stay consistent.
- The narrator uses "ihr" for the group and "du" for single players (to confirm).
