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


# Windows must elevate before creating the WireGuard TUN interface.
# Embedding requireAdministrator makes Windows show UAC automatically on launch.
manifest_path = ROOT / "build" / "windows" / "wails.exe.manifest"
manifest = manifest_path.read_text(encoding="utf-8")
admin_level = '<requestedExecutionLevel level="requireAdministrator" uiAccess="false"/>'
if admin_level not in manifest:
    closing_tag = "</assembly>"
    if closing_tag not in manifest:
        raise RuntimeError("Windows manifest closing tag not found")
    trust_info = """    <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
        <security>
            <requestedPrivileges>
                <requestedExecutionLevel level="requireAdministrator" uiAccess="false"/>
            </requestedPrivileges>
        </security>
    </trustInfo>
"""
    manifest = manifest.replace(closing_tag, trust_info + closing_tag, 1)
manifest_path.write_text(manifest, encoding="utf-8")

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
    s, n = pattern.subn(lambda _m: replacement, s, count=1)
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

# 6. Windows: restore the original default-route metric instead of hardcoded 35.
wg = read("backend/wg.go")
if "physMetric" not in wg:
    wg = wg.replace(
        "\tphysGW              string // physical gateway saved during apply for restore on teardown",
        "\tphysGW              string // physical gateway saved during apply for restore on teardown\n"
        "\tphysMetric          string // original metric of the physical default route",
        1,
    )
    metric_fn = '''
func defaultRouteMetricWindows(gw string) string {
\tcmd := exec.Command("cmd", "/c", "route print 0.0.0.0")
\thideWindow(cmd)
\tout, err := cmd.Output()
\tif err != nil {
\t\treturn ""
\t}
\tfor _, line := range strings.Split(string(out), string([]byte{10})) {
\t\tfields := strings.Fields(line)
\t\tif len(fields) >= 5 && fields[0] == "0.0.0.0" && fields[1] == "0.0.0.0" && fields[2] == gw {
\t\t\treturn fields[4]
\t\t}
\t}
\treturn ""
}
'''
    parse_marker = "func parseCIDR(cidr string) (ip, mask string, err error) {"
    if parse_marker not in wg:
        raise RuntimeError("parseCIDR marker not found in backend/wg.go")
    wg = wg.replace(parse_marker, metric_fn + "\n" + parse_marker, 1)
    wg = wg.replace("\t\tw.physGW = gw\n", "\t\tw.physGW = gw\n\t\tw.physMetric = defaultRouteMetricWindows(gw)\n", 1)
    old_restore = '\tif w.physGW != "" {\n\t\t_ = runCmdWindows("route", "change", "0.0.0.0", "mask", "0.0.0.0", w.physGW, "metric", "35")\n\t\tw.physGW = ""'
    new_restore = '\tif w.physGW != "" {\n\t\tmetric := w.physMetric\n\t\tif metric == "" {\n\t\t\tmetric = "35"\n\t\t}\n\t\t_ = runCmdWindows("route", "change", "0.0.0.0", "mask", "0.0.0.0", w.physGW, "metric", metric)\n\t\tw.physGW = ""\n\t\tw.physMetric = ""'
    if old_restore not in wg:
        raise RuntimeError("physGW restore marker not found in backend/wg.go")
    wg = wg.replace(old_restore, new_restore, 1)
    write("backend/wg.go", wg)
    print("Windows metric restore patch applied")

# 7. Honest connection status and neutral DTLS timeout wording.
bridge = read("backend/bridge.go")
if "[WG] Конфиг применён, туннель активен" in bridge:
    bridge = bridge.replace(
        '"[WG] Конфиг применён, туннель активен"',
        '"[WG] Конфиг применён, ожидаем подтверждение WireGuard"',
        1,
    )
    write("backend/bridge.go", bridge)
    print("Honest config status applied")

session = read("core/session.go")
if "DTLS timeout, пароль/WRAP не подтверждён" in session:
    session = session.replace(
        '"DTLS timeout, пароль/WRAP не подтверждён"',
        '"DTLS timeout: relay не ответил"',
        1,
    )
    write("core/session.go", session)
    print("Neutral DTLS timeout wording applied")

