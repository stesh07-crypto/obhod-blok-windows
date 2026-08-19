#!/usr/bin/env python3
from __future__ import annotations

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


# Full settings UI: old PWDTT-style controls + current OBhoD advanced controls.
for rel in ["frontend/src/modals/Settings.tsx", "frontend/src/modals/Settings.css"]:
    src = OVERLAY / rel
    dst = ROOT / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

# Extend the persistent settings model. settingsStore already merges saved data with DEFAULT_SETTINGS,
# so existing users migrate automatically without losing prior preferences.
types = read("frontend/src/lib/types.ts")
old_iface = """export interface AppSettings {
  autoStart: boolean;
  obfsMode: 'audio' | 'video';
  obfsAccepted: boolean;
}
"""
new_iface = """export interface AppSettings {
  autoStart: boolean;
  trayEnabled: boolean;
  autoConnect: boolean;
  useGlobalHashes: boolean;
  globalHashes: [string, string, string, string];
  obfsMode: 'audio' | 'video';
  obfsAccepted: boolean;
}
"""
if old_iface in types:
    types = types.replace(old_iface, new_iface, 1)
elif "trayEnabled: boolean;" not in types:
    raise RuntimeError("AppSettings marker not found")

old_defaults = """export const DEFAULT_SETTINGS: AppSettings = {
  autoStart: true,
  obfsMode: 'audio',
  obfsAccepted: false,
};
"""
new_defaults = """export const DEFAULT_SETTINGS: AppSettings = {
  autoStart: true,
  trayEnabled: false,
  autoConnect: false,
  useGlobalHashes: false,
  globalHashes: ['', '', '', ''],
  obfsMode: 'audio',
  obfsAccepted: false,
};
"""
if old_defaults in types:
    types = types.replace(old_defaults, new_defaults, 1)
elif "globalHashes: ['', '', '', '']," not in types:
    raise RuntimeError("DEFAULT_SETTINGS marker not found")
write("frontend/src/lib/types.ts", types)

# Make global hashes and auto-connect actually affect tunnel startup.
connect = read("frontend/src/pages/Connect.tsx")
old_hashes = """    const hashes = (cur.hashes ?? []).filter(h => h.trim());
    if (hashes.length === 0) {
      toastStore.show('Добавьте хеши в профиле сервера');
"""
new_hashes = """    const appSettings = settingsStore.get();
    const profileHashes = (cur.hashes ?? []).filter(h => h.trim());
    const configuredGlobalHashes = (appSettings.globalHashes ?? []).filter(h => h.trim());
    const hashes = appSettings.useGlobalHashes && configuredGlobalHashes.length > 0
      ? configuredGlobalHashes
      : profileHashes;
    if (hashes.length === 0) {
      toastStore.show(appSettings.useGlobalHashes ? 'Добавьте глобальные VK-хэши в настройках' : 'Добавьте хеши в профиле сервера');
"""
if old_hashes in connect:
    connect = connect.replace(old_hashes, new_hashes, 1)
elif "const configuredGlobalHashes" not in connect:
    raise RuntimeError("Connect hash marker not found")

auto_marker = "  const reconnectAtRef = useRef(0);\n"
auto_block = """  const autoConnectTriedRef = useRef(false);
  useEffect(() => {
    if (autoConnectTriedRef.current || !selected) return;
    if (!settingsStore.get().autoConnect) return;
    autoConnectTriedRef.current = true;
    const timer = window.setTimeout(() => {
      if (tunnelStore.get() === 'idle') void doConnect();
    }, 700);
    return () => window.clearTimeout(timer);
    // Run once for the first selected profile. doConnect reads the current profile through selectedRef.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id]);

  const reconnectAtRef = useRef(0);
"""
if "const autoConnectTriedRef" not in connect:
    if auto_marker not in connect:
        raise RuntimeError("auto-connect insertion marker not found")
    connect = connect.replace(auto_marker, auto_block, 1)
write("frontend/src/pages/Connect.tsx", connect)

print("Full OBhoD Windows settings applied successfully")
