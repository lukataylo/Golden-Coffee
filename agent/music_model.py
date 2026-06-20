"""Local music model — picks the *music itself* from the room's data.

Golden Coffee already tunes music **volume** (`set_music_volume`). This module
goes further: a small, fully **local** model that chooses *what should be
playing* — the mood/genre, tempo (BPM), energy and the Spotify playlist — from
the anonymized scene metrics (occupancy, queue, room energy, time of day).

Why "model" and not just `if/else`? It's a tiny **softmax (multinomial logistic)
classifier** over a handful of scene features. The weights are *learned locally*
from a labelled dataset (`train()` below, pure-Python gradient descent — no
numpy, no cloud, no API key), then baked into `DEFAULT_WEIGHTS` so import is
instant and deterministic. You can re-train on real data any time:

    python -m agent.music_model --train      # refit weights, print them
    python -m agent.music_model              # demo: roll moods over mock scenes

Design notes:
  * Runs anywhere — no network, no key. Fits the "works fully offline" MVP rule.
  * Privacy-first: it only ever sees aggregate counts/energy, never identities.
  * Hysteresis (`SWITCH_MARGIN`) means the room has to *clearly* call for a new
    mood before we change the track, so the music doesn't thrash.
  * Every mood maps to a real Spotify playlist URI (override per mood via env
    `MUSIC_PLAYLIST_<MOOD>`), plus descriptors the actuator can search on.

Output is a `MusicDirective` the policy turns into a `set_music` AgentAction.
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Mood catalogue — each mood is a café-appropriate "vibe" with the knobs the
# actuator needs (playlist + descriptors), and the knobs the dashboard shows
# (BPM, energy, volume). Playlist URIs are sensible defaults; override any of
# them at deploy time with  MUSIC_PLAYLIST_<MOOD>=spotify:playlist:...
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Mood:
    key: str
    label: str            # human label for the dashboard / rationale
    descriptors: str      # free-text the Spotify actuator can search on
    bpm: int              # target tempo
    energy: float         # 0..1 target energy/valence
    volume: int           # suggested volume 0..100 (the model's "loudness")
    playlist: str         # default Spotify playlist URI (env-overridable)


# Default playlist URIs point at large, public Spotify café/mood playlists.
# Treat them as placeholders — set MUSIC_PLAYLIST_<MOOD> to your own for the demo.
#
# Three time-slot moods (the recommended catalogue):
#   morning_rush    07:00–10:59  Upbeat Acoustic Pop / Light Indie Rock
#   midday_dwell    11:00–14:59  Neo-Soul & Lo-Fi Hip Hop
#   afternoon_lounge 15:00–close  Bossa Nova / Indie Folk / Jazz Soul
#
# Three operational overrides (room-state driven, override time slot):
#   rush_flow    queue building → keep the line moving
#   busy_calm    room full      → soft so people can talk
#   upbeat_lift  flat energy    → brighten a dead room
MOODS: dict[str, Mood] = {
    "morning_rush": Mood(
        "morning_rush", "Morning Rush",
        "upbeat acoustic pop light indie rock bright cheerful mid-to-fast tempo",
        bpm=118, energy=0.72, volume=58,
        playlist="spotify:playlist:37i9dQZF1DX0jgyAiPl8Af",
    ),
    "midday_dwell": Mood(
        "midday_dwell", "Midday Dwell",
        "neo-soul lo-fi hip hop instrumental smooth mellow focus background",
        bpm=78, energy=0.38, volume=44,
        playlist="spotify:playlist:37i9dQZF1DWWQRwui0ExPn",
    ),
    "afternoon_lounge": Mood(
        "afternoon_lounge", "Afternoon Lounge",
        "bossa nova indie folk jazz soul warm textured premium relaxing wind-down",
        bpm=85, energy=0.40, volume=46,
        playlist="spotify:playlist:37i9dQZF1DXbITWG1ZJKYt",
    ),
    "rush_flow": Mood(
        "rush_flow", "Rush Flow",
        "steady mid-tempo groove soulful nu-jazz keep the line moving",
        bpm=104, energy=0.55, volume=46,
        playlist="spotify:playlist:37i9dQZF1DX2sUQwD7tbmL",
    ),
    "busy_calm": Mood(
        "busy_calm", "Busy & Calm",
        "soft downtempo chill ambient so a full room stays talkable",
        bpm=80, energy=0.38, volume=38,
        playlist="spotify:playlist:37i9dQZF1DWTvNyxOwkztu",
    ),
    "upbeat_lift": Mood(
        "upbeat_lift", "Upbeat Lift",
        "bright feel-good indie pop sunny energetic vibe-lifter",
        bpm=116, energy=0.70, volume=60,
        playlist="spotify:playlist:37i9dQZF1DX9XIFQuFvzM4",
    ),
}
MOOD_KEYS: list[str] = list(MOODS.keys())


def playlist_for(mood_key: str) -> str:
    """Resolve a mood's playlist URI, honouring a per-mood env override."""
    return os.environ.get(f"MUSIC_PLAYLIST_{mood_key.upper()}", MOODS[mood_key].playlist)