# 8. Separate TURN quota (486) from a dead address.
sess = read("core/session.go")
if "SessionErrorQuota" not in sess:
    sess = sess.replace(
        '\tSessionErrorAddressDead SessionErrorType = "ADDRESS_DEAD"',
        '\tSessionErrorAddressDead SessionErrorType = "ADDRESS_DEAD"\n'
        '\t// SessionErrorQuota — квота звонка/адреса исчерпана, адрес не «мёртв».\n'
        '\tSessionErrorQuota SessionErrorType = "TURN_QUOTA"',
        1,
    )
    old_quota = '\t\t// Квота, unreachable, timeout — всё это "адрес мёртв"\n\t\tif strings.Contains(errLower, "quota") ||\n\t\t\tstrings.Contains(errLower, "486") ||\n\t\t\tstrings.Contains(errLower, "unreachable") ||'
    new_quota = '\t\t// 486 — квота звонка/адреса исчерпана, но адрес не «мёртв»: не баним.\n\t\tif strings.Contains(errLower, "quota") || strings.Contains(errLower, "486") {\n\t\t\treturn false, &SessionError{Type: SessionErrorQuota, Address: turnAddr, Err: fmt.Errorf("TURN Allocate: %w", err)}\n\t\t}\n\n\t\t// unreachable, timeout — адрес недоступен\n\t\tif strings.Contains(errLower, "unreachable") ||'
    if old_quota not in sess:
        raise RuntimeError("quota marker not found in core/session.go")
    sess = sess.replace(old_quota, new_quota, 1)
    write("core/session.go", sess)

    wg = read("core/worker_group.go")
    case_anchor = "\t\t\t\t\tcase SessionErrorAddressDead:"
    case_new = "\t\t\t\t\tcase SessionErrorQuota:\n\t\t\t\t\t\t// Квота — не мёртвый адрес: не баним, короткая пауза и повтор.\n\t\t\t\t\t\tlog.Printf(\"[ВОРКЕР #%d] TURN-квота исчерпана на %s, адрес не баним\", wid, sessErr.Address)\n\t\t\t\t\t\ttime.Sleep(3 * time.Second)\n\n" + case_anchor
    if case_anchor not in wg:
        raise RuntimeError("worker_group case marker not found")
    wg = wg.replace(case_anchor, case_new, 1)
    write("core/worker_group.go", wg)
    print("TURN quota classification applied")

# 9. "All retransmissions failed" is transient, not fatal.
sess = read("core/session.go")
if "SessionErrorTransient" not in sess:
    sess = sess.replace(
        'SessionErrorQuota SessionErrorType = "TURN_QUOTA"',
        'SessionErrorQuota SessionErrorType = "TURN_QUOTA"\n'
        '\t// SessionErrorTransient — нет ответа после ретрансмиссий: повторить, не выходить.\n'
        '\tSessionErrorTransient SessionErrorType = "TRANSIENT"',
        1,
    )
    fatal_anchor = "\t\t// Остальные ошибки — фатальные"
    transient = ('\t\t// Нет ответа после ретрансмиссий — транзиентная ошибка, не фатальная.\n'
                 '\t\tif strings.Contains(errLower, "all retransmissions failed") {\n'
                 '\t\t\treturn false, &SessionError{Type: SessionErrorTransient, Address: turnAddr, Err: fmt.Errorf("TURN Allocate: %w", err)}\n'
                 '\t\t}\n\n') + fatal_anchor
    if fatal_anchor not in sess:
        raise RuntimeError("fatal marker not found in core/session.go")
    sess = sess.replace(fatal_anchor, transient, 1)
    write("core/session.go", sess)
    print("Transient allocate failure classification applied")

