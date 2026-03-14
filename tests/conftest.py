"""Shared pytest fixtures for Commander AI Lab tests."""
import pytest
from commander_ai_lab.sim.models import Card, Player, PlayerStats, SimState


@pytest.fixture
def basic_creature():
    return Card(name="Grizzly Bears", type_line="Creature — Bear", cmc=2, pt="2/2", power="2", toughness="2")


@pytest.fixture
def flying_creature():
    return Card(
        name="Serra Angel",
        type_line="Creature — Angel",
        cmc=5,
        pt="4/4",
        power="4",
        toughness="4",
        oracle_text="Flying, vigilance",
        keywords=["Flying", "Vigilance"],
    )


@pytest.fixture
def basic_land():
    return Card(name="Forest", type_line="Basic Land — Forest", cmc=0)


@pytest.fixture
def sol_ring():
    return Card(name="Sol Ring", type_line="Artifact", cmc=1, oracle_text="{T}: Add {C}{C}", is_ramp=True)


@pytest.fixture
def removal_spell():
    return Card(name="Murder", type_line="Instant", cmc=3, oracle_text="Destroy target creature.", is_removal=True)


@pytest.fixture
def board_wipe():
    return Card(name="Wrath of God", type_line="Sorcery", cmc=4, oracle_text="Destroy all creatures.", is_board_wipe=True)


@pytest.fixture
def commander_card():
    return Card(
        name="Korvold, Fae-Cursed King",
        type_line="Legendary Creature — Dragon Noble",
        cmc=5,
        pt="4/4",
        power="4",
        toughness="4",
        is_commander=True,
        oracle_text="Flying, haste\nWhenever Korvold, Fae-Cursed King enters the battlefield or attacks, sacrifice another permanent.",
        keywords=["Flying", "Haste"],
    )


@pytest.fixture
def sample_player(basic_creature, basic_land, sol_ring):
    p = Player(name="Alice", life=40, owner_id=0)
    p.library = [basic_creature.clone(), basic_land.clone(), sol_ring.clone()] * 20
    return p


@pytest.fixture
def two_player_state(sample_player):
    import copy
    p2 = copy.deepcopy(sample_player)
    p2.name = "Bob"
    p2.owner_id = 1
    state = SimState(players=[sample_player, p2])
    state.init_battlefields(2)
    return state