# How hard a controller "prefer this mood" hint leans the softmax. Tuned so a
# single hint reliably wins a toss-up but a clear scene signal (queue building)
# still overrides it — i.e. a *steer*, not a *lock*.
HINT_STRENGTH = 1.5


def bias_for_hint(prefer: str | None = None, strength: float = HINT_STRENGTH) -> dict[str, float]:
    """Build a `bias` dict the controller agent can pass to `recommend()`.

    `prefer` is a mood key the controller wants to lean toward (owner override,
    event mode, or Claude's suggestion folded in as a soft nudge). Returns {} for
    an unknown/empty hint, so callers can pass it through unconditionally.
    """
    if prefer in MOODS:
        return {prefer: float(strength)}
    return {}


# ---------------------------------------------------------------------------
# Features — a fixed-order vector the linear model scores. Kept tiny and
# interpretable; all derived from aggregate, privacy-safe scene metrics.
# ---------------------------------------------------------------------------
# Only *instantaneous* signals — note we deliberately exclude cumulative funnel
# counts (e.g. total walk-offs), which only ever grow and would mislead the model.
FEATURE_NAMES = [
    "bias", "occ", "queue", "energy",
    "morning", "midday", "late_aft", "busy", "lull", "rush",
]
BUSY_OCC = 8     # >= this => a full/busy room
LULL_OCC = 3     # <= this => a flat/quiet room
HIGH_QUEUE = 3   # >= this => the queue is building (music adapts early; staff alert is at 5)


def features(scene: dict) -> list[float]:
    """Map a SceneEvent dict to the model's normalized feature vector."""
    occ = float(scene.get("occupancy", 0) or 0)
    queue = float(scene.get("queue_len", 0) or 0)
    energy = float(scene.get("staff_productivity", 0.0) or 0.0)  # aggregate room movement
    hour = time.localtime(scene.get("ts") or time.time()).tm_hour

    occ_n = min(occ / 12.0, 1.0)
    queue_n = min(queue / 6.0, 1.0)
    # Time-of-day buckets aligned to the recommended catalogue:
    #   morning   07:00–10:59  (Morning Rush slot)
    #   midday    11:00–14:59  (Mid-Day Dwell slot)
    #   late_aft  15:00–close + pre-open  (Late Afternoon / Lounge slot)
    morning = 1.0 if 7 <= hour < 11 else 0.0
    midday = 1.0 if 11 <= hour < 15 else 0.0
    late_aft = 1.0 if (hour >= 15 or hour < 7) else 0.0
    busy = 1.0 if occ >= BUSY_OCC else 0.0
    lull = 1.0 if occ <= LULL_OCC else 0.0
    rush = 1.0 if queue >= HIGH_QUEUE else 0.0
    return [1.0, occ_n, queue_n, energy, morning, midday, late_aft, busy, lull, rush]