# 10. DTLS timeout is its own type: retry via default without rotating obfuscation.
sess = read("core/session.go")
if "SessionErrorDtlsTimeout" not in sess:
    sess = sess.replace(
        '\tSessionErrorWrapTimeout SessionErrorType = "WRAP_TIMEOUT"',
        '\tSessionErrorWrapTimeout SessionErrorType = "WRAP_TIMEOUT"\n'
        '\t// DTLS_TIMEOUT — ретранслятор не ответил на DTLS; это не WRAP-проблема.\n'
        '\t// В worker_group.go тип попадает в default: пауза и повтор без смены обфускации.\n'
        '\tSessionErrorDtlsTimeout SessionErrorType = "DTLS_TIMEOUT"',
        1,
    )
    if 'SessionErrorDtlsTimeout SessionErrorType = "DTLS_TIMEOUT"' not in sess:
        raise RuntimeError("DTLS timeout type marker not found in core/session.go")
    write("core/session.go", sess)

sess = read("core/session.go")
if "Type:    SessionErrorDtlsTimeout" not in sess:
    old_dtls = (
        '\t\t\treturn false, &SessionError{\n'
        '\t\t\t\tType:    SessionErrorWrapTimeout,\n'
        '\t\t\t\tAddress: turnAddr,\n'
        '\t\t\t\tErr:     fmt.Errorf("DTLS timeout'
    )
    new_dtls = (
        '\t\t\treturn false, &SessionError{\n'
        '\t\t\t\tType:    SessionErrorDtlsTimeout,\n'
        '\t\t\t\tAddress: turnAddr,\n'
        '\t\t\t\tErr:     fmt.Errorf("DTLS timeout'
    )
    if old_dtls not in sess:
        raise RuntimeError("DTLS timeout classification marker not found in core/session.go")
    sess = sess.replace(old_dtls, new_dtls, 1)
    write("core/session.go", sess)
print("DTLS timeout classified separately")

# 11. Use every TURN relay and publish TURN IPs from every group.
wg = read("core/worker_group.go")

old_fetch = '''\tvar credGen uint64

\tfetchCreds := func() error {
\t\tu, p, urls, err := GetCreds(ctx, hash, credStreamID)
\t\tif err != nil {
\t\t\treturn err
\t\t}
\t\tcredsMu.Lock()
\t\tcurUser, curPass, curURLs = u, p, urls
\t\tcredsMu.Unlock()
\t\treturn nil
\t}
'''
new_fetch = '''\tvar credGen uint64

\t// publishTurnIPs reports every relay used by this group to the core collector.
\t// The collector merges groups and refreshes WireGuard exclude routes, so a
\t// credential refresh does not leave a new relay outside the tunnel split.
\tpublishTurnIPs := func(urls []string) {
\t\tif turnIPsCh == nil || len(urls) == 0 {
\t\t\treturn
\t\t}
\t\tvar turnIPs []string
\t\tfor _, url := range urls {
\t\t\thost, _, err := net.SplitHostPort(url)
\t\t\tif err != nil {
\t\t\t\thost = url
\t\t\t}
\t\t\tif tp.Host != "" {
\t\t\t\thost = tp.Host
\t\t\t}
\t\t\tresolved, err := net.LookupIP(host)
\t\t\tif err != nil {
\t\t\t\tturnIPs = append(turnIPs, host)
\t\t\t} else {
\t\t\t\tfor _, ip := range resolved {
\t\t\t\t\tturnIPs = append(turnIPs, ip.String())
\t\t\t\t}
\t\t\t}
\t\t}
\t\tseen := make(map[string]bool)
\t\tvar unique []string
\t\tfor _, ip := range turnIPs {
\t\t\tif ip != "" && !seen[ip] {
\t\t\t\tseen[ip] = true
\t\t\t\tunique = append(unique, ip)
\t\t\t}
\t\t}
\t\tif len(unique) == 0 {
\t\t\treturn
\t\t}
\t\tselect {
\t\tcase turnIPsCh <- turnIPUpdate{GroupID: groupID, IPs: unique}:
\t\tdefault:
\t\t}
\t}

\tfetchCreds := func() error {
\t\tu, p, urls, err := GetCreds(ctx, hash, credStreamID)
\t\tif err != nil {
\t\t\treturn err
\t\t}
\t\tcredsMu.Lock()
\t\tcurUser, curPass, curURLs = u, p, urls
\t\tcredsMu.Unlock()
\t\treturn nil
\t}
'''
if old_fetch not in wg:
    raise RuntimeError("fetchCreds marker not found in core/worker_group.go")
