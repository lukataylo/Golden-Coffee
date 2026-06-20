"""Shared data contracts for Golden Coffee.

These are the ONLY thing the four workstreams must agree on. Perception produces
`SceneEvent`s; the agent produces `AgentAction`s. Everything else (backend,
dashboard, actuators) talks in terms of these two shapes. Keep this file stable —
changing it means coordinating across all four people.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Zones — the named regions the camera is divided into.
# ---------------------------------------------------------------------------
class Zone(str, Enum):
    ENTRY = "entry"
    QUEUE = "queue"
    COUNTER = "counter"
    SEATING = "seating"
    OFF = "off"  # outside any defined zone


class Role(str, Enum):
    CUSTOMER = "customer"
    STAFF = "staff"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Perception output: one SceneEvent per processed tick (~1-2 Hz is plenty).
# ---------------------------------------------------------------------------
class Track(BaseModel):
    id: int                         # ephemeral ByteTrack id (NOT a person identity)
    role: Role = Role.UNKNOWN
    zone: Zone = Zone.OFF
    dwell_s: float = 0.0            # seconds in current zone
    activity: float = 0.0           # 0..1 movement/activity score (for staff productivity)
    bbox: Optional[list[float]] = None  # [x1,y1,x2,y2] normalized 0..1 (faces blurred upstream)


class Funnel(BaseModel):
    entered: int = 0
    approached: int = 0   # reached the counter/queue
    ordered: int = 0      # dwell at counter long enough to be a purchase proxy
    seated: int = 0
    abandoned: int = 0    # left the queue without ordering


class Table(BaseModel):
    """A named table region: live wait state + cleaning/bussing state."""
    id: str                         # "T1"
    occupied: bool = False
    party_size: int = 0             # customers currently at the table
    occupied_s: float = 0.0         # seconds the table has been occupied
    wait_s: float = 0.0             # seconds waiting (since seated / last staff visit)
    status: Literal["empty", "seated", "waiting", "overdue"] = "empty"
    # cleaning / turnover
    needs_cleaning: bool = False    # vacated and not yet bussed
    since_clean_s: float = 0.0      # seconds since last cleaned/bussed
    uses_since_clean: int = 0       # parties served since last clean


class CleaningZone(BaseModel):
    """A zone whose cleaning cadence is tracked by usage + elapsed time
    (e.g. restroom, counter, high-traffic area)."""
    id: str                         # "restroom"
    uses_since_clean: int = 0       # entries since last clean
    since_clean_s: float = 0.0      # seconds since last cleaned
    status: Literal["ok", "due", "overdue"] = "ok"


class SceneEvent(BaseModel):
    type: Literal["scene"] = "scene"
    ts: float                       # unix seconds (producer-stamped)
    tracks: list[Track] = Field(default_factory=list)
    occupancy: int = 0              # customers currently inside
    queue_len: int = 0
    funnel: Funnel = Field(default_factory=Funnel)
    cups_made: int = 0              # cumulative drinks detected at counter
    heatmap_grid: Optional[list[list[float]]] = None  # coarse dwell-density grid for flow/layout
    staff_productivity: float = 0.0  # 0..1 aggregate, anonymized
    tables: list[Table] = Field(default_factory=list)       # per-table wait + cleaning
    cleaning: list[CleaningZone] = Field(default_factory=list)  # cleaning cadence by zone
    walkaway_gbp: Optional[float] = None   # cumulative revenue lost to queue walk-offs today
    forecast_next_hour: Optional[int] = None  # predicted occupancy for the next clock hour
    source: Literal["mock", "perception"] = "mock"


# ---------------------------------------------------------------------------
# Agent output: actions the system takes on the real world.
# ---------------------------------------------------------------------------
ActionName = Literal[
    "set_music_volume",   # Spotify volume 0-100
    "set_music",          # local music model: switch mood/playlist {mood, playlist_uri, bpm, energy, volume}
    "set_temperature",    # AC/heater via IR: {delta_c}
    "set_lighting",       # smart lights: {brightness 0-100, warmth: warm|neutral|cool}
    "set_scent",          # scent diffuser: {intensity 0-100, scent}
    "push_discount",
    "notify_staff",
    "suggest_layout",
    "tune_policy",        # federated learning: cross-café threshold update {lull, high, queue, n_nodes}
]


class AgentAction(BaseModel):
    type: Literal["action"] = "action"
    ts: float
    action: ActionName
    params: dict = Field(default_factory=dict)   # e.g. {"volume": 55} or {"text": "20% off pastries"}
    rationale: str = ""                          # plain-English why, shown on the dashboard
    reversible: bool = True
    auto: bool = True                            # False if triggered by a human override


# Convenience union for anything broadcast over the websocket.
Message = Union[SceneEvent, AgentAction]
