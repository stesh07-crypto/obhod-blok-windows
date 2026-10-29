package backend

import (
	"bufio"
	"fmt"
	"net/netip"
	"strconv"
	"strings"
)

// Transport bootstrap uses these resolvers outside the tunnel. Routing them
// into WG would make VK credential refresh depend on the tunnel it repairs.
func bootstrapDNS(ip netip.Addr) bool {
	return ip.String() == "77.88.8.8" || ip.String() == "77.88.8.1"
}

func windowsTunnelDNS(conf string, allowed []string) ([]string, error) {
	var candidates []string
	scanner := bufio.NewScanner(strings.NewReader(conf))
	inInterface := false
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if strings.HasPrefix(line, "[") {
			inInterface = strings.EqualFold(line, "[Interface]")
			continue
		}
		if !inInterface {
			continue
		}
		parts := strings.SplitN(line, "=", 2)
		if len(parts) == 2 && strings.EqualFold(strings.TrimSpace(parts[0]), "DNS") {
			for _, v := range strings.Split(parts[1], ",") {
				candidates = append(candidates, strings.TrimSpace(v))
			}
		}
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	if len(candidates) == 0 {
		candidates = []string{"1.1.1.1", "8.8.8.8"}
	}
	var prefixes []netip.Prefix
	for _, s := range allowed {
		if p, e := netip.ParsePrefix(s); e == nil {
			prefixes = append(prefixes, p)
		}
	}
	var result []string
	seen := map[string]bool{}
	for _, s := range candidates {
		ip, e := netip.ParseAddr(s)
		// wg-quick also permits search suffixes; these are not resolver addresses.
		if e != nil {
			continue
		}
		if !ip.Is4() || ip.IsLoopback() || ip.IsUnspecified() || ip.IsMulticast() || ip.IsLinkLocalUnicast() || bootstrapDNS(ip) {
			continue
		}
		covered := false
		for _, p := range prefixes {
			if p.Contains(ip) {
				covered = true
				break
			}
		}
		if covered && !seen[ip.String()] {
			result = append(result, ip.String())
			seen[ip.String()] = true
		}
	}
	if len(result) == 0 {
		return nil, fmt.Errorf("нет IPv4 DNS, доступного через AllowedIPs (DNS для запуска VK не используется как DNS туннеля)")
	}
	return result, nil
}

func windowsExcludeCIDRs(base []string) []string {
	result := make([]string, 0, len(base))
	for _, cidr := range base {
		if cidr == "1.1.1.0/24" || cidr == "8.8.8.0/24" {
			continue
		}
		result = append(result, cidr)
	}
	return result
}

type dnsCommand func(string, ...string) error

// Install explicit /32 routes before assigning DNS: route specificity must win
// over existing broad bypass routes, independent of interface metric. Only
// routes successfully created by this invocation are returned for teardown.
func configureWindowsTunnelDNS(iface string, servers []string, existingRoutes []string, run dnsCommand) ([]string, error) {
	var routes []string
	existing := make(map[string]bool, len(existingRoutes))
	for _, route := range existingRoutes {
		existing[route] = true
	}
	rollback := func() {
		for _, cidr := range routes {
			_ = run("netsh", "interface", "ipv4", "delete", "route", cidr, iface)
		}
	}
	for _, ip := range servers {
		cidr := ip + "/32"
		if existing[cidr] {
			continue
		}
		if err := run("netsh", "interface", "ipv4", "add", "route", cidr, iface, "metric=1", "store=active"); err != nil {
			rollback()
			return nil, fmt.Errorf("DNS route %s: %w", cidr, err)
		}
		routes = append(routes, cidr)
	}
	if len(servers) == 0 {
		return nil, fmt.Errorf("empty DNS list")
	}
	if err := run("netsh", "interface", "ipv4", "set", "dnsservers", "name="+iface, "source=static", "address="+servers[0], "register=none", "validate=no"); err != nil {
		_ = run("netsh", "interface", "ipv4", "set", "dnsservers", "name="+iface, "source=dhcp")
		rollback()
		return nil, fmt.Errorf("set tunnel DNS: %w", err)
	}
	for i, ip := range servers[1:] {
		if err := run("netsh", "interface", "ipv4", "add", "dnsservers", "name="+iface, "address="+ip, "index="+strconv.Itoa(i+2), "validate=no"); err != nil {
			_ = run("netsh", "interface", "ipv4", "set", "dnsservers", "name="+iface, "source=dhcp")
			rollback()
			return nil, fmt.Errorf("add tunnel DNS: %w", err)
		}
	}
	return routes, nil
}
