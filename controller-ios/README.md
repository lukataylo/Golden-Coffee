# Coffee Steve — native iOS/iPadOS café controller

App icon + brand: **Coffee Steve** (`App/Assets.xcassets/AppIcon.appiconset`, from `CoffeeSteve.svg`). Xcode project/bundle id and the `GoldenCoffeeKit` package keep their internal names.

A native **SwiftUI** controller for the café‑ambiance system, styled
after Apple Home, with an **on‑device autopilot** (Yao's rules ported to Swift),
**Apple Foundation Models** for natural‑language commands (no cloud AI calls), a
**3D coffee‑shop model** wired to the live CCTV, and a **Gemini‑powered layout
generator** with UK coffee‑shop presets.

Built spec‑first with **codeplain** (`spec/golden_coffee_control.plain`); the
companion `spec/golden_coffee_brain.plain` is rendered by codeplain to a working
artifact in `spec/dist/`.

## Architecture

```
controller-ios/
├── spec/                         # codeplain specs (.plain) + rendered brain (dist/)
├── Package.swift                 # GoldenCoffeeKit — pure-Foundation, builds & tests without Xcode
├── Sources/GoldenCoffeeKit/
│   ├── Models/                   # SceneEvent, AgentAction, ComfortIndex, Geometry, RoomLayout, JSONValue …
│   ├── Comfort/ComfortScore      # port of shared/comfort.py
│   ├── Policy/                   # PolicyEngine (Yao's rules, energy-bug fixed), MusicModel, Discounts
│   ├── Networking/               # BackendClient, WebSocketClient, MJPEGDecoder
│   ├── Intelligence/             # CommandParser + KeywordParser
│   └── Layout/                   # CoffeeShopPresets, ProceduralLayout, GeminiLayoutClient
├── Tests/GoldenCoffeeKitTests/   # 19 tests: parity vs Python oracle + layout + Codable
├── App/                          # SwiftUI app (xcodegen project)
│   ├── Support/Theme, Components/ …  Apple-Home glass UI
│   ├── State/AppModel            # live data in, on-device decisions out, layout gen
│   ├── Intelligence/FoundationModelsBridge   # on-device LLM (guarded) + keyword fallback
│   └── Views/                    # Home, Controls, Camera, Map(3D), Autopilot, Settings, Onboarding
└── tools/gen_oracle.py           # regenerates the Python golden vectors
```

**Two layers:** `GoldenCoffeeKit` imports only Foundation, so the brain compiles
and unit‑tests with `swift test` on any machine. The app is a thin SwiftUI shell;
`FoundationModels` and `.glassEffect`/SceneKit live only in the app target.

## Build & run

```bash
cd controller-ios
swift test                                   # 19 tests (brain parity + layout)
xcodegen generate                            # regenerate the Xcode project
xcodebuild -project GoldenCoffeeControl.xcodeproj -scheme GoldenCoffeeControl \
  -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17 Pro' build
```
Open `GoldenCoffeeControl.xcodeproj` in Xcode 26 and run on an iPhone 15 Pro+/iPad
(or the iOS 26 Simulator). Foundation Models needs Apple Intelligence enabled; the
app degrades to a keyword parser otherwise.

### Demo launch flags (env)
`GC_SKIP_ONBOARDING=1` jump past setup · `GC_TAB=0..4` initial tab ·
`GC_AUTOPILOT=1` arm autopilot · `GC_GEN_PROMPT="…"` generate a layout on launch ·
`GEMINI_API_KEY=…` enable Gemini layout generation.

## How it meets the brief

| Requirement | Where |
|---|---|
| Native iPhone/iPad app, Apple‑Home glass UI | SwiftUI, `Theme`/`GlassCard`, `TARGETED_DEVICE_FAMILY 1,2` |
| Local model, **no cloud API calls** | `FoundationModelsBridge` (on‑device) + `KeywordParser`; `/ask` is never called |
| On‑device autopilot from camera/mic scenes | `PolicyEngine.decide` (Yao's rules) on each `/ws` SceneEvent → `/override` |
| Yao's commit rules | `Policy/` ported from `agent/policy.py` (the undefined‑`energy` crash is fixed) and parity‑tested |
| CCTV | `MJPEGView` (`/stream` + `/frame.jpg`), faces blurred server‑side |
| 3D map | `MapView` SceneKit coffee‑shop, located lights/speakers/cameras, tap a camera → live feed |
| User + café setup, add devices, music service | `OnboardingView` / `SettingsView` (Spotify OAuth) |
| Drives real Xiaomi/lights/scent | `BackendClient.override` → existing hub actuators |
| 3D layout generation | `GeminiLayoutClient` (structured schema) + `ProceduralLayout` fallback + 5 UK presets |

## Verification

- **`swift test` → 19/19 green.** `PolicyEngine`, `ComfortScore`, `MusicModel`,
  `KeywordParser` are asserted against golden vectors generated from the actual
  Python (`tools/gen_oracle.py`). Layout: presets validity, Codable round‑trips,
  Gemini‑response parsing, procedural keyword mapping, normalization.
- **App builds for the iOS 26 Simulator** (`BUILD SUCCEEDED`); every screen
  screenshotted in `shots/`.
- **Live backend**: `POST /override` returns `{"ok":true}`; `/ws` drives the gauge.
- **Adversarial review**: each layer was reviewed by an independent agent tasked to
  find faults; the critical WebSocket data race, duplicate‑audit echo, reconnect
  race and map‑tap issues were fixed.

Note: SceneKit bloom/HDR/SSAO render best on device (the Simulator's Metal path is
limited). Gemini generation is free‑tier rate‑limited; the app falls back to the
on‑device generator automatically.

## Who it's for (go‑to‑market)

Independent UK café owners and small chains who want Apple‑Home‑simple ambiance
control that runs **on‑device, privately** — no cloud AI, faces blurred locally.
The wedge: comfort autopilot + a one‑tap "design your space" 3D twin. Waitlist
capture lives on the marketing site (`landing/`).