# ---------------------------------------------------------------------------
# The model — multinomial logistic regression (softmax) over the features.
# ---------------------------------------------------------------------------
SWITCH_MARGIN = 0.10   # new mood must beat the current one's prob by this to switch


def _softmax(scores: list[float]) -> list[float]:
    m = max(scores)
    exps = [math.exp(s - m) for s in scores]
    z = sum(exps) or 1.0
    return [e / z for e in exps]


@dataclass
class MusicDirective:
    mood: str
    label: str
    playlist: str
    descriptors: str
    bpm: int
    energy: float
    volume: int
    confidence: float
    rationale: str

    def params(self) -> dict:
        return {
            "mood": self.mood,
            "label": self.label,
            "playlist_uri": self.playlist,
            "descriptors": self.descriptors,
            "bpm": self.bpm,
            "energy": round(self.energy, 2),
            "volume": self.volume,
        }


class MusicModel:
    """Scores moods for a scene and (with hysteresis) recommends the track.

    `weights` is a {mood_key: [w per feature]} dict. Defaults to the baked,
    locally-trained `DEFAULT_WEIGHTS`; pass your own to use a re-trained model.
    """

    def __init__(self, weights: dict[str, list[float]] | None = None) -> None:
        self.weights = weights or {k: list(v) for k, v in DEFAULT_WEIGHTS.items()}

    def scores(self, feats: list[float]) -> dict[str, float]:
        return {
            k: sum(w * f for w, f in zip(self.weights[k], feats))
            for k in MOOD_KEYS
        }

    def probabilities(self, scene: dict, bias: dict[str, float] | None = None) -> dict[str, float]:
        """Softmax mood probabilities for a scene.

        `bias` is an optional {mood_key: logit_nudge} from the *controller agent*
        — a way to steer the model without overriding it. Nudges are added to the
        raw logits before softmax, so a small push leans the room toward a vibe
        while big scene signals (a building queue) can still win. Unknown keys are
        ignored; missing moods get 0.
        """
        feats = features(scene)
        raw = self.scores(feats)
        if bias:
            raw = {k: raw[k] + float(bias.get(k, 0.0)) for k in MOOD_KEYS}
        ordered = [raw[k] for k in MOOD_KEYS]
        probs = _softmax(ordered)
        return dict(zip(MOOD_KEYS, probs))

    def recommend(
        self,
        scene: dict,
        current: str | None = None,
        bias: dict[str, float] | None = None,
    ) -> tuple[MusicDirective, bool]:
        """Return (directive, changed). `changed` is False when hysteresis keeps
        the current mood (so the caller can avoid re-firing the same track).

        `bias` (see `probabilities`) lets the controller agent steer the pick —
        e.g. an event mode, an owner preference, or a Claude suggestion folded in
        as a soft nudge rather than a hard override."""
        probs = self.probabilities(scene, bias)
        best = max(MOOD_KEYS, key=lambda k: probs[k])
        chosen = best
        changed = True
        if current in MOODS and current != best:
            # Only switch if the new mood clearly beats the incumbent.
            if probs[best] - probs[current] < SWITCH_MARGIN:
                chosen = current
                changed = False
        elif current == best:
            changed = False

        m = MOODS[chosen]
        occ = int(scene.get("occupancy", 0) or 0)
        why = self._rationale(scene, m, occ)
        directive = MusicDirective(
            mood=m.key, label=m.label, playlist=playlist_for(m.key),
            descriptors=m.descriptors, bpm=m.bpm, energy=m.energy, volume=m.volume,
            confidence=round(probs[chosen], 3), rationale=why,
        )
        return directive, changed

    @staticmethod
    def _rationale(scene: dict, m: Mood, occ: int) -> str:
        queue = int(scene.get("queue_len", 0) or 0)
        energy = float(scene.get("staff_productivity", 0.0) or 0.0)
        bits = {
            "morning_rush":     f"Morning rush ({occ} in) — upbeat acoustic pop to keep the energy moving.",
            "midday_dwell":     f"Midday dwell ({occ} in) — smooth neo-soul / lo-fi for focus and a second pastry.",
            "afternoon_lounge": f"Afternoon lounge ({occ} in) — warm bossa nova / jazz soul for a premium wind-down.",
            "rush_flow":        f"Queue building ({queue}) — steady groove keeps the line moving without stress.",
            "busy_calm":        f"Full and buzzy ({occ} in) — soft downtempo so it stays easy to talk in.",
            "upbeat_lift":      f"Room feels flat (energy {energy:.2f}) — brighter, upbeat music to lift the vibe.",
        }
        return f"{bits.get(m.key, m.label)} → {m.label} (~{m.bpm} BPM)."


