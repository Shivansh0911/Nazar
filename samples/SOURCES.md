# Demo footage — sources and licences

No venue camera was available, so the demo runs on downloaded clips that are stamped as last night's CCTV
footage by `scripts/demo_setup.py` (see `demo_manifest.yaml`). Re-download and normalize everything with
`python scripts/fetch_samples.py` (URL list in `sources.yaml`). Video files are not committed.

Normalized format: H.264, yuv420p, max 1280 px wide, max 30 fps, no audio, ≤ 5 min.

| File | Demo camera | Scene | Duration | Source | Author | Licence |
|---|---|---|---|---|---|---|
| `clip1.mp4` | `shop-counter` (Shop counter) | Street vegetable stall: vendor in a helmet, customers buying. Fixed eye-level camera, daylight, India. 1280×720 | 32 s | [Pexels 19949700](https://www.pexels.com/video/a-young-men-buying-on-street-vegetables-shop-19949700/) | GK Kumawat | Pexels License |
| `clip2.mp4` | `market-street` (Market street) | Busy Mumbai street from a footbridge: pedestrians, taxis, buses. Elevated, near-fixed. 1280×720 | 62 s | [Pexels 30230719](https://www.pexels.com/video/busy-mumbai-street-with-heavy-traffic-30230719/) | Aksinfo7 | Pexels License |
| `clip3.mp4` | `main-road` (Main road / parking side) | City road in front of shops: motorcycles, autos, cars, trucks, pedestrians. Elevated fixed view, India. 1280×720 | 28 s | [Pexels 28925595](https://www.pexels.com/video/busy-urban-traffic-scene-in-city-center-28925595/) | Karthick S | Pexels License |
| `clip4.mp4` | `lobby` (Lobby) | Large mall/transit lobby, people crossing the floor in front of shop entrances. Elevated fixed view. 1280×720 | 86 s | [Pexels 2985409](https://www.pexels.com/video/people-spending-time-inside-a-mall-2985409/) | Joshua Santos | Pexels License |
| `clip5.mp4` | `night-market` (Night stall) | Fruit stall at night under tube lights, customers at the counter. Fixed, low light. 1280×720 | 25 s | [Pexels 32166140](https://www.pexels.com/video/bustling-night-fruit-market-with-vibrant-colors-32166140/) | Riaz Uddin | Pexels License |
| `clip6_bag.mp4` | `office-desk` (Office desk) | INRIA entrance lobby from the ceiling (CAVIAR `LeftBag_PickedUp`): a bag is left, later picked up by someone else. 384×288 (edge upscales ×2) | 55 s | [CAVIAR dataset, first set](https://homepages.inf.ed.ac.uk/rbf/CAVIARDATA1/) | CAVIAR project / INRIA | Research use with acknowledgement |

Upload-test clips (not in the manifest): `extra_mall.mp4` ([Pexels 4750061](https://www.pexels.com/video/people-walking-inside-the-shopping-mall-4750061/), Anvar Tushakov),
`extra_leftbox.mp4` (CAVIAR `LeftBox`), `extra_portrait.mp4` (540×960 portrait, [Pexels 39545313](https://www.pexels.com/video/busy-city-street-intersection-with-pedestrians-and-cyclists-39545313/)),
`extra_4k.mp4` (3840×2160, [Pexels 4687383](https://www.pexels.com/video/top-view-of-people-walking-on-concrete-stairs-4687383/), Kelly).

**Pexels License:** free to use, modify and redistribute in projects; attribution not required (we credit the creators anyway).
**CAVIAR:** "If you publish results using the data, please acknowledge the data as coming from the EC Funded CAVIAR
project/IST 2001 37540, found at URL: http://homepages.inf.ed.ac.uk/rbf/CAVIAR/". We use it for a non-commercial
hackathon research demo and acknowledge it here and in the README.

Selection check (done on 2026-11-21): every clip was probed with ffprobe and three frames per clip were extracted to
`data/inspect/` and reviewed — fixed camera (no pan/drone), people at small-to-medium size, correct orientation.
Rejected candidates: drone/aerial parking clips and a handheld Indian street clip (camera moves).
