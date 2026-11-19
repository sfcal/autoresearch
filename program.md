# autoresearch (Scrabble)

This is an experiment to have the LLM do its own research. The research problem: find the highest-scoring single Scrabble play that can occur in a legal game, using the NWL2023 lexicon.

## Setup

To set up a new experiment, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `mar5`). The branch `autoresearch/<tag>` must not already exist — this is a fresh run.
2. **Create the branch**: `git checkout -b autoresearch/<tag>` from current master.
3. **Read the in-scope files**: The repo is small. Read these files for full context:
   - `prepare.py` — fixed constants, lexicon loading, board rules, scoring, evaluation. Do not modify.
   - `train.py` — the file you modify. The search algorithm.
4. **Verify the lexicon and scorer**: Run `uv run prepare.py`. It checks that `NWL2023.txt` is present next to `prepare.py` and runs the scorer self-tests. If the lexicon is missing, tell the human to add it.
5. **Initialize results.tsv**: Create `results.tsv` with just the header row. The baseline will be recorded after the first run.
6. **Confirm and go**: Confirm setup looks good.

Once you get confirmation, kick off the experimentation.

## The problem

A solution is a **game**: an ordered list of plays starting from an empty board. Each play is `(word, row, col, direction)`:

- `word` is the complete main word, including tiles already on the board. Uppercase is a regular tile, lowercase is a blank standing for that letter.
- `row`, `col` are 0-indexed and give the square of the word's first letter.
- `direction` is `"H"` (left to right) or `"V"` (top to bottom).

`evaluate_solution(plays)` in `prepare.py` replays the game and validates every play: the word and all cross-words must be in the lexicon, at most 7 tiles are placed per play, the first play covers the center, later plays connect to existing tiles, and the standard 100-tile distribution (2 blanks) is respected. The metric is the score of the **last** play. Requiring the whole game proves the position is reachable, so every setup tile has to be placed by a legal play of its own.

For orientation: the best-known constructions put a 15-letter word across three triple-word squares (27x) on an edge, with 7 new tiles joining 8 already there and heavy cross-words; OXYPHENBUTAZONE scores well over 1,700 this way. The baseline is nowhere near that.

## Experimentation

Each experiment runs on the CPU. The search script runs for a **fixed time budget of 5 minutes** (wall clock search time, excluding startup). You launch it simply as: `uv run train.py`.

**What you CAN do:**
- Modify `train.py` — this is the only file you edit. Everything is fair game: the search algorithm, move generation, data structures, how the board is built toward a target play, heuristics, hyperparameters, etc. You may write your own faster board representation in `train.py`, as long as the final game passes `evaluate_solution`.

**What you CANNOT do:**
- Modify `prepare.py`. It is read-only. It contains the fixed rules, scoring, lexicon loading and time budget.
- Modify the evaluation. `evaluate_solution` in `prepare.py` is the ground truth metric.
- Install new packages or add dependencies. You can only use the standard library and what's already in `pyproject.toml`: `ortools` (CP-SAT, good for maximizing a score under constraints) and `python-sat` (`pysat`: CaDiCaL, Glucose, RC2 MaxSAT), plus `numpy`. `matplotlib` and `pandas` are also installed, for plots and for `analysis.ipynb`.
- Hardcode a game. Do not paste a pre-built board, move list, or a previous run's `solution.json` into `train.py`. The score must be found by the search inside the time budget. Encoding structural insight is fine (e.g. "aim for 15-letter words on the edge rows", preferring high-value letters on premium squares); encoding the answer is not.

**The goal is simple: get the highest best_score.** Since the time budget is fixed, you don't need to worry about run time — it's always 5 minutes. The only constraints are that the code runs without crashing, finishes within the time budget, and produces a game that the evaluator accepts.

**Solvers and the time budget**: `train.py` enforces the 5 minutes itself, so a solver call that runs long blows the budget. Always give solver calls a time limit derived from the time remaining (e.g. `solver.parameters.max_time_in_seconds` for CP-SAT), and keep the best game found so far so that a timed-out call still leaves a valid result. Model building counts against the budget too.

