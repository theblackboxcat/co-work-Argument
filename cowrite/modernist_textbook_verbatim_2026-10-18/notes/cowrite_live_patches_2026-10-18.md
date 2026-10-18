# Cowrite-test live patches · 2026-10-18

Source (laptop): `C:\deepseekharness\cowrite-dist\Cowrite-test\app\`

| File | Change |
|------|--------|
| `v3/SKILL_v3.md` | Grafted `textbook_verbatim_v2.5b` into `policy.build_system` content stance (mode/ban placeholders kept; speak-gate unchanged) |
| `providers.py` | Disable thinking for `longcat.chat` base_url (else empty `content`) |
| `server.py` | `_loads_tool_json` collapses doubled braces `{{call…}}` from LongCat tool fences |

**Not included:** live `config.json` (has keys). Use `config.example.json` + env / local secrets.

Not a 知音 claim. Speak-gate ≠ modernism ≠ 知音.

## Public landing

These notes sit with the 2026-10-18 content-stance pack. The three files were copied onto `cowrite/Cowrite-test/app/`. `providers.py` keeps the repo placeholder `http://<API_HOST>`; the laptop dots3 host was not committed. No live `config.json` and no API keys.

