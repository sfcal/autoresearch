"""
Fixed rules, lexicon and scoring for the Scrabble autoresearch experiments.

The goal of the search (train.py) is the highest-scoring single Scrabble play
that can occur in a legal game. A solution is a *game*: an ordered list of
plays starting from an empty board. Every play is validated against the rules
and the lexicon, and the metric is the score of the LAST play. Requiring the
whole game (not just a final board) proves that the position is reachable.

Usage:
    python prepare.py                         # check lexicon + scorer self-tests
    python prepare.py --verify solution.json  # independently re-score a solution

The lexicon is read from NWL2023.txt next to this file.
"""

import os
import sys
import json
import argparse

# ---------------------------------------------------------------------------
# Constants (fixed, do not modify)
# ---------------------------------------------------------------------------

TIME_BUDGET = 300        # search time budget in seconds (5 minutes)
BOARD_SIZE = 15
CENTER = (7, 7)
RACK_SIZE = 7            # max tiles placed in a single play
BINGO_BONUS = 50         # bonus for placing all 7 tiles
TOTAL_TILES = 100
# The game ends when a player empties their rack with the bag empty, and a
# player's rack is only ever empty at that moment. So whenever a play is made
# the opponent still holds at least one tile: the board never exceeds 99 tiles.
MAX_TILES_ON_BOARD = TOTAL_TILES - 1

LEXICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "NWL2023.txt")

BLANK = "?"
TILE_COUNTS = {
    "A": 9, "B": 2, "C": 2, "D": 4, "E": 12, "F": 2, "G": 3, "H": 2, "I": 9,
    "J": 1, "K": 1, "L": 4, "M": 2, "N": 6, "O": 8, "P": 2, "Q": 1, "R": 6,
    "S": 4, "T": 6, "U": 4, "V": 2, "W": 2, "X": 1, "Y": 2, "Z": 1, BLANK: 2,
}
TILE_VALUES = {
    "A": 1, "B": 3, "C": 3, "D": 2, "E": 1, "F": 4, "G": 2, "H": 4, "I": 1,
    "J": 8, "K": 5, "L": 1, "M": 3, "N": 1, "O": 1, "P": 3, "Q": 10, "R": 1,
    "S": 1, "T": 1, "U": 1, "V": 4, "W": 4, "X": 8, "Y": 4, "Z": 10, BLANK: 0,
}
assert sum(TILE_COUNTS.values()) == TOTAL_TILES

# T = triple word, D = double word, t = triple letter, d = double letter
_HALF = [
    "T..d...T...d..T",
    ".D...t...t...D.",
    "..D...d.d...D..",
    "d..D...d...D..d",
    "....D.....D....",
    ".t...t...t...t.",
    "..d...d.d...d..",
]
PREMIUMS = _HALF + ["T..d...D...d..T"] + _HALF[::-1]
LETTER_MULT = [[{"d": 2, "t": 3}.get(ch, 1) for ch in row] for row in PREMIUMS]
WORD_MULT = [[{"D": 2, "T": 3}.get(ch, 1) for ch in row] for row in PREMIUMS]

HORIZONTAL = "H"
VERTICAL = "V"

# ---------------------------------------------------------------------------
# Lexicon
# ---------------------------------------------------------------------------

def load_lexicon(path=LEXICON_PATH):
    """Return the set of valid words (uppercase). File format: 'WORD definition...' per line."""
    if not os.path.exists(path):
        print(f"Lexicon not found at {path}. Place NWL2023.txt next to prepare.py.")
        sys.exit(1)
    words = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.split(None, 1)
            if not parts:
                continue
            word = parts[0].upper()
            if 2 <= len(word) <= BOARD_SIZE and word.isascii() and word.isalpha():
                words.add(word)
    return frozenset(words)

# ---------------------------------------------------------------------------
# Board and rules (imported by train.py)
# ---------------------------------------------------------------------------

class IllegalPlay(ValueError):
    pass


