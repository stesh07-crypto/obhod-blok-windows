package backend

import (
	"fmt"
	"reflect"
	"strings"
	"testing"
)

func TestWindowsTunnelDNSConfigAndCoverage(t *testing.T) {
	for _, tc := range []struct {
		name, conf    string
		allowed, want []string
		bad           bool
	}{
		{"default", "[Interface]\nAddress = 10.66.0.2/32", []string{"0.0.0.0/0"}, []string{"1.1.1.1", "8.8.8.8"}, false},
		{"configured", "[Interface]\nDNS = 9.9.9.9, example.test, 9.9.9.9\n[Peer]\nDNS = 8.8.8.8", []string{"0.0.0.0/0"}, []string{"9.9.9.9"}, false},
		{"private", "[Interface]\nDNS = 10.66.0.1", []string{"10.66.0.0/24"}, []string{"10.66.0.1"}, false},
		{"not routed", "[Interface]\nDNS = 1.1.1.1", []string{"10.66.0.0/24"}, nil, true},
		{"bootstrap loop", "[Interface]\nDNS = 77.88.8.8,77.88.8.1", []string{"0.0.0.0/0"}, nil, true},
		{"localhost", "[Interface]\nDNS = 127.0.0.1", []string{"0.0.0.0/0"}, nil, true},
		{"ipv6 unsupported", "[Interface]\nDNS = 2606:4700:4700::1111", []string{"::/0"}, nil, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got, err := windowsTunnelDNS(tc.conf, tc.allowed)
			if (err != nil) != tc.bad || !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("got=%v err=%v", got, err)
			}
		})
	}
}
func TestWindowsDNSNotInPublicBypass(t *testing.T) {
	base := []string{"87.240.128.0/18", "1.1.1.0/24", "77.88.0.0/18", "8.8.8.0/24"}
	want := []string{"87.240.128.0/18", "77.88.0.0/18"}
	if got := windowsExcludeCIDRs(base); !reflect.DeepEqual(got, want) {
		t.Fatalf("bypass=%v", got)
	}
	if len(base) != 4 {
		t.Fatal("modified shared cross-platform list")
	}
}
func TestWindowsDNSRoutesPrecedeAssignment(t *testing.T) {
	var calls []string
	routes, err := configureWindowsTunnelDNS("pwdtt-wg", []string{"1.1.1.1", "8.8.8.8"}, nil, func(n string, args ...string) error { calls = append(calls, n+" "+strings.Join(args, " ")); return nil })
	if err != nil || len(routes) != 2 || len(calls) != 4 {
		t.Fatalf("routes=%v calls=%v err=%v", routes, calls, err)
	}
	for i := 0; i < 2; i++ {
		if !strings.Contains(calls[i], "add route "+routes[i]+" pwdtt-wg metric=1 store=active") {
			t.Fatal(calls)
		}
	}
	if !strings.Contains(calls[2], "source=static address=1.1.1.1") || !strings.Contains(calls[3], "address=8.8.8.8 index=2") {
		t.Fatal(calls)
	}
}
func TestWindowsDNSFailureRollsBackOwnedChanges(t *testing.T) {
	for failAt := 1; failAt <= 4; failAt++ {
		t.Run(fmt.Sprint(failAt), func(t *testing.T) {
			var calls []string
			routes, err := configureWindowsTunnelDNS("pwdtt-wg", []string{"1.1.1.1", "8.8.8.8"}, nil, func(n string, args ...string) error {
				calls = append(calls, n+" "+strings.Join(args, " "))
				if len(calls) == failAt {
					return fmt.Errorf("injected")
				}
				return nil
			})
			if err == nil || routes != nil {
				t.Fatalf("routes=%v err=%v", routes, err)
			}
			joined := strings.Join(calls[failAt:], "\n")
			if failAt > 1 && !strings.Contains(joined, "delete route 1.1.1.1/32 pwdtt-wg") {
				t.Fatal("missing rollback", calls)
			}
			if failAt > 2 && !strings.Contains(joined, "source=dhcp") {
				t.Fatal("DNS not reset", calls)
			}
			for _, c := range calls {
				if strings.Contains(c, "Ethernet") || strings.Contains(c, "Wi-Fi") || strings.Contains(c, "store=persistent") {
					t.Fatal("modified physical adapter", c)
				}
			}
		})
	}
}

func TestWindowsDNSDoesNotRecreateAllowedHostRoute(t *testing.T) {
	var calls []string
	routes, err := configureWindowsTunnelDNS("pwdtt-wg", []string{"1.1.1.1"}, []string{"1.1.1.1/32"}, func(n string, args ...string) error { calls = append(calls, strings.Join(args, " ")); return nil })
	if err != nil || len(routes) != 0 || len(calls) != 1 || !strings.Contains(calls[0], "set dnsservers") {
		t.Fatalf("routes=%v calls=%v err=%v", routes, calls, err)
	}
}