wg = wg.replace(old_fetch, new_fetch, 1)

old_worker_sig = '\tturnIPsCh chan<- []string,'
new_worker_sig = '\tturnIPsCh chan<- turnIPUpdate,'
if old_worker_sig not in wg:
    raise RuntimeError("WorkerGroup turnIPsCh signature marker not found")
wg = wg.replace(old_worker_sig, new_worker_sig, 1)

turn_update_type = '''type turnIPUpdate struct {
\tGroupID int
\tIPs     []string
}

'''
if "type turnIPUpdate struct" not in wg:
    wg = wg.replace("func WorkerGroup(", turn_update_type + "func WorkerGroup(", 1)

old_initial = '''\tfor attempt := 1; ; attempt++ {
\t\tif err := fetchCreds(); err == nil {
\t\t\tbreak
\t\t} else {
'''
new_initial = '''\tfor attempt := 1; ; attempt++ {
\t\tif err := fetchCreds(); err == nil {
\t\t\tcredsMu.RLock()
\t\t\tinitialURLs := cloneStringSlice(curURLs)
\t\t\tcredsMu.RUnlock()
\t\t\tpublishTurnIPs(initialURLs)
\t\t\tbreak
\t\t} else {
'''
if old_initial not in wg:
    raise RuntimeError("initial fetchCreds marker not found in core/worker_group.go")
wg = wg.replace(old_initial, new_initial, 1)

# The old block only published group 1 and only once; publishTurnIPs now does
# this for every group on every credential refresh.
wg, n = re.subn(
    r'\tif groupID == 1 && turnIPsCh != nil \{.*?\n\t\}\n\n(?=\tvar configRequestInFlight)',
    '\t// TURN IPs were published by every group above; main.go merges them.\n\n',
    wg,
    count=1,
    flags=re.S,
)
if n != 1:
    raise RuntimeError("group-1 TURN IP block marker not found in core/worker_group.go")
wg = wg.replace('\t// Отправляем TURN IP для exclude routes (только первая группа)\n', '', 1)

old_select = '\t\t\t\t// Берём первый доступный адрес\n\t\t\t\tturnAddr := available[0]'
new_select = ('\t\t\t\t// Распределяем воркеров по всем доступным релеям. wid стабилен,\n'
              '\t\t\t\t// поэтому соседние воркеры не сбиваются в очередь на первый адрес.\n'
              '\t\t\t\tturnAddr := available[(wid-1)%len(available)]')
if old_select not in wg:
    raise RuntimeError("turnAddr selection marker not found in core/worker_group.go")
wg = wg.replace(old_select, new_select, 1)