# ---------------------------------------------------------------------------
# Local training — a labelled "oracle" + pure-Python softmax gradient descent.
# This is how DEFAULT_WEIGHTS below were produced (`python -m agent.music_model
# --train`). It needs nothing but the standard library.
# ---------------------------------------------------------------------------
def _oracle(scene: dict) -> str:
    """Heuristic ground-truth mood for a scene — the labels we learn from.

    Priority: rush > busy > flat-energy lull > time-of-day slot.
    """
    occ = int(scene.get("occupancy", 0) or 0)
    queue = int(scene.get("queue_len", 0) or 0)
    energy = float(scene.get("staff_productivity", 0.0) or 0.0)
    hour = time.localtime(scene.get("ts") or time.time()).tm_hour
    if queue >= HIGH_QUEUE:
        return "rush_flow"
    if occ >= BUSY_OCC:
        return "busy_calm"
    if occ <= LULL_OCC and energy < 0.45:
        return "upbeat_lift"
    if 7 <= hour < 11:
        return "morning_rush"
    if 11 <= hour < 15:
        return "midday_dwell"
    return "afternoon_lounge"  # 15:00–close + pre-open


def _dataset() -> list[tuple[list[float], str]]:
    """Synthesize a labelled dataset across occupancy/queue/energy/hour."""
    rows: list[tuple[list[float], str]] = []
    base = time.mktime((2025, 1, 1, 0, 0, 0, 0, 0, -1))
    for hour in range(0, 24):
        ts = base + hour * 3600
        for occ in range(0, 14):
            for queue in range(0, 6):
                for energy in (0.2, 0.4, 0.6, 0.8):
                    scene = {
                        "ts": ts, "occupancy": occ, "queue_len": queue,
                        "staff_productivity": energy, "funnel": {"abandoned": queue // 2},
                    }
                    rows.append((features(scene), _oracle(scene)))
    return rows


def fit(data: list[tuple[list[float], str]], epochs: int = 300,
        lr: float = 0.3, l2: float = 1e-4) -> dict[str, list[float]]:
    """Softmax-regression gradient descent on a labelled (features, mood) dataset.

    Pure Python (no numpy) so it runs in the demo venv. Returns
    {mood_key: [weight per feature]}. Factored out of `train()` so federated
    learning (`federated.music_flock_model`) can fit on a *single venue's* data
    and then average the resulting weight vectors across cafés.
    """
    nfeat = len(FEATURE_NAMES)
    W = {k: [0.0] * nfeat for k in MOOD_KEYS}
    n = max(1, len(data))
    for _ in range(epochs):
        grads = {k: [0.0] * nfeat for k in MOOD_KEYS}
        for feats, label in data:
            scores = [sum(W[k][j] * feats[j] for j in range(nfeat)) for k in MOOD_KEYS]
            probs = _softmax(scores)
            for ki, k in enumerate(MOOD_KEYS):
                err = probs[ki] - (1.0 if k == label else 0.0)
                for j in range(nfeat):
                    grads[k][j] += err * feats[j]
        for k in MOOD_KEYS:
            for j in range(nfeat):
                W[k][j] -= lr * (grads[k][j] / n + l2 * W[k][j])
    return {k: [round(w, 4) for w in W[k]] for k in MOOD_KEYS}


def train(epochs: int = 300, lr: float = 0.3, l2: float = 1e-4) -> dict[str, list[float]]:
    """Fit weights on the full oracle-labelled dataset (bakes DEFAULT_WEIGHTS)."""
    return fit(_dataset(), epochs=epochs, lr=lr, l2=l2)


# Locally-trained weights (produced by `train()`); deterministic & offline.
# feature order: bias, occ, queue, energy, morning, midday, late_aft, busy, lull, rush
DEFAULT_WEIGHTS: dict[str, list[float]] = {
    "morning_rush":     [0.0174, -0.1809, -0.2193,  0.2189,  1.5841, -0.4925, -1.0742, -0.6068, -0.1401, -0.4682],
    "midday_dwell":     [0.0174, -0.1809, -0.2193,  0.2189, -0.4925,  1.5841, -1.0742, -0.6068, -0.1401, -0.4682],
    "afternoon_lounge": [0.4225, -0.2406, -0.4422,  0.8462, -0.7433, -0.7433,  1.9092, -1.5806, -0.5336, -1.1359],
    "rush_flow":        [-0.4427, 0.0086,  1.9446, -0.1962, -0.1776, -0.1776, -0.0875,  0.3298, -0.1918,  4.4445],
    "busy_calm":        [-0.2424, 1.3599, -0.7602, -0.0908, -0.1275, -0.1275,  0.0127,  3.0469, -0.9787, -1.6390],
    "upbeat_lift":      [0.2278, -0.7661, -0.3036, -0.9971, -0.0431, -0.0431,  0.3141, -0.5825,  1.9843, -0.7332],
}

_WEIGHTS_FILE = os.path.join(os.path.dirname(__file__), "music_weights.json")
# If a trained-weights file exists next to this module, prefer it (lets you
# re-train on real data without editing code). Falls back to baked defaults.
try:
    if os.path.exists(_WEIGHTS_FILE):
        with open(_WEIGHTS_FILE) as _fh:
            _loaded = json.load(_fh)
        if set(_loaded) == set(MOOD_KEYS):
            DEFAULT_WEIGHTS = {k: [float(x) for x in _loaded[k]] for k in MOOD_KEYS}
except Exception:
    pass


# ---------------------------------------------------------------------------
# CLI: --train refits & writes music_weights.json; default runs a demo roll.
# ---------------------------------------------------------------------------
def _demo() -> None:
    from shared.mock_events import _synthetic_scene

    print("=== local music model — mood over synthetic scenes ===\n")
    model = MusicModel()
    current: str | None = None
    base = time.time()
    for t in range(0, 75, 3):
        scene = _synthetic_scene(t).model_dump()
        scene["ts"] = base + t * 60  # advance ~1 min/step so time-of-day moves
        directive, changed = model.recommend(scene, current)
        flag = "▶ switch" if changed else "  hold  "
        print(
            f"t={t:>2} occ={scene['occupancy']:>2} q={scene['queue_len']} "
            f"energy={scene['staff_productivity']:.2f}  {flag}  "
            f"{directive.label:<16} {directive.bpm}bpm vol={directive.volume} "
            f"p={directive.confidence:.2f}"
        )
        if changed:
            print(f"        ↳ {directive.rationale}")
        current = directive.mood


def _train_cli() -> None:
    print("[music] training local softmax model on oracle-labelled scenes…")
    W = train()
    with open(_WEIGHTS_FILE, "w") as fh:
        json.dump(W, fh, indent=2)
    # quick accuracy check against the oracle
    model = MusicModel(W)
    data = _dataset()
    correct = sum(
        1 for feats, label in data
        if max(MOOD_KEYS, key=lambda k: sum(w * f for w, f in zip(W[k], feats))) == label
    )
    print(f"[music] trained — oracle agreement {correct}/{len(data)} "
          f"({100*correct/len(data):.1f}%); wrote {_WEIGHTS_FILE}")
    for k in MOOD_KEYS:
        print(f"  {k:<18} {W[k]}")


if __name__ == "__main__":
    import sys
    if "--train" in sys.argv[1:]:
        _train_cli()
    else:
        _demo()