**Noise**: The search is randomized and time-limited, so the same code can give different scores on different runs or machines. Be skeptical of small improvements from pure luck. If a gain is small and the change has no clear reason to help, re-run before keeping it.

**Simplicity criterion**: All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it. Conversely, removing something and getting equal or better results is a great outcome — that's a simplification win. When evaluating whether to keep a change, weigh the complexity cost against the improvement magnitude.

**The first run**: Your very first run should always be to establish the baseline, so you will run the search script as is.

## Output format

Once the script finishes it prints the best game, the final board, and a summary like this:

```
---
best_score:       311
best_word:        CLAQUERS
search_seconds:   300.0
total_seconds:    300.2
num_playouts:     62400
num_plays:        605700
num_samples_M:    200.40
game_length:      3
tiles_on_board:   19
```

The numbers will look different depending on the computer. You can extract the key metric from the log file:

```
grep "^best_score:" run.log
```

The script also writes the best game to `solution.json`. You can re-score it independently with `uv run prepare.py --verify solution.json`.

## Logging results

When an experiment is done, log it to `results.tsv` (tab-separated, NOT comma-separated — commas break in descriptions).

The TSV has a header row and 5 columns:

```
commit	best_score	best_word	status	description
```

1. git commit hash (short, 7 chars)
2. best_score achieved (e.g. 311) — use 0 for crashes
3. best_word, the final word of the best game — use `-` for crashes
4. status: `keep`, `discard`, or `crash`
5. short text description of what this experiment tried

Example:

```
commit	best_score	best_word	status	description
a1b2c3d	311	CLAQUERS	keep	baseline
b2c3d4e	392	QUIXOTRY	keep	sample placements through two existing tiles
c3d4e5f	275	ZYZZYVAS	discard	always pick a random legal play
d4e5f6g	0	-	crash	edge-row targeting (index error)
```

## The experiment loop

The experiment runs on a dedicated branch (e.g. `autoresearch/mar5`).

LOOP FOREVER:

1. Look at the git state: the current branch/commit we're on
2. Tune `train.py` with an experimental idea by directly hacking the code.
3. git commit
4. Run the experiment: `uv run train.py > run.log 2>&1` (redirect everything — do NOT use tee or let output flood your context)
5. Read out the results: `grep "^best_score:\|^best_word:" run.log`
6. If the grep output is empty, the run crashed. Run `tail -n 50 run.log` to read the Python stack trace and attempt a fix. If you can't get things to work after more than a few attempts, give up.
7. Record the results in the tsv (NOTE: do not commit the results.tsv file, leave it untracked by git)
8. If best_score improved (higher), you "advance" the branch, keeping the git commit. Also copy `solution.json` to `best_solution.json` so the record game survives later runs (leave it untracked).
9. If best_score is equal or worse, you git reset back to where you started

The idea is that you are a completely autonomous researcher trying things out. If they work, keep. If they don't, discard. And you're advancing the branch so that you can iterate. If you feel like you're getting stuck in some way, you can rewind but you should probably do this very very sparingly (if ever).

**Timeout**: Each experiment should take ~5 minutes total (+ a few seconds for startup and eval overhead). If a run exceeds 10 minutes, kill it and treat it as a failure (discard and revert).

**Crashes**: If a run crashes (a bug, an illegal final game, etc.), use your judgment: If it's something dumb and easy to fix (e.g. a typo, a missing import), fix it and re-run. If the idea itself is fundamentally broken, just skip it, log "crash" as the status in the tsv, and move on.

**NEVER STOP**: Once the experiment loop has begun (after the initial setup), do NOT pause to ask the human if you should continue. Do NOT ask "should I keep going?" or "is this a good stopping point?". The human might be asleep, or gone from a computer and expects you to continue working *indefinitely* until you are manually stopped. You are autonomous. If you run out of ideas, think harder — re-read the in-scope files for new angles, study how the known record plays are structured, try combining previous near-misses, try more radical changes to the search. The loop runs until the human interrupts you, period.

As an example use case, a user might leave you running while they sleep. If each experiment takes you ~5 minutes then you can run approx 12/hour, for a total of about 100 over the duration of the average human sleep. The user then wakes up to experimental results, all completed by you while they slept!
