# Windows DNS candidate

Base OBhoD overlay: 8bea96e. Core remains pinned to PWDTT v1.6.0.

Confirmed in the assembled source: DNS fields were dropped from wg-quick config
without configuring DNS on the Windows adapter; 1.1.1.0/24 and 8.8.8.0/24 were
explicitly routed via the physical gateway. Browser DoH succeeding is consistent
with DNS-path failure but does not prove the earlier claims about MTU or DPI.

Changes:
- Parse IPv4 DNS in the Interface section and require coverage by AllowedIPs.
  If absent, use 1.1.1.1 and 8.8.8.8 when covered. Search suffixes/unsupported IPs
  are not sent to shell commands. Fail if no usable resolver exists.
- Keep VK bootstrap resolvers separate (77.88.8.8 / 77.88.8.1 remain direct).
- Remove only the two public DNS bypass prefixes on Windows, leaving the shared
  cross-platform list untouched. Add explicit DNS /32 routes inside WireGuard.
- Set DNS on pwdtt-wg only; no global registry, NRPT or physical-adapter edits.
- Roll back newly created routes on DNS setup error. Reset virtual-adapter DNS
  and flush cache on normal disconnect. Errors installing DNS, MTU or tunnel
  routes fail startup rather than reporting a ready tunnel.
- Apply the configured/default TUN MTU to the Windows IPv4 interface using active
  settings (no persistent changes to physical MTU).

Limits: this is encrypted DNS transport INSIDE the existing VPN, not a local DoH
proxy. It does not block all alternative DNS paths: applications with their own
resolver, IPv6, Windows multi-interface fallback and preexisting policy require
separate examination. It does not claim universal censorship bypass or fix a
broken TURN/WG transport. UDP/TCP DNS after the VPS can still be affected by its
network; if that occurs, a separately tested DoH proxy is the next layer.

Validation: hermetic Go tests with -race exercise config/AllowedIPs, removal of
public bypass, command ordering, each failure rollback, and preexisting host
routes. Full Wails Windows build checks assembled source integration.
Real Windows 10 and provider-network validation remains required: with browser
DoH disabled, test system DNS and a non-browser app, then disconnect and verify
normal DNS works. Keep before/after route and DNS diagnostics; do not disable
firewalls or modify physical adapters to make the test pass.