old_auth = '''\t\t\t\t\tcase SessionErrorAuth:
\t\t\t\t\t\t// Креды протухли (401) — обновляем и продолжаем.
\t\t\t\t\t\t// Обновляет только один воркер: остальные увидят новый credGen
\t\t\t\t\t\tlog.Printf("[ВОРКЕР #%d] Ошибка авторизации TURN, обновляю креды", wid)
\t\t\t\t\t\tcredsMu.Lock()
\t\t\t\t\t\tif credGen == gen {
\t\t\t\t\t\t\tif err := fetchCreds(); err == nil {
\t\t\t\t\t\t\t\tcredGen++
\t\t\t\t\t\t\t\tlog.Printf("[ВОРКЕР #%d] Креды обновлены", wid)
\t\t\t\t\t\t\t} else {
\t\t\t\t\t\t\t\tlog.Printf("[ВОРКЕР #%d] Не удалось обновить креды: %v", wid, err)
\t\t\t\t\t\t\t}
\t\t\t\t\t\t}
\t\t\t\t\t\tcredsMu.Unlock()
\t\t\t\t\t\tselect {
'''
new_auth = '''\t\t\t\t\tcase SessionErrorAuth:
\t\t\t\t\t\t// Креды протухли (401) — обновляем и продолжаем.
\t\t\t\t\t\t// Обновляет только один воркер: остальные увидят новый credGen.
\t\t\t\t\t\tlog.Printf("[ВОРКЕР #%d] Ошибка авторизации TURN, обновляю креды", wid)
\t\t\t\t\t\tcredsMu.Lock()
\t\t\t\t\t\tneedRefresh := credGen == gen
\t\t\t\t\t\tif needRefresh {
\t\t\t\t\t\t\t// Заявляем поколение до сетевого запроса, иначе несколько
\t\t\t\t\t\t\t// воркеров одновременно пойдут за новыми кредами.
\t\t\t\t\t\t\tcredGen++
\t\t\t\t\t\t}
\t\t\t\t\t\tcredsMu.Unlock()
\t\t\t\t\t\tif needRefresh {
\t\t\t\t\t\t\tif err := fetchCreds(); err == nil {
\t\t\t\t\t\t\t\tcredsMu.RLock()
\t\t\t\t\t\t\t\trefreshedURLs := cloneStringSlice(curURLs)
\t\t\t\t\t\t\t\tcredsMu.RUnlock()
\t\t\t\t\t\t\t\tpublishTurnIPs(refreshedURLs)
\t\t\t\t\t\t\t\tlog.Printf("[ВОРКЕР #%d] Креды обновлены", wid)
\t\t\t\t\t\t\t} else {
\t\t\t\t\t\t\t\tlog.Printf("[ВОРКЕР #%d] Не удалось обновить креды: %v", wid, err)
\t\t\t\t\t\t\t}
\t\t\t\t\t\t}
\t\t\t\t\t\tselect {
'''
if old_auth not in wg:
    raise RuntimeError("SessionErrorAuth marker not found in core/worker_group.go")
wg = wg.replace(old_auth, new_auth, 1)

write("core/worker_group.go", wg)
print("TURN relay distribution and refresh applied")

