# 🔒 Privacy

Privacy isn't a feature bolted onto Caffe Steve — it's the premise. The product only works if a
café owner can point it at their existing camera without it becoming surveillance. So the design
goal is simple: **understand the room, never the person.**

## The stance

> Caffe Steve is an ambient + ops copilot, **not** a surveillance tool. **No employee scoring.
> No demographics. No facial recognition. No surge pricing. No using discomfort to move people
> along.** Every action helps the customer or the staff.

This isn't just policy — it's enforced in the schema and the perception pipeline.

## What is *not* stored

- ❌ **Faces.** Detected faces are **blurred on-device** before anything downstream sees a frame
  (`perception/run.py`): MediaPipe face detection where available, falling back to an OpenCV Haar
  cascade, falling back to blurring the top portion of each person box. Faces never leave the
  camera unblurred.
- ❌ **Identities.** Tracking uses **ephemeral ByteTrack IDs** — an integer that exists only while a
  person is on screen. The schema comment is explicit: it is *"NOT a person identity."* Stale tracks
  are purged after a short expiry so dead IDs never accumulate.
- ❌ **Demographics.** No age, gender, or any biometric inference anywhere in the pipeline.
- ❌ **Raw video off-site.** Federated learning shares only capacity-normalized ratios and model
  weights between cafés — **no footage ever leaves a venue.**

## What *is* stored

- ✅ **Aggregate counts and states** — occupancy, queue length, the funnel, per-table wait/cleaning
  status, a coarse dwell heatmap, room-energy score. These are numbers about *the room*, not people.
- ✅ **The agent's action log** — each `AgentAction` with its plain-English rationale.
- ✅ **A compact metrics history** (`data/metrics.jsonl`) for the footfall forecast and the pitch.

## Hardened privacy mode

Running perception with `--privacy-mode` tightens it further:

- **Strips all bounding boxes** from emitted `SceneEvent`s, so even box coordinates don't leave the
  device.
- **Adds Laplacian differential-privacy noise** to the heatmap grid, so individual paths can't be
  reconstructed from the aggregate.

## Verifiable, not just claimed

Because the on-chain snapshot (`POST /onchain/snapshot`) anchors **aggregate metrics + the action
audit trail** — not video — to Walrus, anyone can independently verify *what the AI did* without any
personal data ever being involved. Transparency is part of the privacy story, not in tension with it.

## A note on the optional Claude path

When the optional Claude tool-use path is enabled, the model receives a **compact, anonymized scene
summary** (counts, queue, room energy, funnel, table/cleaning states) — never images, never identities.
The system prompt explicitly forbids individual tracking, surge pricing, and discomfort.
