# Nazar test plan (v3)

Every feature → the test that covers it → status on the final code. Run everything with the commands at the end.
✅ = passing · ⚠️ = known issue (see the note and PROGRESS.md "Known issues") · ⏭ = not in scope (reason given).

Suites: **unit** = `pytest -q` (no network) · **routes** = `tests/test_routes.py` (every API route, dev DB) ·
**triggers** = `tests/test_triggers_recorded.py` (recorded footage) · **telegram** = `tests/test_telegram.py` ·
**live** = `pytest -m live` (real OpenAI calls) · **e2e** = `scripts/e2e.mjs` (real Chrome, 1440×900 + 390×844,
dark + light) · **voice** = `scripts/eval_voice_matrix.py` · **battery** = `scripts/eval_battery.py` ·
**counts** = `scripts/eval_counts.py` · **privacy** = `scripts/privacy_spotcheck.py` · **smoke** = `scripts/smoke.ps1`.

## 1. Product features (v2 review "Works" list)
| Feature | Covered by | Status |
|---|---|---|
| Login with passcode, wrong passcode rejected, forged token rejected | routes `test_auth_*`, e2e `login` | ✅ |
| Every route needs the token (only `/api/auth`, `/api/health` public) | routes `test_every_route_needs_a_token_except_public` (sweeps all 66 routes) | ✅ |
| Upload a video → live analysis view (boxes, counts) → ready | e2e `upload short clip + live analysis`, routes `test_upload_init_part_status` | ✅ |
| CCTV/DVR builder + Test connection (explains the failure) | routes `test_onboarding_presets_test_template_import` | ✅ |
| CCTV camera added with an encrypted password (never returned) | routes (same test: `/api/cameras/rtsp`, then the password is absent from GET) | ✅ |
| Excel/CSV template + import probes each row | routes `test_onboarding_presets_test_template_import` | ✅ |
| Phone camera (Larix QR / SRT URL) | routes `test_phone_setup_and_discover` | ✅ |
| Camera CRUD, zones saved, 404 on unknown | routes `test_camera_*` | ✅ |
| Zones + count lines → enter / exit / dwell / cross events | unit `test_eventizer.py` (10 tests) | ✅ |
| Counts from SQL with receipts (receipts == number) | unit `test_api_smoke::test_count_matches_sql`, routes `test_count_equals_sql_and_receipts`, voice (SQL recomputed for every spoken count), battery | ✅ |
| Peak occupancy carries receipts (the tracks present at the peak) | battery Q29 | ✅ |
| Motorcycle/bicycle riders are not "people on foot" (v3 #5) | unit `test_riders.py` (4), counts (3/3 windows exact) | ✅ |
| Server-written count answers (one model round) in en/hi/hinglish | unit `test_agent::test_count_reply_is_written_from_the_sql_result`, voice | ✅ |
| Any analysis: one read-only SQL over whitelisted views, SQL shown | battery Q7–10, Q30; e2e `any analysis with SQL` | ✅ |
| Heatmap | battery Q20, e2e `heatmap` | ✅ |
| Hindi voice note → Hindi spoken reply | voice (12/12, 8 languages, webm + m4a), e2e voice in the film recording | ✅ |
| Face request refused (no face recognition) | battery Q24, e2e `privacy: face request refused`, telegram (face-only photo refused in code) | ✅ |
| Search by words (local SigLIP 2 index) | routes `test_visual_search_text_and_photo_audit`, battery Q13–16, Q31, e2e `search by words` | ✅ |
| AI verification of top hits → Probable only with a recorded AI "yes" | unit `test_levels::test_visual_levels_only_from_a_recorded_ai_yes`, e2e `verify top hits with AI` | ✅ |
| Journey (same look across cameras, clothes/objects only) | routes `test_search_tracks_similar_journey`, e2e `journey clip plays` | ✅ |
| Search by photo, purpose audited, face-only photo refused | routes (audit list), telegram `test_photo_search_sends_candidates`, e2e `photo search (audited)` | ✅ |
| Teach by text (open-vocabulary YOLOE) → replay on stored frames | triggers `test_custom_object_replays_on_stored_frames`, routes `test_custom_object_create_list_delete`, e2e `teach` | ✅ |
| Teach by photo (SigLIP 2) → live sighting alert | `scripts/live_alert_test.py --photo` (v2: alert 23 s after the object appeared) | ✅ |
| Rule by voice/text → compiled spec → replay yesterday → activate | live `test_rule_compile_and_report`, battery Q22, e2e `rule … activate` | ✅ |
| Live alert (rule fires on a camera playing as live) + voice note | `scripts/live_alert_test.py`, e2e `simulated live alert arrives` (`--live`), the film recording | ✅ |
| WebRTC live view with overlay, faces blurred | `scripts/webrtc_check.mjs` | ✅ |
| Live edge speed (v3 #3) | edge summary `loop_fps` (7.9–8.6 fps with all services up) | ⚠️ analysed frames ≈ 6/s (target 8) |
| Incident PDF (timeline, blurred frames, AI text marked, hashes; Hindi renders) | live `test_rule_compile_and_report` (Hindi PDF), telegram `test_report_command_sends_pdf`, e2e `incident PDF downloads` | ✅ |
| Security pack + events (object taken, abandoned, loitering, crowding, after-hours) | triggers (recorded footage), unit `test_security.py` | ✅ |
| Running / fall | unit `test_security.py` (synthetic paths); triggers check no false alarms on 200+ calm tracks | ⚠️ no demo clip with a real run or fall |
| Possible snatch | unit `test_security.py` | ⏭ snatch dataset not downloaded (multi-GB; v3 #8) |
| Morning digest (text + voice) | routes `test_security_digest_reports_settings_pair`, telegram `test_today_digest` | ✅ |
| Insights: measured costs, speed, accuracy (no raw JSON) | routes (`/api/metrics`), e2e `insights` | ✅ |

## 2. Evidence levels and privacy
| Rule | Covered by | Status |
|---|---|---|
| Levels decided by server code only; the model cannot promote | unit `test_levels.py` (13), `test_agent::test_model_cannot_inject_levels_via_answer` | ✅ |
| Confirmed numbers equal SQL | voice, battery (re-runs the SQL behind every Confirmed number) | ✅ |
| Every served media file is face-blurred | privacy spot-check: 11 files (crops, keyframes, alert snapshots, clip frames) → 0 faces | ✅ |
| Every clip: H.264, yuv420p, even size, faststart, first/middle frame not black | routes `test_clip_for_track_is_h264_yuv420p_even_and_not_black` | ✅ |
| Every kind of clip plays in real Chrome (receipt, proof reel, search hit, journey, alert, security event) | e2e `* clip plays` (currentTime advances + sampled frame luma > 10) | see e2e report |
| `/media` path traversal blocked | routes `test_clip_range_reel_and_media` | ✅ |
| No API key in `/api/settings` | routes `test_security_digest_reports_settings_pair` | ✅ |

## 3. Rule triggers on recorded footage
| Trigger | Covered by | Status |
|---|---|---|
| zone_enter, zone_exit, dwell_over (desk 14, office desk) | triggers `test_zone_triggers_fire_on_office_desk` | ✅ |
| object_removed (ABODA bag, with the taker) | triggers `test_object_removed_fires_with_the_person_who_took_it` | ✅ |
| count_over (busy lobby; not at an absurd threshold) | triggers `test_count_over_fires_in_the_busy_lobby_and_not_at_a_huge_threshold` | ✅ |
| time_window limits hits | triggers `test_time_window_limits_replay_hits`, unit `test_time_window_wraps_midnight` | ✅ |
| abandoned_object, loitering, crowding, after_hours | triggers (4 tests) | ✅ |
| running, fall | unit (synthetic) + triggers false-alarm check | ⚠️ see §1 |
| custom objects (YOLOE text / SigLIP photo) | triggers `test_custom_object_replays_on_stored_frames`, live_alert_test `--photo` | ✅ |

## 4. Telegram bot
| Path | Covered by | Status |
|---|---|---|
| Unpaired chat is asked to pair | telegram `test_unpaired_chat_is_asked_to_pair` | ✅ |
| /pair wrong code, right code, code works once | telegram `test_pairing_wrong_then_right_code` | ✅ |
| /start, /cameras | telegram `test_start_and_cameras` | ✅ |
| Text question → text + Confirmed line + voice note (OGG) + clip | telegram `test_text_question_gets_text_voice_and_clip` (live) | ✅ |
| Voice note (OGG) → transcript echoed → answer | telegram `test_voice_note_ogg` (live) | ✅ |
| Photo → audited photo search → candidates | telegram `test_photo_search_sends_candidates` | ✅ |
| /today digest, /report PDF | telegram `test_today_digest`, `test_report_command_sends_pdf` | ✅ |
| Alert push: snapshot + voice note + clip | telegram `test_alert_push_sends_snapshot_voice_and_clip` | ✅ |
| Rate limit | telegram `test_rate_limit` | ✅ |
| Real phone end-to-end (pairing, voice note, alert on the phone) | `scripts/telegram_selftest.py` (bot reachable as @nazar_hackathon_bot; no chat paired yet) | ⚠️ needs the owner's phone — 60-second test in FINAL_STEPS |

## 5. Screens (e2e, real Chrome)
Login · Today · Add camera (upload) · Ask (count, receipts, proof reel, analysis + SQL, heatmap, privacy, teach, rule)
· Search (words, verify, hit, journey, photo) · Alerts (inbox, alert clip, incident PDF, security events) · Settings
(pairing code) · Insights — each at 1440×900 and 390×844, dark and light; no console errors, no failed API calls,
no spinner stuck > 15 s, no horizontal overflow. Report: `<DATA_DIR>/e2e/<run>/report.json` + screenshots.

## 6. Not in scope (recorded as not done)
- Snatch/theft dataset precision (multi-GB download) — v3 #8.
- Backend Docker image build (network timeouts here; build on EC2) — v3 #11.
- Marathi voice (transcription returns the wrong script) — v3 #9, not claimed.
- Chrome DevTools MCP: re-added with `--headless`, still "connection closed" — not needed (Playwright covers it).

## Run everything
```powershell
.\.venv\Scripts\Activate.ps1
cd backend; python -m pytest -q; python -m pytest -q -m live; cd ..
python scripts/privacy_spotcheck.py; python scripts/eval_counts.py; python scripts/eval_voice_matrix.py
python scripts/eval_battery.py; python scripts/telegram_selftest.py
cd web; node ../scripts/e2e.mjs --viewport both --theme both; cd ..
powershell -ExecutionPolicy Bypass -File scripts\smoke.ps1
```
