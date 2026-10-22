# rba-demo-kaze

Kaze Labs' employee portal: the second relying party of the RokuSec demo (U-5).
It signs in through RokuSec's **light** hosted login (ADR-0036), linking with its
public client id (ADR-0039), and asks the IdP on every request what the session may do
(ADR-0029). It never talks to the risk engine.

| Page | Needs |
|---|---|
| `/` Inicio | `portal:read` |
| `/proyectos` read · create | `portal:read` · `projects:write` |
| `/configuracion` | `settings:manage` (admins only) |

Seeded users: `lucas@kazelabs.example` (admin), `martin@kazelabs.example` (member),
`valen@kazelabs.example` (viewer); password `<name>-demo` locally.

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ../rba-contracts -e '.[dev]'
.venv/bin/uvicorn rba_demo_kaze.main:app --port 8003   # IdP on :8001
.venv/bin/pytest
```
