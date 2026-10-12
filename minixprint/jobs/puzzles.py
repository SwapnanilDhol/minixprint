"""Puzzle jobs: ``puzzle.sudoku``, ``puzzle.maze``, ``puzzle.wordsearch``.

All are seeded: pass ``seed`` for a specific puzzle, otherwise the date is the seed so
the same day always gives the same puzzle.
"""
from PIL import Image, ImageDraw

from ..render import WIDTH, font, render_text, rule, stack
from ._common import rng

# --------------------------------------------------------------------------- sudoku

CLUES = {"easy": 40, "medium": 32, "hard": 26}
_PEERS = []
for _i in range(81):
    _r, _c = divmod(_i, 9)
    _b = (_r // 3) * 3 + _c // 3
    _PEERS.append([j for j in range(81) if j != _i and (
        j // 9 == _r or j % 9 == _c or (j // 9 // 3) * 3 + (j % 9) // 3 == _b)])


def _candidates(grid, i):
    used = {grid[j] for j in _PEERS[i]}
    return [v for v in range(1, 10) if v not in used]


def _solve(grid, r=None, limit=1):
    """Backtracking (most-constrained cell first). Returns solutions found, up to `limit`."""
    sols = []

    def go():
        best, opts = -1, None
        for i in range(81):
            if grid[i] == 0:
                c = _candidates(grid, i)
                if opts is None or len(c) < len(opts):
                    best, opts = i, c
                    if len(c) <= 1:
                        break
        if best < 0:
            sols.append(list(grid))
            return len(sols) >= limit
        if r is not None:
            r.shuffle(opts)
        for v in opts:
            grid[best] = v
            if go():
                grid[best] = 0
                return True
        grid[best] = 0
        return False

    go()
    return sols


def make_sudoku(difficulty="medium", seed=None):
    """Return (puzzle, solution) as flat lists of 81 ints (0 = blank), unique solution."""
    import random
    r = random.Random(seed)
    solution = _solve([0] * 81, r)[0]
    puzzle = list(solution)
    target = CLUES.get(difficulty, CLUES["medium"])
    order = list(range(81))
    r.shuffle(order)
    clues = 81
    for i in order:
        if clues <= target:
            break
        keep, puzzle[i] = puzzle[i], 0
        if len(_solve(list(puzzle), limit=2)) != 1:
            puzzle[i] = keep
        else:
            clues -= 1
    return puzzle, solution


def draw_sudoku(grid, cell=40, margin=None, size=None):
    n = cell * 9
    margin = (WIDTH - n) // 2 if margin is None else margin
    img = Image.new("1", (WIDTH, n + 4), 1)
    d = ImageDraw.Draw(img)
    thick = 3 if cell >= 30 else 2
    for k in range(10):
        w = thick if k % 3 == 0 else 1
        x = margin + k * cell
        d.rectangle([x - w // 2, 1, x - w // 2 + w - 1, n + 1 + thick // 2], fill=0)
        y = 1 + k * cell
        d.rectangle([margin - thick // 2, y - w // 2, margin + n + thick // 2, y - w // 2 + w - 1], fill=0)
    f = font("sans", size or int(cell * 0.62), bold=True)
    for i, v in enumerate(grid):
        if v:
            r, c = divmod(i, 9)
            d.text((margin + c * cell + cell / 2, 1 + r * cell + cell / 2 + 1), str(v),
                   font=f, fill=0, anchor="mm")
    return img


def sudoku(params, ctx):
    """Sudoku with a unique solution, at easy, medium or hard difficulty."""
    diff = str(params.get("difficulty", "medium")).lower()
    if diff not in CLUES:
        diff = "medium"
    seed = rng(params, ctx, "sudoku").random()
    puzzle, solution = make_sudoku(diff, seed)
    blocks = [render_text("SUDOKU", size=30, bold=True, align="center", margin=4),
              render_text(diff.capitalize(), size=18, align="center", margin=0),
              draw_sudoku(puzzle)]
    if params.get("with_solution"):
        blocks += [rule("dashed"), render_text("Solution", size=16, align="center", margin=0),
                   draw_sudoku(solution, cell=22)]
    return stack(*blocks)


# --------------------------------------------------------------------------- maze

def make_maze(n, seed=None):
    """Recursive backtracker on an n x n cell grid.

    Returns the set of open passages as frozenset({(r1,c1),(r2,c2)}) pairs.
    """
    import random
    r = random.Random(seed)
    seen = {(0, 0)}
    stack_ = [(0, 0)]
    open_ = set()
    while stack_:
        cr, cc = stack_[-1]
        nbrs = [(cr + dr, cc + dc) for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if 0 <= cr + dr < n and 0 <= cc + dc < n and (cr + dr, cc + dc) not in seen]
        if not nbrs:
            stack_.pop()
            continue
        nxt = r.choice(nbrs)
        seen.add(nxt)
        open_.add(frozenset(((cr, cc), nxt)))
        stack_.append(nxt)
    return open_


def maze_size(raw):
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 25
    n = max(15, min(41, n))
    return n if n % 2 else n + 1 if n < 41 else n - 1


def draw_maze(n, open_):
    wall = 2
    cell = (WIDTH - 8 - wall) // n
    side = cell * n + wall
    ox = (WIDTH - side) // 2
    img = Image.new("1", (WIDTH, side + 8), 1)
    d = ImageDraw.Draw(img)
    oy = 4

    def hline(r, c):  # wall below row r-1 / above row r, spanning column c
        x, y = ox + c * cell, oy + r * cell
        d.rectangle([x, y, x + cell + wall - 1, y + wall - 1], fill=0)

    def vline(r, c):
        x, y = ox + c * cell, oy + r * cell
        d.rectangle([x, y, x + wall - 1, y + cell + wall - 1], fill=0)

    for r in range(n + 1):
        for c in range(n):
            if r == 0:
                if c != 0:      # entrance gap at top-left
                    hline(r, c)
            elif r == n:
                if c != n - 1:  # exit gap at bottom-right
                    hline(r, c)
            elif frozenset(((r - 1, c), (r, c))) not in open_:
                hline(r, c)
    for r in range(n):
        for c in range(n + 1):
            if c in (0, n) or frozenset(((r, c - 1), (r, c))) not in open_:
                vline(r, c)
    f = font("sans", max(8, cell - 4), bold=True)
    d.text((ox + cell / 2 + 1, oy + cell / 2 + 1), "S", font=f, fill=0, anchor="mm")
    d.text((ox + (n - 0.5) * cell + 1, oy + (n - 0.5) * cell + 1), "E", font=f, fill=0, anchor="mm")
    return img


def maze(params, ctx):
    """Square perfect maze with an entrance and an exit."""
    n = maze_size(params.get("size", 25))
    open_ = make_maze(n, rng(params, ctx, "maze").random())
    return stack(render_text("MAZE", size=30, bold=True, align="center", margin=4),
                 draw_maze(n, open_), gap=2)


# --------------------------------------------------------------------------- word search

THEMES = {
    "aviation": ["RUNWAY", "FLAPS", "RUDDER", "COCKPIT", "PILOT", "HANGAR", "TAXIWAY", "AILERON",
                 "ALTITUDE", "THROTTLE", "TURBINE", "APRON"],
    "space": ["ORBIT", "COMET", "GALAXY", "NEBULA", "PLANET", "ROCKET", "LUNAR", "SOLAR",
              "METEOR", "COSMOS", "ECLIPSE", "PULSAR"],
    "kitchen": ["WHISK", "LADLE", "SKILLET", "SPATULA", "KETTLE", "GRATER", "COLANDER", "OVEN",
                "TONGS", "APRON", "BLENDER", "MIXER"],
    "animals": ["OTTER", "FALCON", "BADGER", "LEMUR", "HERON", "WALRUS", "GECKO", "BISON",
                "PANDA", "RAVEN", "TIGER", "MOOSE"],
}
GRID = 12
DIRS = [(0, 1), (1, 0), (1, 1), (-1, 1), (0, -1), (-1, 0), (-1, -1), (1, -1)]


def make_wordsearch(words, seed=None):
    import random
    r = random.Random(seed)
    grid = [[""] * GRID for _ in range(GRID)]
    placed = []
    for w in sorted(words, key=len, reverse=True):
        if len(w) > GRID:
            continue
        for _ in range(200):
            dr, dc = r.choice(DIRS)
            r0, c0 = r.randrange(GRID), r.randrange(GRID)
            r1, c1 = r0 + dr * (len(w) - 1), c0 + dc * (len(w) - 1)
            if not (0 <= r1 < GRID and 0 <= c1 < GRID):
                continue
            cells = [(r0 + dr * k, c0 + dc * k) for k in range(len(w))]
            if all(grid[a][b] in ("", w[k]) for k, (a, b) in enumerate(cells)):
                for k, (a, b) in enumerate(cells):
                    grid[a][b] = w[k]
                placed.append(w)
                break
    for a in range(GRID):
        for b in range(GRID):
            if not grid[a][b]:
                grid[a][b] = chr(65 + r.randrange(26))
    return grid, sorted(placed)


def wordsearch(params, ctx):
    """Word-search grid with the word list underneath."""
    rr = rng(params, ctx, "wordsearch")
    words = params.get("words")
    theme = params.get("theme")
    if words:
        words = [str(w).upper().replace(" ", "") for w in words if str(w).strip()]
    else:
        theme = theme if theme in THEMES else rr.choice(sorted(THEMES))
        words = THEMES[theme]
    grid, placed = make_wordsearch(words, rr.random())
    cell = 30
    n = cell * GRID
    ox = (WIDTH - n) // 2
    img = Image.new("1", (WIDTH, n + 2), 1)
    d = ImageDraw.Draw(img)
    f = font("mono", 22, bold=True)
    for r in range(GRID):
        for c in range(GRID):
            d.text((ox + c * cell + cell / 2, r * cell + cell / 2 + 1), grid[r][c],
                   font=f, fill=0, anchor="mm")
    title = "WORD SEARCH" + (" - %s" % theme.upper() if theme and not params.get("words") else "")
    return stack(render_text(title, size=24, bold=True, align="center", margin=4), img,
                 rule("dashed"), render_text("  ".join(placed), size=18, align="center", margin=2))


JOBS = {"puzzle.sudoku": sudoku, "puzzle.maze": maze, "puzzle.wordsearch": wordsearch}
