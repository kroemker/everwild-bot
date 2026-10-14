import pytest

from everwild.rules import items as it


def test_adjectives_agree_with_gender(catalog, rng):
    names = {it.generate_name(catalog, rng, "streitaxt", "gewoehnlich", "stahl") for _ in range(60)}
    adjective_names = [n for n in names if " " in n]
    assert adjective_names and all(n.split()[0].endswith("e") for n in adjective_names)
    names = {it.generate_name(catalog, rng, "schwert", "gewoehnlich", "feuer") for _ in range(30)}
    assert names <= {"Glühendes Schwert", "Loderndes Schwert"}


def test_rare_names_use_element_words(catalog, rng):
    words = catalog.names.elements["wasser"]
    for _ in range(30):
        name = it.generate_name(catalog, rng, "schwert", "selten", "wasser")
        assert any(w in name for w in words.prefixes + words.genitives) or name.split()[0].startswith(("Frostig", "Eisig"))


def test_legendary_items_need_a_name(catalog, rng):
    with pytest.raises(it.ItemError):
        it.make_item(catalog, rng, "schwert", rarity="legendaer")
    blade = it.make_item(catalog, rng, "schwert", rarity="legendaer", element="feuer", name="Ascheherz")
    assert it.display_name(catalog, blade) == "★ Ascheherz"
    assert it.describe(catalog, blade) == "★ Ascheherz (Schwert, legendär, 🔥)"


def test_bag_limit_and_stacking(catalog, rng, make_char):
    hero = make_char()
    hero.bag.clear()
    it.add_to_bag(catalog, hero, it.make_item(catalog, rng, "heiltrank", name="Heiltrank", quantity=7))
    assert [i.quantity for i in hero.bag] == [5, 2]
    for _ in range(8):
        it.add_to_bag(catalog, hero, it.make_item(catalog, rng, "rubin", name="Rubin"))
    assert it.slots_used(catalog, hero) == 10
    # stacking into a free stack still works when the bag is full
    it.add_to_bag(catalog, hero, it.make_item(catalog, rng, "heiltrank", name="Heiltrank", quantity=3))
    with pytest.raises(it.ItemError):
        it.add_to_bag(catalog, hero, it.make_item(catalog, rng, "rubin", name="Rubin"))
    # quest items never count
    it.add_to_bag(catalog, hero, it.make_item(catalog, rng, "questgegenstand", name="Mondschlüssel"))
    assert it.slots_used(catalog, hero) == 10


def test_equip_swaps_and_checks_class(catalog, rng, make_char):
    hero = make_char("krieger")
    axe = it.make_item(catalog, rng, "streitaxt", name="Streitaxt")
    it.add_to_bag(catalog, hero, axe)
    back = it.equip(catalog, hero, axe.id)
    # two-handed: sword and shield go back into the bag
    assert {i.base for i in back} == {"schwert", "schild"}
    assert hero.equipment.waffe.id == axe.id and hero.equipment.schild is None

    mage = make_char("magier")
    plate = it.make_item(catalog, rng, "plattenpanzer", name="Plattenpanzer")
    it.add_to_bag(catalog, mage, plate)
    with pytest.raises(it.ItemError):
        it.equip(catalog, mage, plate.id)


def test_give_needs_same_location(catalog, make_char):
    a = make_char("krieger", id="a", location="dorf")
    b = make_char("barde", id="b", location="sumpf")
    potion = a.bag[0]
    with pytest.raises(it.ItemError):
        it.give(catalog, a, b, potion.id)
    b.location = "dorf"
    given = it.give(catalog, a, b, potion.id)
    assert given.base == "heiltrank"
    assert all(i.base != "heiltrank" for i in a.bag)
    assert sum(i.quantity for i in b.bag if i.base == "heiltrank") == 2


def test_give_equipped_item(catalog, make_char):
    a = make_char("krieger", id="a")
    b = make_char("barde", id="b")
    shield = a.equipment.schild
    it.give(catalog, a, b, shield.id)
    assert a.equipment.schild is None
    assert any(i.id == shield.id for i in b.bag)


def test_prices(catalog, rng):
    common = it.make_item(catalog, rng, "schwert", name="Schwert")
    rare = it.make_item(catalog, rng, "schwert", rarity="selten")
    quest = it.make_item(catalog, rng, "questgegenstand", name="Siegel")
    assert it.price(catalog, common) == 12
    assert it.price(catalog, rare) == 48
    assert it.sell_price(catalog, common) == 6
    assert it.sell_price(catalog, quest) == 0
