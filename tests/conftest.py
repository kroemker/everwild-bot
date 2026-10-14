import random

import pytest

from everwild.catalog import default_catalog
from everwild.rules import character as ch


class FixedRng(random.Random):
    """Returns queued values from randint; falls back to a seeded generator."""

    def __init__(self, values):
        super().__init__(0)
        self.values = list(values)

    def randint(self, a, b):
        if self.values:
            value = self.values.pop(0)
            assert a <= value <= b, f"{value} not in [{a}, {b}]"
            return value
        return super().randint(a, b)


@pytest.fixture
def catalog():
    return default_catalog()


@pytest.fixture
def rng():
    return random.Random(42)


@pytest.fixture
def make_char(catalog, rng):
    def factory(class_id="krieger", element="feuer", id=None, name=None, location="dorf", **kwargs):
        return ch.create_character(
            catalog, rng, id=id or class_id, name=name or class_id.title(),
            class_id=class_id, element=element, location=location, **kwargs,
        )
    return factory