class Board:
    """
    Scrabble board with full play validation and scoring.

    A play is (word, row, col, direction):
      - word: the complete main word, including tiles already on the board.
        Uppercase = regular tile, lowercase = blank standing for that letter.
      - row, col: 0-indexed square of the word's first letter.
      - direction: "H" (left to right) or "V" (top to bottom).

    grid[r][c] is None for an empty square, otherwise the tile's letter
    (lowercase if the tile is a blank).
    """

    def __init__(self, lexicon):
        self.lexicon = lexicon
        self.grid = [[None] * BOARD_SIZE for _ in range(BOARD_SIZE)]
        self.used = dict.fromkeys(TILE_COUNTS, 0)  # tiles on the board, blanks under "?"
        self.num_tiles = 0

    def copy(self):
        other = Board.__new__(Board)
        other.lexicon = self.lexicon
        other.grid = [row[:] for row in self.grid]
        other.used = dict(self.used)
        other.num_tiles = self.num_tiles
        return other

    def tiles_left(self):
        """Tiles not yet on the board (bag + racks), as {letter: count}."""
        return {t: TILE_COUNTS[t] - n for t, n in self.used.items()}

    def _analyze(self, word, row, col, direction):
        """Validate a play. Returns (score, placed) where placed = [(r, c, tile_char)]."""
        if direction == HORIZONTAL:
            dr, dc = 0, 1
        elif direction == VERTICAL:
            dr, dc = 1, 0
        else:
            raise IllegalPlay(f"bad direction {direction!r}")
        n = len(word)
        grid = self.grid
        if n < 2:
            raise IllegalPlay("word must have at least 2 letters")
        if not (word.isascii() and word.isalpha()):
            raise IllegalPlay(f"bad word {word!r}")
        end_r, end_c = row + dr * (n - 1), col + dc * (n - 1)
        if not (0 <= row and 0 <= col and end_r < BOARD_SIZE and end_c < BOARD_SIZE):
            raise IllegalPlay("word does not fit on the board")
        # The word given must be the complete run of tiles along its line
        br, bc = row - dr, col - dc
        if br >= 0 and bc >= 0 and grid[br][bc] is not None:
            raise IllegalPlay("word is preceded by an existing tile")
        ar, ac = end_r + dr, end_c + dc
        if ar < BOARD_SIZE and ac < BOARD_SIZE and grid[ar][ac] is not None:
            raise IllegalPlay("word is followed by an existing tile")
        if word.upper() not in self.lexicon:
            raise IllegalPlay(f"{word.upper()} is not in the lexicon")

        lexicon = self.lexicon
        placed = []
        main_sum = 0
        main_mult = 1
        cross_total = 0
        connected = False
        covers_center = False
        for i, ch in enumerate(word):
            r, c = row + dr * i, col + dc * i
            existing = grid[r][c]
            if existing is not None:
                if existing.upper() != ch.upper():
                    raise IllegalPlay(f"square ({r},{c}) holds {existing}, not {ch}")
                main_sum += TILE_VALUES[existing] if existing.isupper() else 0
                connected = True
                continue
            placed.append((r, c, ch))
            if (r, c) == CENTER:
                covers_center = True
            value = (TILE_VALUES[ch] if ch.isupper() else 0) * LETTER_MULT[r][c]
            wm = WORD_MULT[r][c]
            main_sum += value
            main_mult *= wm
            # Cross-word formed perpendicular to the play through this tile
            pr, pc = r - dc, c - dr
            before = []
            while pr >= 0 and pc >= 0 and grid[pr][pc] is not None:
                before.append(grid[pr][pc])
                pr -= dc
                pc -= dr
            pr, pc = r + dc, c + dr
            after = []
            while pr < BOARD_SIZE and pc < BOARD_SIZE and grid[pr][pc] is not None:
                after.append(grid[pr][pc])
                pr += dc
                pc += dr
            if before or after:
                cross = "".join(before[::-1]) + ch + "".join(after)
                if cross.upper() not in lexicon:
                    raise IllegalPlay(f"cross-word {cross.upper()} is not in the lexicon")
                cross_sum = value
                for t in before:
                    if t.isupper():
                        cross_sum += TILE_VALUES[t]
                for t in after:
                    if t.isupper():
                        cross_sum += TILE_VALUES[t]
                cross_total += cross_sum * wm
                connected = True

        if not placed:
            raise IllegalPlay("play places no tiles")
        if len(placed) > RACK_SIZE:
            raise IllegalPlay(f"play places {len(placed)} tiles (max {RACK_SIZE})")
        if self.num_tiles == 0:
            if not covers_center:
                raise IllegalPlay("first play must cover the center square")
        elif not connected:
            raise IllegalPlay("play does not connect to existing tiles")
        if self.num_tiles + len(placed) > MAX_TILES_ON_BOARD:
            raise IllegalPlay("not enough tiles left in the game")
        need = {}
        for _, _, ch in placed:
            tile = ch if ch.isupper() else BLANK
            need[tile] = need.get(tile, 0) + 1
        for tile, k in need.items():
            if self.used[tile] + k > TILE_COUNTS[tile]:
                raise IllegalPlay(f"not enough {tile} tiles left")

        score = main_sum * main_mult + cross_total
        if len(placed) == RACK_SIZE:
            score += BINGO_BONUS
        return score, placed

    def score_play(self, word, row, col, direction):
        """Score a play without making it. Raises IllegalPlay if it is not legal."""
        return self._analyze(word, row, col, direction)[0]

    def play(self, word, row, col, direction):
        """Make a play and return its score. Raises IllegalPlay if it is not legal."""
        score, placed = self._analyze(word, row, col, direction)
        for r, c, ch in placed:
            self.grid[r][c] = ch
            self.used[ch if ch.isupper() else BLANK] += 1
        self.num_tiles += len(placed)
        return score

    def __str__(self):
        header = "    " + " ".join(f"{c:X}" for c in range(BOARD_SIZE))
        rows = [header]
        for r in range(BOARD_SIZE):
            cells = [self.grid[r][c] or "." for c in range(BOARD_SIZE)]
            rows.append(f"{r:3d} " + " ".join(cells))
        return "\n".join(rows)


