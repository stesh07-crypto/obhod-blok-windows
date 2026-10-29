#!/usr/bin/env python3
"""Apply after existing OBhoD overlays; fail if the pinned core has changed."""
from pathlib import Path
import shutil,sys
root=Path(sys.argv[1]);overlay=Path(sys.argv[2]);p=root/'backend/wg.go';s=p.read_text()
def replace(old,new):
 global s
 if s.count(old)!=1:raise RuntimeError('Expected one marker: '+old[:100])
 s=s.replace(old,new,1)
replace('''\tactiveTurnRoutes    []string // TURN /32 routes that can change after a credential refresh''','''\tactiveTurnRoutes    []string // TURN /32 routes that can change after a credential refresh
\ttunnelDNSConfigured bool''')
# The only Windows occurrence of this line (Linux excludes are built differently).
replace('''\t\texcludes = append(excludes, vkExcludeCIDRs...)''','''\t\texcludes = append(excludes, windowsExcludeCIDRs(vkExcludeCIDRs)...)''')
replace('''func (w *WG) applyWindows(conf string, turnIPs []string, logf wgLogFunc) error {''','''func (w *WG) applyWindows(conf string, turnIPs []string, logf wgLogFunc) (applyErr error) {''')
replace('''\tw.teardownWindowsLocked()

\tif err := extractWintun();''','''\tw.teardownWindowsLocked()
\tdefer func() { if applyErr != nil { w.teardownWindowsLocked() } }()

\tif err := extractWintun();''')
replace('''\t// Create wintun TUN interface''','''\tdnsServers, err := windowsTunnelDNS(conf, allowedIPs)
\tif err != nil { return fmt.Errorf("DNS конфигурация: %w", err) }

\t// Create wintun TUN interface''')
replace('''\t// Set low metric on WG interface so it wins over physical default route
\t_ = runCmdWindows("netsh", "interface", "ip", "set", "interface",
\t\t"interface="+wgIface, "metric=1")''','''\t// Apply the same MTU to Windows' IP layer, not only the Go TUN object.
\tif err := runCmdWindows("netsh", "interface", "ipv4", "set", "subinterface",
\t\twgIface, fmt.Sprintf("mtu=%d", mtu), "store=active"); err != nil { return fmt.Errorf("set tunnel MTU: %w", err) }
\tif err := runCmdWindows("netsh", "interface", "ip", "set", "interface",
\t\t"interface="+wgIface, "metric=1"); err != nil { return fmt.Errorf("set tunnel metric: %w", err) }''')
replace('''\t\tif err := runCmdWindows("netsh", "interface", "ip", "add", "route", cidr, wgIface); err != nil {
\t\t\tlogf(fmt.Sprintf("netsh add route %s failed: %v", cidr, err))
\t\t}
\t\ttunnelRoutes = append(tunnelRoutes, cidr)''','''\t\tif err := runCmdWindows("netsh", "interface", "ip", "add", "route", cidr, wgIface); err != nil {
\t\t\tw.activeRoutes = tunnelRoutes
\t\t\treturn fmt.Errorf("netsh add route %s: %w", cidr, err)
\t\t}
\t\ttunnelRoutes = append(tunnelRoutes, cidr)''')
replace('''\tw.activeRoutes = tunnelRoutes

\tlogf(fmt.Sprintf("Туннель %s поднят, AllowedIPs: %v", wgIface, tunnelRoutes))''','''\tw.activeRoutes = tunnelRoutes
\tdnsRoutes, err := configureWindowsTunnelDNS(wgIface, dnsServers, w.activeRoutes, runCmdWindows)
\tif err != nil { return err }
\tw.activeRoutes = append(w.activeRoutes, dnsRoutes...)
\tw.tunnelDNSConfigured = true
\tif err := runCmdWindows("ipconfig", "/flushdns"); err != nil { logf(fmt.Sprintf("[DNS] Не удалось очистить кэш: %v", err)) }
\tlogf(fmt.Sprintf("[DNS] Серверы=%v; маршрут=WireGuard; обычный DNS внутри зашифрованного туннеля", dnsServers))

\tlogf(fmt.Sprintf("Туннель %s поднят, AllowedIPs: %v", wgIface, tunnelRoutes))''')
replace('''\t// Restore physical gateway metric (must happen BEFORE closing WG device)''','''\t// Only our virtual adapter is changed; physical adapter DNS is untouched.
\tif w.tunnelDNSConfigured {
\t\tif err := runCmdWindows("netsh", "interface", "ipv4", "set", "dnsservers", "name="+wgIface, "source=dhcp"); err != nil { log.Printf("[DNS] Сброс DNS туннеля: %v", err) }
\t\tw.tunnelDNSConfigured = false
\t\t_ = runCmdWindows("ipconfig", "/flushdns")
\t}

\t// Restore physical gateway metric (must happen BEFORE closing WG device)''')
p.write_text(s)
for name in ('tunnel_dns.go','tunnel_dns_test.go'):shutil.copy2(overlay/'backend'/name,root/'backend'/name)
print('Windows tunnel DNS routing applied')
