#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
OVERLAY = Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).resolve().parents[1] / "overlay").resolve()


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def replace_once(rel: str, old: str, new: str) -> None:
    s = read(rel)
    if old not in s:
        raise RuntimeError(f"marker not found in {rel}: {old[:80]!r}")
    write(rel, s.replace(old, new, 1))


# 1. Visible Windows branding.
replace_once("main_windows.go", 'Title:     "PWDTT",', 'Title:     "OBhoD",')

wails_path = ROOT / "wails.json"
wails = json.loads(wails_path.read_text(encoding="utf-8"))
wails["name"] = "OBhoD"
wails["outputfilename"] = "OBhoD"
wails.setdefault("author", {})["name"] = "OBhoD"
wails_path.write_text(json.dumps(wails, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# Frontend contains only visible branding references; replace PWDTT there, not in backend update URLs.
for p in (ROOT / "frontend").rglob("*"):
    if not p.is_file() or p.suffix.lower() not in {".ts", ".tsx", ".css", ".html", ".json"}:
        continue
    try:
        s = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    if "PWDTT" in s:
        p.write_text(s.replace("PWDTT", "OBhoD"), encoding="utf-8")

# Separate local state from the friend's PWDTT installation.
store = read("backend/store.go").replace('filepath.Join(base, "pwdtt")', 'filepath.Join(base, "obhod")')
write("backend/store.go", store)

autostart = read("backend/autostart.go").replace('"PWDTT"', '"OBhoD"').replace('Name=PWDTT', 'Name=OBhoD')
write("backend/autostart.go", autostart)

frontend_store = read("frontend/src/lib/store.ts")
frontend_store = frontend_store.replace("wdtt_servers:v1", "obhod_servers:v1")
frontend_store = frontend_store.replace("wdtt_settings:v1", "obhod_settings:v1")
frontend_store = frontend_store.replace("wdtt_last_server:v1", "obhod_last_server:v1")
write("frontend/src/lib/store.ts", frontend_store)

# 2. Add backend HTTPS Bronya importer.
shutil.copy2(OVERLAY / "backend" / "subscription.go", ROOT / "backend" / "subscription.go")

app = read("backend/app.go")
profile_marker = "func (a *App) ListProfiles() map[string]ProfileData {\n\treturn a.store.ListProfiles()\n}\n"
if "func (a *App) ImportSubscription(" not in app:
    if profile_marker not in app:
        raise RuntimeError("ListProfiles marker not found in backend/app.go")
    app = app.replace(
        profile_marker,
        profile_marker
        + "\n// ImportSubscription downloads one personal OBhoD Bronya profile from a copied HTTPS URL.\n"
        + "func (a *App) ImportSubscription(rawURL string) (*SubscriptionImportResult, error) {\n"
        + "\treturn FetchSubscription(rawURL)\n}\n",
        1,
    )

# Do not offer releases from the upstream PWDTT repository inside OBhoD.
app = re.sub(
    r"func \(a \*App\) CheckUpdate\(\) \*UpdateInfo \{.*?\n\}",
    'func (a *App) CheckUpdate() *UpdateInfo {\n\treturn &UpdateInfo{Available: false}\n}',
    app,
    count=1,
    flags=re.S,
)
write("backend/app.go", app)

# 3. Persist the source subscription URL in the frontend server model.
types = read("frontend/src/lib/types.ts")
if "subscriptionUrl?: string;" not in types:
    types = types.replace("  power?: number;\n", "  power?: number;\n  subscriptionUrl?: string;\n", 1)
write("frontend/src/lib/types.ts", types)

# 4. Add HTTPS subscription handling to the existing Add Server modal.
p = ROOT / "frontend/src/modals/Add-server.tsx"
s = p.read_text(encoding="utf-8")
s = s.replace(
    "import { SaveProfile } from '../../wailsjs/go/backend/App';",
    "import { SaveProfile, ImportSubscription } from '../../wailsjs/go/backend/App';",
    1,
)

if "const [subscriptionUrl" not in s:
    s = s.replace(
        "  const [hashOpen, setHashOpen] = useState(false);\n",
        "  const [hashOpen, setHashOpen] = useState(false);\n"
        "  const [subscriptionUrl, setSubscriptionUrl] = useState('');\n"
        "  const [importing, setImporting] = useState(false);\n"
        "  const [importError, setImportError] = useState('');\n",
        1,
    )

pattern = re.compile(r"  const applyLink = \(raw: string\) => \{.*?\n  \};\n\n  const handleHashSave", re.S)
replacement = r'''  const applyLink = async (raw: string) => {
    setLink(raw);
    setImportError('');
    const trimmed = raw.trim();

    if (/^https?:\/\//i.test(trimmed)) {
      if (trimmed.length < 25 || importing) return;
      setImporting(true);
      try {
        const result = await ImportSubscription(trimmed);
        setSubscriptionUrl(result.subscriptionUrl || trimmed);
        setName(result.name || 'OBhoD_BLOK');
        const peer = result.peer || '';
        const lastColon = peer.lastIndexOf(':');
        if (lastColon > 0 && lastColon < peer.length - 1 && /^\d+$/.test(peer.slice(lastColon + 1))) {
          setIp(peer.slice(0, lastColon));
          setPort(peer.slice(lastColon + 1));
        } else {
          setIp(peer);
          setPort('56000');
        }
        setPassword(result.password || '');
        const source = result.hashes || [];
        const h4: [string,string,string,string] = [source[0]??'', source[1]??'', source[2]??'', source[3]??''];
        setHashes(h4);
        const filled = h4.filter(x => x.trim()).length;
        setPower(result.workers > 0 ? result.workers : Math.max(9, filled * 9));
      } catch (e) {
        setSubscriptionUrl('');
        setImportError(e instanceof Error ? e.message : String(e));
      } finally {
        setImporting(false);
      }
      return;
    }

    setSubscriptionUrl('');
    const parsed = parseWdttUrl(trimmed);
    if (!parsed) return;
    const lastColon = parsed.host.lastIndexOf(':');
    if (lastColon > 0 && lastColon < parsed.host.length - 1) {
      setIp(parsed.host.slice(0, lastColon));
      setPort(parsed.host.slice(lastColon + 1));
    } else {
      setIp(parsed.host);
      setPort('56000');
    }
    setPassword(parsed.password);
    if (parsed.name !== 'Server') setName(parsed.name);
    if (parsed.hashes.length > 0) {
      const h4: [string,string,string,string] = [parsed.hashes[0]??'', parsed.hashes[1]??'', parsed.hashes[2]??'', parsed.hashes[3]??''];
      setHashes(h4);
      const filled = h4.filter(x => x.trim()).length;
      setPower(parsed.workers && parsed.workers > 0 ? parsed.workers : Math.max(9, filled * 9));
    }
  };

  const handleHashSave'''
if "const applyLink = async" not in s:
    s, n = pattern.subn(replacement, s, count=1)
    if n != 1:
        raise RuntimeError("applyLink marker not found in Add-server.tsx")

# Persist imported hashes in the Go profile too.
s = s.replace("        hashes: [],\n", "        hashes: hashes.filter(h => h.trim()),\n", 1)
s = s.replace(
    "    onAdd({ name: name.trim(), host, password, hashes, power });",
    "    onAdd({ name: name.trim(), host, password, hashes, power, subscriptionUrl: subscriptionUrl || undefined });",
    1,
)
s = s.replace("Добавление сервера", "Добавление профиля")
s = s.replace('placeholder="Вставьте ссылку wdtt://..."', 'placeholder="Вставьте ссылку Брони https://... или wdtt://..."')
s = s.replace('onChange={e => applyLink(e.target.value)}', 'onChange={e => { void applyLink(e.target.value); }}')
status_anchor = '          />\n\n          <div className="as-divider">или вручную</div>'
if "Броня загружена" not in s and status_anchor in s:
    s = s.replace(
        status_anchor,
        '          />\n'
        '          {importing && <div style={{ fontSize: 12, margin: \'-2px 0 10px\', color: \'var(--text-4)\' }}>Загрузка Брони...</div>}\n'
        '          {importError && <div style={{ fontSize: 12, margin: \'-2px 0 10px\', color: \'#ef4444\' }}>{importError}</div>}\n'
        '          {subscriptionUrl && !importing && <div style={{ fontSize: 12, margin: \'-2px 0 10px\', color: \'#22c55e\' }}>Броня загружена</div>}\n\n'
        '          <div className="as-divider">или вручную</div>',
        1,
    )
s = s.replace("disabled={!name.trim() || !ip.trim() || saving}", "disabled={!name.trim() || !ip.trim() || saving || importing}")
s = s.replace("{saving ? 'Сохранение...' : 'Добавить сервер'}", "{saving ? 'Сохранение...' : 'Добавить профиль'}")
p.write_text(s, encoding="utf-8")

# 5. Re-pasting the same Bronya URL updates that profile instead of creating a duplicate.
connect = read("frontend/src/pages/Connect.tsx")
old_handle = """  const handleAdd = (data: Omit<Server, 'id'>) => {\n    const s = serverStore.add(data);\n    setServers(serverStore.getAll());\n    setSelected(s);\n  };\n"""
new_handle = """  const handleAdd = (data: Omit<Server, 'id'>) => {\n    const existing = data.subscriptionUrl\n      ? serverStore.getAll().find(s => s.subscriptionUrl === data.subscriptionUrl)\n      : undefined;\n    if (existing) {\n      const updated: Server = { ...existing, ...data };\n      serverStore.update(updated);\n      setServers(serverStore.getAll());\n      setSelected(updated);\n      toastStore.show('Броня обновлена', 2500);\n      return;\n    }\n    const added = serverStore.add(data);\n    setServers(serverStore.getAll());\n    setSelected(added);\n  };\n"""
if old_handle in connect:
    connect = connect.replace(old_handle, new_handle, 1)
elif "const existing = data.subscriptionUrl" not in connect:
    raise RuntimeError("handleAdd marker not found in Connect.tsx")
write("frontend/src/pages/Connect.tsx", connect)

print("OBhoD Windows patch applied successfully")