# 12. Merge TURN addresses from every group and publish updates.
main_go = read("core/main.go")
old_turn_block = '''\tconfigCh := make(chan string, 1)
\tturnIPsCh := make(chan []string, 1)
\tgo func() {
\t\tselect {
\t\tcase rawConf, ok := <-configCh:
\t\t\tif !ok || rawConf == "" {
\t\t\t\treturn
\t\t\t}
\t\t\tfinalConf := patchMTU(rawConf)
\t\t\tvar turnIPs []string
\t\t\tselect {
\t\t\tcase ips := <-turnIPsCh:
\t\t\t\tturnIPs = ips
\t\t\tdefault:
\t\t\t}
\t\t\tc.emit(Event{Type: EventEvent, Name: "wg_config", Data: finalConf, TurnIPs: turnIPs})
\t\tcase <-ctx.Done():
\t\t}
\t}()
'''
new_turn_block = '''\tconfigCh := make(chan string, 1)
\tturnIPsCh := make(chan turnIPUpdate, 64)
\tvar turnIPsMu sync.Mutex
\tvar turnIPsList []string
\tturnIPsByGroup := make(map[int][]string)
\tturnIPsSnapshot := func() []string {
\t\tturnIPsMu.Lock()
\t\tdefer turnIPsMu.Unlock()
\t\treturn append([]string(nil), turnIPsList...)
\t}
\tgo func() {
\t\tfor {
\t\t\tselect {
\t\t\tcase upd := <-turnIPsCh:
\t\t\t\tturnIPsMu.Lock()
\t\t\t\tturnIPsByGroup[upd.GroupID] = append([]string(nil), upd.IPs...)
\t\t\t\tseen := make(map[string]struct{})
\t\t\t\tnext := make([]string, 0, len(turnIPsList))
\t\t\t\tfor _, ips := range turnIPsByGroup {
\t\t\t\t\tfor _, ip := range ips {
\t\t\t\t\t\tif ip == "" {
\t\t\t\t\t\t\tcontinue
\t\t\t\t\t\t}
\t\t\t\t\t\tif _, ok := seen[ip]; ok {
\t\t\t\t\t\t\tcontinue
\t\t\t\t\t\t}
\t\t\t\t\t\tseen[ip] = struct{}{}
\t\t\t\t\t\tnext = append(next, ip)
\t\t\t\t\t}
\t\t\t\t}
\t\t\t\tchanged := len(next) != len(turnIPsList)
\t\t\t\tif !changed {
\t\t\t\t\toldSet := make(map[string]struct{}, len(turnIPsList))
\t\t\t\t\tfor _, ip := range turnIPsList {
\t\t\t\t\t\toldSet[ip] = struct{}{}
\t\t\t\t\t}
\t\t\t\t\tfor _, ip := range next {
\t\t\t\t\t\tif _, ok := oldSet[ip]; !ok {
\t\t\t\t\t\t\tchanged = true
\t\t\t\t\t\t\tbreak
\t\t\t\t\t\t}
\t\t\t\t\t}
\t\t\t\t}
\t\t\t\tif changed {
\t\t\t\t\tturnIPsList = next
\t\t\t\t}
\t\t\t\tsnapshot := append([]string(nil), turnIPsList...)
\t\t\t\tturnIPsMu.Unlock()
\t\t\t\tif changed {
\t\t\t\t\tc.emit(Event{Type: EventEvent, Name: "turn_ips", TurnIPs: snapshot})
\t\t\t\t}
\t\t\tcase <-ctx.Done():
\t\t\t\treturn
\t\t\t}
\t\t}
\t}()
\tgo func() {
\t\tselect {
\t\tcase rawConf, ok := <-configCh:
\t\t\tif !ok || rawConf == "" {
\t\t\t\treturn
\t\t\t}
\t\t\tfinalConf := patchMTU(rawConf)
\t\t\tc.emit(Event{Type: EventEvent, Name: "wg_config", Data: finalConf, TurnIPs: turnIPsSnapshot()})
\t\tcase <-ctx.Done():
\t\t}
\t}()
'''
if old_turn_block not in main_go:
    raise RuntimeError("turnIPs channel marker not found in core/main.go")
main_go = main_go.replace(old_turn_block, new_turn_block, 1)
write("core/main.go", main_go)
print("All-group TURN address collector applied")

# 13. Bridge readiness and live TURN-route updates.
bridge = read("backend/bridge.go")
old_sig = "func (b *Bridge) forwardEvents(events <-chan core.Event, sessID uint64) {\n"
new_sig = old_sig + '''\twgApplied := false
\tcoreReady := false
\tconnectedSent := false
\tmarkConnected := func() {
\t\tif connectedSent || !wgApplied || !coreReady {
\t\t\treturn
\t\t}
\t\tconnectedSent = true
\t\tb.onEvent("state_changed", "connected")
\t}
\twgLogf := func(msg string) {
\t\tb.onEvent("log", "INFO", "[WG] "+msg)
\t\tb.mu.Lock()
\t\tif b.logFile != nil {
\t\t\tb.logFile.Write("INFO", "[WG] "+msg)
\t\t}
\t\tb.mu.Unlock()
\t}
'''
if old_sig not in bridge:
    raise RuntimeError("forwardEvents marker not found in backend/bridge.go")
bridge = bridge.replace(old_sig, new_sig, 1)

