from everwild.rules.enemies import EnemySpec, build_enemies, encounter_xp, health_words, scaled_count


def test_counts_scale_with_group(catalog):
    spec = EnemySpec("Wolf", "normal", (), 1)
    assert scaled_count(catalog, spec, 1) == 1
    assert scaled_count(catalog, spec, 2) == 2
    assert scaled_count(catalog, spec, 6) == 6


def test_bosses_and_elites_scale_hp_and_attacks_not_count(catalog):
    for tier in ("boss", "elite"):
        solo = build_enemies(catalog, [EnemySpec("X", tier)], 1, 1)
        group = build_enemies(catalog, [EnemySpec("X", tier)], 1, 4)
        assert len(solo) == len(group) == 1
        assert group[0].max_hp == 4 * solo[0].max_hp
        assert group[0].attacks > solo[0].attacks == 1


def test_region_level_scaling(catalog):
    low = build_enemies(catalog, [EnemySpec("Wolf", "normal")], 1, 1)[0]
    high = build_enemies(catalog, [EnemySpec("Wolf", "normal")], 7, 1)[0]
    assert high.max_hp > low.max_hp
    assert high.defense == low.defense + 2
    assert high.attack == low.attack + 2
    assert high.damage_bonus == 2


def test_ids_and_names_are_unique(catalog):
    enemies = build_enemies(catalog, [EnemySpec("Moorschleicher", "normal", (), 2)], 1, 2)
    assert len({e.id for e in enemies}) == len(enemies) == 4
    assert enemies[0].name == "Moorschleicher 1"


def test_encounter_xp_ignores_group_size(catalog):
    specs = [EnemySpec("Oger", "stark"), EnemySpec("Wolf", "normal", (), 2)]
    assert encounter_xp(catalog, specs) == 20 + 2 * 10


def test_health_words(catalog):
    wolf = build_enemies(catalog, [EnemySpec("Wolf", "normal")], 1, 1)[0]
    assert health_words(wolf) == "unverletzt"
    wolf.hp = 1
    assert health_words(wolf) == "schwer verwundet"
    wolf.hp = 0
    assert health_words(wolf) == "besiegt"