def format_play(play, score=None):
    word, row, col, direction = play
    text = f"{word:<15s} row {row:2d} col {col:2d} {direction}"
    return text if score is None else f"{text}  {score:5d}"

# ---------------------------------------------------------------------------
# Evaluation (DO NOT CHANGE — this is the fixed metric)
# ---------------------------------------------------------------------------

_LEXICON = None

def replay_game(plays):
    """Replay a game from an empty board. Returns (board, list of per-play scores)."""
    global _LEXICON
    if _LEXICON is None:
        _LEXICON = load_lexicon()
    board = Board(_LEXICON)
    scores = []
    for i, play in enumerate(plays):
        word, row, col, direction = play
        try:
            scores.append(board.play(str(word), int(row), int(col), str(direction)))
        except IllegalPlay as e:
            raise IllegalPlay(f"play {i + 1} ({word} at {row},{col} {direction}): {e}") from None
    return board, scores


def evaluate_solution(plays):
    """
    Ground-truth metric: the score of the final play of a fully legal game.
    `plays` is a list of (word, row, col, direction) starting from an empty
    board. Raises IllegalPlay if any play in the game is illegal. Higher is better.
    """
    if not plays:
        return 0
    _, scores = replay_game(plays)
    return scores[-1]


def save_solution(plays, path="solution.json"):
    score = evaluate_solution(plays)
    with open(path, "w") as f:
        json.dump({"score": score, "plays": [list(p) for p in plays]}, f, indent=1)
    return score

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _self_test():
    # MUZJIKS is the highest-scoring opening play in the lexicon: 128 points
    assert evaluate_solution([("MUZJIKS", 7, 1, "H")]) == 128
    # (10+1+1+10) x2 for the center square
    assert evaluate_solution([("QUIZ", 7, 4, "H")]) == 44
    # Existing tiles score face value, no premiums
    assert evaluate_solution([("QUIZ", 7, 4, "H"), ("ZA", 7, 7, "V")]) == 11
    # Main word FA (4x2 + 1 = 9) plus cross-word IF (1 + 4x2 = 9)
    assert evaluate_solution([("QUIZ", 7, 4, "H"), ("ZA", 7, 7, "V"), ("FA", 8, 6, "H")]) == 18
    # A blank scores zero
    assert evaluate_solution([("QUIz", 7, 4, "H")]) == 24
    illegal = [
        [("QUIZ", 7, 0, "H")],                         # misses the center
        [("QUIZ", 7, 4, "H"), ("ZA", 0, 0, "H")],      # disconnected
        [("QUIZ", 7, 4, "H"), ("QUIZ", 7, 4, "H")],    # places nothing
        [("QUIZ", 7, 4, "H"), ("ZZZ", 7, 7, "V")],     # only one Z in the bag
        [("QUIZ", 7, 4, "H"), ("QUI", 7, 4, "H")],     # not the complete run
        [("QUIZ", 7, 4, "H"), ("XA", 8, 6, "H")],      # invalid cross-words
        [("ZZXQ", 7, 4, "H")],                         # not a word
    ]
    for plays in illegal:
        try:
            evaluate_solution(plays)
        except IllegalPlay:
            continue
        raise AssertionError(f"expected illegal: {plays}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lexicon check and solution verifier for Scrabble autoresearch")
    parser.add_argument("--verify", metavar="SOLUTION_JSON", help="re-score a solution file written by train.py")
    args = parser.parse_args()

    lexicon = load_lexicon()
    print(f"Lexicon: {len(lexicon):,} words from {LEXICON_PATH}")

    if args.verify:
        with open(args.verify) as f:
            plays = [tuple(p) for p in json.load(f)["plays"]]
        board, scores = replay_game(plays)
        for play, score in zip(plays, scores):
            print(format_play(play, score))
        print(board)
        print(f"best_score:       {scores[-1] if scores else 0}")
    else:
        _self_test()
        print("Scorer: self-tests passed")
        print()
        print("Done! Ready to search.")
