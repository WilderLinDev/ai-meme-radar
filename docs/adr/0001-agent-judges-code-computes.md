# Agent collects and judges, code computes; the meme pack is the only source

The run is split in two. The AI agent does browser collection (Creative Center, watchlist profiles, remix pages) and the subjective scoring, and writes both as structured files. Code does everything deterministic: validation, normalisation, lifecycle and share-rate maths, tracker, backtest, score-sum checks, and rendering. Code never hardcodes a given day's judgments (the old `build_meme_pack.py` did), and the agent never hand-writes a number code can compute or a Markdown report alongside the docx: both Markdown and Word are rendered from the meme pack, so they cannot disagree.

## Considered Options

- Agent writes the report directly, code only draws charts (the old way): two sources of truth that drifted apart.
- Fully scripted collection: Creative Center and TikTok/IG profiles need a logged-in browser and change layout often, so collection stays with the agent.
