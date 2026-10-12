import json
import os
from collections import deque

import pytest

from minixprint.jobs import DEFAULT_SETTINGS, JobContext, discover, puzzles
from minixprint.jobs import fortune as fortune_mod
from minixprint.render import WIDTH

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "open-meteo.json")
NAMES = {"puzzle.sudoku", "puzzle.maze", "puzzle.wordsearch", "fortune", "morning", "system.status"}


class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        with open(FIXTURE) as fh:
            return json.load(fh)


class FakeHttp:
    def get(self, url, **kw):
        assert "open-meteo" in url
        return FakeResponse()


class DeadHttp:
    def get(self, *a, **kw):
        raise OSError("network down")


def ctx(http=None):
    return JobContext(settings=dict(DEFAULT_SETTINGS), http=http or FakeHttp())


def test_discover_lists_all():
    assert NAMES <= set(discover())


@pytest.mark.parametrize("name", sorted(NAMES))
def test_renders_384_wide(name):
    img = discover()[name]({}, ctx())
    assert img.mode == "1" and img.width == WIDTH and img.height > 1


def test_morning_survives_dead_network_and_is_short():
    img = discover()["morning"]({"todos": ["a", "b"], "notes": "x"}, ctx(DeadHttp()))
    assert img.width == WIDTH and img.height < 900


def test_morning_todo_file(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("one\ntwo\n")
    c = JobContext(settings=dict(DEFAULT_SETTINGS, todo_file=str(f)), http=FakeHttp())
    with_file = discover()["morning"]({"sections": ["todos"]}, c)
    without = discover()["morning"]({"sections": ["todos"]}, ctx())
    assert with_file.height > without.height


@pytest.mark.parametrize("diff", ["easy", "medium", "hard"])
def test_sudoku_valid_and_unique(diff):
    puzzle, solution = puzzles.make_sudoku(diff, seed=42)
    groups = [[r * 9 + c for c in range(9)] for r in range(9)]
    groups += [[r * 9 + c for r in range(9)] for c in range(9)]
    groups += [[(br * 3 + r) * 9 + bc * 3 + c for r in range(3) for c in range(3)]
               for br in range(3) for bc in range(3)]
    for g in groups:
        assert sorted(solution[i] for i in g) == list(range(1, 10))
    assert all(p in (0, s) for p, s in zip(puzzle, solution))
    assert len(puzzles._solve(list(puzzle), limit=2)) == 1
    assert sum(1 for p in puzzle if p) <= puzzles.CLUES[diff] + 2


def test_sudoku_deterministic():
    assert puzzles.make_sudoku("easy", seed=7) == puzzles.make_sudoku("easy", seed=7)
    assert puzzles.make_sudoku("easy", seed=7) != puzzles.make_sudoku("easy", seed=8)
    job = discover()["puzzle.sudoku"]
    a = job({"seed": 3, "with_solution": True}, ctx())
    assert a.tobytes() == job({"seed": 3, "with_solution": True}, ctx()).tobytes()
    assert a.height > job({"seed": 3}, ctx()).height


@pytest.mark.parametrize("n", [15, 25, 41])
def test_maze_solvable(n):
    open_ = puzzles.make_maze(n, seed=n)
    adj = {}
    for e in open_:
        a, b = tuple(e)
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    seen, q = {(0, 0)}, deque([(0, 0)])
    while q:
        for nb in adj.get(q.popleft(), []):
            if nb not in seen:
                seen.add(nb)
                q.append(nb)
    assert (n - 1, n - 1) in seen and len(seen) == n * n


def test_maze_size_clamped_to_odd_range():
    assert puzzles.maze_size(3) == 15 and puzzles.maze_size(99) == 41
    assert puzzles.maze_size(20) % 2 == 1 and puzzles.maze_size("x") == 25
    img = discover()["puzzle.maze"]({"size": 41, "seed": 1}, ctx())
    assert img.width == WIDTH


def test_wordsearch_places_words():
    grid, placed = puzzles.make_wordsearch(["CAT", "DOG", "BIRD"], seed=1)
    assert placed == ["BIRD", "CAT", "DOG"]
    assert len(grid) == 12 and all(len(r) == 12 for r in grid)


def test_fortunes_file_and_determinism():
    lines = fortune_mod.load_fortunes()
    assert len(lines) >= 60 and len(set(lines)) == len(lines)
    assert all(len(ln) < 120 for ln in lines)
    c = ctx()
    assert fortune_mod.pick_fortune({"seed": 5}, c) == fortune_mod.pick_fortune({"seed": 5}, c)
