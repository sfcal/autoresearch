"""
Autoresearch Scrabble search script. Single-file, CPU only.
Searches for the highest-scoring single Scrabble play reachable in a legal game.
Usage: uv run train.py

Baseline: random greedy playouts. Each playout builds a game from an empty
board by sampling random word placements through tiles already on the board
and (mostly) keeping the highest-scoring legal one. The best single play seen
across all playouts, together with the game leading up to it, is the solution.
"""

import random
import time

from prepare import (
    TIME_BUDGET, BOARD_SIZE, CENTER, RACK_SIZE, MAX_TILES_ON_BOARD,
    Board, IllegalPlay, load_lexicon, evaluate_solution, save_solution,
    replay_game, format_play,
)

# ---------------------------------------------------------------------------
# Hyperparameters (edit these directly, no CLI flags needed)
# ---------------------------------------------------------------------------

SEED = 42
MAX_WORD_LEN = 8         # longest word sampled (7 new tiles + 1 tile on the board)
SAMPLES_PER_TURN = 300   # random placements tried per turn
GREED = 0.8              # probability of keeping the best sample (else a random legal one)
MAX_TURNS = 30           # plays per playout before restarting

# ---------------------------------------------------------------------------
# Setup: lexicon and word indexes
# ---------------------------------------------------------------------------

t_start = time.time()
random.seed(SEED)

lexicon = load_lexicon()
words = sorted(w for w in lexicon if len(w) <= MAX_WORD_LEN)
opening_words = [w for w in words if len(w) <= RACK_SIZE]
words_with = {}  # letter -> words containing it
for w in words:
    for ch in set(w):
        words_with.setdefault(ch, []).append(w)
print(f"Lexicon: {len(lexicon):,} words ({len(words):,} with length <= {MAX_WORD_LEN})")
print(f"Time budget: {TIME_BUDGET}s")

# ---------------------------------------------------------------------------
# Move sampling
# ---------------------------------------------------------------------------

def sample_opening():
    """Random first play: a horizontal word covering the center square."""
    word = random.choice(opening_words)
    offset = random.randrange(len(word))
    return (word, CENTER[0], CENTER[1] - offset, "H")


def sample_play(board, occupied):
    """Random placement of a word through one tile already on the board (may be illegal)."""
    r, c = random.choice(occupied)
    letter = board.grid[r][c].upper()
    word = random.choice(words_with[letter])
    idx = random.choice([i for i, ch in enumerate(word) if ch == letter])
    if random.random() < 0.5:
        return (word, r, c - idx, "H")
    return (word, r - idx, c, "V")

# ---------------------------------------------------------------------------
# Search loop
# ---------------------------------------------------------------------------

best_score = 0
best_plays = []
num_playouts = 0
num_plays = 0
num_samples = 0
t_start_search = time.time()
t_last_log = t_start_search

def time_left():
    return TIME_BUDGET - (time.time() - t_start_search)

while time_left() > 0:
    board = Board(lexicon)
    plays = []
    occupied = []
    num_playouts += 1

    for turn in range(MAX_TURNS):
        if board.num_tiles >= MAX_TILES_ON_BOARD or time_left() <= 0:
            break

        # Sample candidate plays and score the legal ones
        candidates = []
        for _ in range(SAMPLES_PER_TURN):
            play = sample_play(board, occupied) if occupied else sample_opening()
            num_samples += 1
            try:
                candidates.append((board.score_play(*play), play))
            except IllegalPlay:
                continue
        if not candidates:
            break

        if random.random() < GREED:
            score, play = max(candidates)
        else:
            score, play = random.choice(candidates)
        board.play(*play)
        plays.append(play)
        num_plays += 1
        occupied = [(r, c) for r in range(BOARD_SIZE) for c in range(BOARD_SIZE)
                    if board.grid[r][c] is not None]

        if score > best_score:
            best_score = score
            best_plays = list(plays)
            elapsed = time.time() - t_start_search
            print(f"\n[{elapsed:6.1f}s] new best: {best_score} ({play[0]}, play {len(plays)} of playout {num_playouts})", flush=True)

    now = time.time()
    if now - t_last_log > 1.0:
        t_last_log = now
        elapsed = now - t_start_search
        pct_done = 100 * min(elapsed / TIME_BUDGET, 1.0)
        print(f"\rplayout {num_playouts:06d} ({pct_done:.1f}%) | best: {best_score} | samples/sec: {int(num_samples / elapsed):,} | remaining: {max(0, TIME_BUDGET - elapsed):.0f}s    ", end="", flush=True)

print()  # newline after \r search log
search_seconds = time.time() - t_start_search

# Final eval: the solution is re-scored from scratch by the fixed evaluator
final_score = evaluate_solution(best_plays)
save_solution(best_plays, "solution.json")
board, scores = replay_game(best_plays)

print("Best game:")
for play, score in zip(best_plays, scores):
    print("  " + format_play(play, score))
print(board)

# Final summary
t_end = time.time()
print("---")
print(f"best_score:       {final_score}")
print(f"best_word:        {best_plays[-1][0].upper() if best_plays else ''}")
print(f"search_seconds:   {search_seconds:.1f}")
print(f"total_seconds:    {t_end - t_start:.1f}")
print(f"num_playouts:     {num_playouts}")
print(f"num_plays:        {num_plays}")
print(f"num_samples_M:    {num_samples / 1e6:.2f}")
print(f"game_length:      {len(best_plays)}")
print(f"tiles_on_board:   {board.num_tiles}")
