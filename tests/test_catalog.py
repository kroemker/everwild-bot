from everwild.catalog import load_catalog


def test_catalog_loads_and_references_are_valid():
    catalog = load_catalog()
    assert set(catalog.rules.game_lengths) == {"kurz", "mittel", "lang"}


def test_every_playable_class_has_three_second_abilities(catalog):
    for class_id, cls in catalog.classes.items():
        if cls.selectable:
            assert cls.first_ability, class_id
            assert len(cls.second_abilities) == 3, class_id


def test_every_element_has_name_words(catalog):
    for element in catalog.rules.elements:
        if element != "stahl":
            words = catalog.names.elements[element]
            assert words.prefixes and words.adjectives and words.genitives
