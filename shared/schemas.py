"""Shared data contracts for Golden Coffee.

These are the ONLY thing the four workstreams must agree on. Perception produces
`SceneEvent`s; the agent produces `AgentAction`s. Everything else (backend,
dashboard, actuators) talks in terms of these two shapes. Keep this file stable —
changing it means coordinating across all four people.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

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
    source: Literal["mock", "perception"] = "mock"


# ---------------------------------------------------------------------------
# Agent output: actions the system takes on the real world.
# ---------------------------------------------------------------------------
ActionName = Literal[
    "set_music_volume",
    "set_temperature",
    "push_discount",
    "notify_staff",
    "suggest_layout",
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
Message = SceneEvent | AgentAction