new_switch = '''\t\t\tswitch ev.Name {
\t\t\tcase "wg_config":
\t\t\t\tb.onEvent("log", "INFO", "[WG] Применение конфига...")
\t\t\t\tif err := wg.Apply(ev.Data, ev.TurnIPs, wgLogf); err != nil {
\t\t\t\t\tb.onEvent("error", fmt.Sprintf("[WG] Ошибка: %v", err))
\t\t\t\t} else {
\t\t\t\t\twgApplied = true
\t\t\t\t\tb.onEvent("log", "INFO", "[WG] Конфиг применён, ожидаем подтверждение WireGuard")
\t\t\t\t\tmarkConnected()
\t\t\t\t}
\t\t\tcase "turn_ips":
\t\t\t\twg.UpdateTurnRoutes(ev.TurnIPs, wgLogf)
\t\t\tcase "captcha_required":
\t\t\t\tb.onEvent("captcha_required", ev.Data)
\t\t\tcase "ready":
\t\t\t\tb.onEvent("log", "INFO", "[ЯДРО] Туннель готов к работе")
\t\t\t\tcoreReady = true
\t\t\t\tmarkConnected()
\t\t\tdefault:
\t\t\t\tb.onEvent("event", ev.Name)
\t\t\t}'''
bridge, n = re.subn(
    r'\t\t\tswitch ev\.Name \{.*?\n\t\t\tdefault:\n\t\t\t\tb\.onEvent\("event", ev\.Name\)\n\t\t\t\}',
    new_switch,
    bridge,
    count=1,
    flags=re.S,
)
if n != 1:
    raise RuntimeError("event switch marker not found in backend/bridge.go")
write("backend/bridge.go", bridge)
print("Readiness gated on WG apply and core ready")

# 14. The frontend must not treat wg_config as readiness.
app = read("frontend/src/App.tsx")
old_event = '''      EventsOn('event', (name: unknown) => {
        if (name === 'wg_config') tunnelStore.set('connected');
      }),
'''
new_event = '''      // Readiness arrives as state_changed only after Bridge has applied
      // WireGuard and the core has emitted ready. wg_config alone is not ready.
'''
if old_event not in app:
    raise RuntimeError("frontend wg_config marker not found in App.tsx")
app = app.replace(old_event, new_event, 1)
write("frontend/src/App.tsx", app)
print("Frontend readiness source fixed")

# 15. Refresh only TURN exclude routes when the relay list changes.
wg_go = read("backend/wg.go")
old_field = '''\tactiveDevice        *device.Device
\tactiveTun           tun.Device
\tactiveExcludeRoutes []string
'''
new_field = '''\tactiveDevice        *device.Device
\tactiveTun           tun.Device
\tactiveExcludeRoutes []string
\tactiveTurnRoutes    []string // TURN /32 routes that can change after a credential refresh
'''
if old_field not in wg_go:
    raise RuntimeError("activeExcludeRoutes field marker not found in backend/wg.go")
wg_go = wg_go.replace(old_field, new_field, 1)

old_apply = '''\t// Exclude routes — VK IPs, DNS, etc go via physical gateway (bypass tunnel)
\tvar excludes []string
\tif gw != "" {
\t\tfor _, ip := range turnIPs {
\t\t\texcludes = append(excludes, ip+"/32")
\t\t}
\t\texcludes = append(excludes, vkExcludeCIDRs...)
\t\tfor _, cidr := range excludes {
\t\t\tip, mask, err := parseCIDR(cidr)
\t\t\tif err != nil {
\t\t\t\tcontinue
\t\t\t}
\t\t\t_ = runCmdWindows("route", "add", ip, "mask", mask, gw)
\t\t}
\t}
\tw.activeExcludeRoutes = excludes
'''
new_apply = '''\t// Exclude routes — VK IPs, DNS, etc go via physical gateway (bypass tunnel)
\tvar excludes []string
\tvar turnRoutes []string
\tif gw != "" {
\t\tfor _, ip := range turnIPs {
\t\t\tif ip == "" {
\t\t\t\tcontinue
\t\t\t}
\t\t\tcidr := ip + "/32"
\t\t\tturnRoutes = append(turnRoutes, cidr)
\t\t\texcludes = append(excludes, cidr)
\t\t}
\t\texcludes = append(excludes, vkExcludeCIDRs...)
\t\tfor _, cidr := range excludes {
\t\t\tip, mask, err := parseCIDR(cidr)
\t\t\tif err != nil {
\t\t\t\tcontinue
\t\t\t}
\t\t\t_ = runCmdWindows("route", "add", ip, "mask", mask, gw)
\t\t}
\t}
\tw.activeExcludeRoutes = excludes
\tw.activeTurnRoutes = turnRoutes
'''
if old_apply not in wg_go:
    raise RuntimeError("Windows exclude-route marker not found in backend/wg.go")
