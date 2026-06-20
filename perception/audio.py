"""Audio sensing for the Comfort Index — loudness + acoustic stress.

We listen to the room through any available microphone and turn the raw waveform
into two numbers the rest of the system understands:

  * **loudness (dB SPL, approximate)** — how loud the room is. We measure RMS in
    dBFS and apply a fixed calibration offset to land in a plausible SPL range.
    It is *relative* (uncalibrated mics vary), but stable enough to drive
    comfort and to detect "it just got loud in here".

  * **acoustic stress (0–100)** — how *unpleasant* the soundscape is, separate
    from raw level. A steady 62 dB of chatter is calm; the same average level
    full of clatter, spikes and shouting is stressful. We blend three cues:
        - over-loudness   : sustained level above the comfortable ceiling
        - choppiness      : short-term variability of loudness (peaky vs even)
        - harshness       : high-frequency energy ratio (clatter/screech skew bright)

Runs in a background thread; `read()` returns the latest smoothed snapshot
without blocking the perception loop. If `sounddevice` or a mic is unavailable
the monitor degrades to `enabled=False` and `read()` returns Nones, so the
Comfort Index simply drops the Sound pillar rather than breaking.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

# Calibration: dBFS (≤0) + offset ≈ dB SPL. A quiet room ~ -40 dBFS, a busy
# café ~ -22 dBFS; +90 maps those to ~50 and ~68 dB SPL. Tunable per venue.
DBFS_TO_SPL_OFFSET = 90.0
COMFORT_CEILING_DB = 68.0   # sustained level above this contributes to stress


class AudioMonitor:
    def __init__(self, samplerate: int = 16000, block_s: float = 0.25,
                 device: Optional[int] = None) -> None:
        self.samplerate = samplerate
        self.block = int(samplerate * block_s)
        self.device = device
        self.enabled = False
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._stream = None
        self._np = None
        # smoothed state
        self._db: Optional[float] = None
        self._stress: Optional[float] = None
        self._loud_hist: deque = deque(maxlen=24)   # ~6 s of loudness for choppiness
        self._harsh = 0.0

    def start(self) -> "AudioMonitor":
        try:
            import numpy as np
            import sounddevice as sd
            self._np = np
            self._stream = sd.InputStream(
                samplerate=self.samplerate, channels=1, blocksize=self.block,
                device=self.device, dtype="float32", callback=self._on_block,
            )
            self._stream.start()
            self.enabled = True
        except Exception as e:  # no portaudio, no mic, no numpy — degrade quietly
            print(f"[audio] disabled ({type(e).__name__}: {e}); Sound pillar will be omitted", flush=True)
            self.enabled = False
        return self

    def _on_block(self, indata, frames, time_info, status) -> None:
        np = self._np
        x = indata[:, 0].astype(np.float32)
        # RMS -> dBFS -> approx SPL
        rms = float(np.sqrt(np.mean(x * x)) + 1e-9)
        dbfs = 20.0 * math.log10(max(rms, 1e-7))
        spl = dbfs + DBFS_TO_SPL_OFFSET

        # harshness: fraction of spectral energy above ~2 kHz (clatter/screech)
        try:
            mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
            freqs = np.fft.rfftfreq(len(x), 1.0 / self.samplerate)
            total = float(mag.sum()) + 1e-9
            high = float(mag[freqs >= 2000].sum())
            harsh = high / total  # 0..1
        except Exception:
            harsh = 0.0

        with self._lock:
            # EWMA on loudness so the displayed dB is steady, not jittery
            self._db = spl if self._db is None else 0.6 * self._db + 0.4 * spl
            self._loud_hist.append(spl)
            self._harsh = 0.7 * self._harsh + 0.3 * harsh
            self._stress = self._compute_stress()

    def _compute_stress(self) -> float:
        np = self._np
        if not self._loud_hist:
            return 0.0
        db = self._db or 0.0
        # 1) over-loudness: how far sustained level sits above the comfort ceiling
        over = max(0.0, db - COMFORT_CEILING_DB)
        over_score = min(1.0, over / 12.0)            # +12 dB over ceiling -> maxed
        # 2) choppiness: std-dev of recent loudness (even rooms feel calm)
        std = float(np.std(np.array(self._loud_hist))) if len(self._loud_hist) > 2 else 0.0
        chop_score = min(1.0, std / 8.0)              # 8 dB swing -> maxed
        # 3) harshness: high-frequency energy ratio
        harsh_score = min(1.0, self._harsh / 0.45)    # 45% energy >2kHz -> maxed
        stress = 100.0 * (0.45 * over_score + 0.35 * chop_score + 0.20 * harsh_score)
        return max(0.0, min(100.0, stress))

    def read(self) -> dict:
        """Latest smoothed snapshot. dB/stress are None until the first block
        lands (or forever if disabled)."""
        with self._lock:
            return {
                "enabled": self.enabled,
                "sound_db": None if self._db is None else round(self._db, 1),
                "sound_stress": None if self._stress is None else round(self._stress, 1),
            }

    def close(self) -> None:
        self._stop.set()
        if self._stream is not None:
            try:
                self._stream.stop(); self._stream.close()
            except Exception:
                pass


if __name__ == "__main__":  # quick manual check: python -m perception.audio
    m = AudioMonitor().start()
    if not m.enabled:
        raise SystemExit("no audio device available")
    try:
        for _ in range(40):
            time.sleep(0.5)
            r = m.read()
            if r["sound_db"] is not None:
                print(f"{r['sound_db']:5.1f} dB   stress {r['sound_stress']:5.1f}", flush=True)
    finally:
        m.close()