wg_go = wg_go.replace(old_apply, new_apply, 1)

old_clear = '''\tfor _, cidr := range w.activeExcludeRoutes {
\t\tip, _, _ := parseCIDR(cidr)
\t\tif ip != "" {
\t\t\t_ = runCmdWindows("route", "delete", ip)
\t\t}
\t}
\tw.activeExcludeRoutes = nil
'''
new_clear = '''\tfor _, cidr := range w.activeExcludeRoutes {
\t\tip, _, _ := parseCIDR(cidr)
\t\tif ip != "" {
\t\t\t_ = runCmdWindows("route", "delete", ip)
\t\t}
\t}
\tw.activeExcludeRoutes = nil
\tw.activeTurnRoutes = nil
'''
if old_clear not in wg_go:
    raise RuntimeError("Windows exclude-route teardown marker not found in backend/wg.go")
wg_go = wg_go.replace(old_clear, new_clear, 1)

update_method = '''
// UpdateTurnRoutes refreshes only TURN /32 exclude routes after a credentials
// refresh. It never reapplies WireGuard and never touches unrelated routes.
func (w *WG) UpdateTurnRoutes(turnIPs []string, logf wgLogFunc) {
\tif runtime.GOOS != "windows" {
\t\treturn
\t}
\tif logf == nil {
\t\tlogf = func(msg string) { log.Printf("[WG] %s", msg) }
\t}
\tw.stateMu.Lock()
\tdefer w.stateMu.Unlock()
\tif w.activeDevice == nil || w.physGW == "" {
\t\treturn
\t}
\twanted := make(map[string]bool, len(turnIPs))
\tfor _, ip := range turnIPs {
\t\tif ip != "" {
\t\t\twanted[ip+"/32"] = true
\t\t}
\t}
\tif len(wanted) == 0 {
\t\treturn
\t}
\told := make(map[string]bool, len(w.activeTurnRoutes))
\tfor _, cidr := range w.activeTurnRoutes {
\t\told[cidr] = true
\t}
\tfor cidr := range old {
\t\tif wanted[cidr] {
\t\t\tcontinue
\t\t}
\t\tip, _, err := parseCIDR(cidr)
\t\tif err == nil && ip != "" {
\t\t\t_ = runCmdWindows("route", "delete", ip)
\t\t}
\t}
\tnextTurn := make([]string, 0, len(wanted))
\tadded := 0
\tfor cidr := range wanted {
\t\tif old[cidr] {
\t\t\tnextTurn = append(nextTurn, cidr)
\t\t\tcontinue
\t\t}
\t\tip, mask, err := parseCIDR(cidr)
\t\tif err != nil {
\t\t\tcontinue
\t\t}
\t\tif err := runCmdWindows("route", "add", ip, "mask", mask, w.physGW); err != nil {
\t\t\tlogf(fmt.Sprintf("TURN-маршрут %s не добавлен: %v", cidr, err))
\t\t\tcontinue
\t\t}
\t\tnextTurn = append(nextTurn, cidr)
\t\tadded++
\t}
\tbase := make([]string, 0, len(w.activeExcludeRoutes)+len(nextTurn))
\tfor _, cidr := range w.activeExcludeRoutes {
\t\tif !old[cidr] {
\t\t\tbase = append(base, cidr)
\t\t}
\t}
\tbase = append(base, nextTurn...)
\tw.activeExcludeRoutes = base
\tw.activeTurnRoutes = nextTurn
\tif added > 0 {
\t\tlogf(fmt.Sprintf("TURN-маршруты обновлены: +%d, всего %d", added, len(nextTurn)))
\t}
}
'''
anchor = "\n// CleanupStaleExcludeRoutes"
if anchor not in wg_go:
    raise RuntimeError("CleanupStaleExcludeRoutes anchor not found in backend/wg.go")
wg_go = wg_go.replace(anchor, update_method + anchor, 1)
write("backend/wg.go", wg_go)
print("Live TURN exclude-route refresh applied")
