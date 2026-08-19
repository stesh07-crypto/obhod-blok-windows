package backend

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// SubscriptionImportResult is one personal Bronya profile returned to the UI.
type SubscriptionImportResult struct {
	Name            string   `json:"name"`
	Peer            string   `json:"peer"`
	Password        string   `json:"password"`
	Hashes          []string `json:"hashes"`
	Workers         int      `json:"workers"`
	ListenPort      int      `json:"listenPort"`
	Description     string   `json:"description"`
	SubscriptionURL string   `json:"subscriptionUrl"`
}

type subscriptionEnvelope struct {
	SubscriptionName string                `json:"subscriptionName"`
	GroupName        string                `json:"groupName"`
	Description      string                `json:"description"`
	Profiles         []subscriptionProfile `json:"profiles"`
	Servers          []subscriptionProfile `json:"servers"`
}

type subscriptionProfile struct {
	Name           string          `json:"name"`
	Peer           string          `json:"peer"`
	Password       string          `json:"password"`
	Pass           string          `json:"pass"`
	Hashes         json.RawMessage `json:"hashes"`
	VKHashes       json.RawMessage `json:"vkHashes"`
	Workers        int             `json:"workers"`
	WorkersPerHash int             `json:"workersPerHash"`
	Port           int             `json:"port"`
	ListenPort     int             `json:"listenPort"`
}

var subscriptionHTTPClient = &http.Client{Timeout: 20 * time.Second}

// FetchSubscription downloads and parses one OBhoD Bronya profile.
// The copied URL itself is the subscription; there is intentionally no server catalogue.
func FetchSubscription(rawURL string) (*SubscriptionImportResult, error) {
	rawURL = strings.TrimSpace(rawURL)
	u, err := url.Parse(rawURL)
	if err != nil || (u.Scheme != "https" && u.Scheme != "http") || u.Host == "" {
		return nil, fmt.Errorf("ссылка подписки должна начинаться с http:// или https://")
	}

	req, err := http.NewRequest(http.MethodGet, rawURL, nil)
	if err != nil {
		return nil, fmt.Errorf("не удалось создать запрос: %w", err)
	}
	req.Header.Set("Accept", "application/json, text/plain, */*")
	req.Header.Set("User-Agent", "OBhoD-Windows-Subscription/1.0")

	resp, err := subscriptionHTTPClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("не удалось загрузить подписку: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		return nil, fmt.Errorf("сервер подписки вернул HTTP %d", resp.StatusCode)
	}

	body, err := io.ReadAll(io.LimitReader(resp.Body, 2<<20))
	if err != nil {
		return nil, fmt.Errorf("не удалось прочитать подписку: %w", err)
	}

	fallbackName := strings.TrimSpace(u.Fragment)
	result, err := parseSubscriptionPayload(strings.TrimSpace(string(body)), rawURL, fallbackName)
	if err != nil {
		return nil, err
	}
	return result, nil
}

func parseSubscriptionPayload(text, sourceURL, fallbackName string) (*SubscriptionImportResult, error) {
	if text == "" {
		return nil, fmt.Errorf("пустая подписка")
	}

	// Mobile OBhoD accepts Base64 wrapped payloads; Windows mirrors that behaviour.
	if !strings.HasPrefix(text, "{") && !strings.HasPrefix(text, "[") && !strings.HasPrefix(text, "qwdtt:") {
		for _, enc := range []*base64.Encoding{base64.StdEncoding, base64.RawStdEncoding} {
			if decoded, err := enc.DecodeString(text); err == nil {
				candidate := strings.TrimSpace(string(decoded))
				if candidate != "" {
					if r, err := parseSubscriptionPayload(candidate, sourceURL, fallbackName); err == nil {
						return r, nil
					}
				}
			}
		}
	}

	if strings.HasPrefix(text, "qwdtt://config?") || strings.HasPrefix(text, "qwdtt:config?") {
		return parseQwdttConfig(text, sourceURL, fallbackName)
	}

	if strings.HasPrefix(text, "[") {
		var list []subscriptionProfile
		if err := json.Unmarshal([]byte(text), &list); err != nil || len(list) == 0 {
			return nil, fmt.Errorf("неверный формат подписки")
		}
		return resultFromProfile(list[0], "", fallbackName, sourceURL)
	}

	var env subscriptionEnvelope
	if err := json.Unmarshal([]byte(text), &env); err != nil {
		return nil, fmt.Errorf("неверный формат подписки: %w", err)
	}
	profiles := env.Profiles
	if len(profiles) == 0 {
		profiles = env.Servers
	}
	if len(profiles) == 0 {
		// Also accept a direct single profile object.
		var direct subscriptionProfile
		if err := json.Unmarshal([]byte(text), &direct); err == nil && strings.TrimSpace(direct.Peer) != "" {
			return resultFromProfile(direct, env.Description, fallbackName, sourceURL)
		}
		return nil, fmt.Errorf("в подписке нет профиля Брони")
	}

	nameFallback := strings.TrimSpace(env.SubscriptionName)
	if nameFallback == "" {
		nameFallback = strings.TrimSpace(env.GroupName)
	}
	if nameFallback == "" {
		nameFallback = fallbackName
	}
	return resultFromProfile(profiles[0], env.Description, nameFallback, sourceURL)
}

func resultFromProfile(p subscriptionProfile, description, fallbackName, sourceURL string) (*SubscriptionImportResult, error) {
	peer := strings.TrimSpace(p.Peer)
	if peer == "" {
		return nil, fmt.Errorf("в профиле Брони отсутствует peer")
	}
	password := p.Password
	if password == "" {
		password = p.Pass
	}
	if password == "" {
		return nil, fmt.Errorf("в профиле Брони отсутствует пароль")
	}

	hashes := parseSubscriptionHashes(p.Hashes)
	if len(hashes) == 0 {
		hashes = parseSubscriptionHashes(p.VKHashes)
	}
	if len(hashes) == 0 {
		return nil, fmt.Errorf("в профиле Брони отсутствуют VK-хэши")
	}
	if len(hashes) > 4 {
		hashes = hashes[:4]
	}

	workers := p.Workers
	if workers <= 0 {
		workers = p.WorkersPerHash
	}
	if workers <= 0 {
		workers = len(hashes) * 9
	}

	listenPort := p.Port
	if listenPort <= 0 {
		listenPort = p.ListenPort
	}
	if listenPort <= 0 {
		listenPort = 9000
	}

	name := strings.TrimSpace(p.Name)
	if name == "" {
		name = strings.TrimSpace(fallbackName)
	}
	if name == "" {
		name = "OBhoD_BLOK"
	}

	return &SubscriptionImportResult{
		Name:            name,
		Peer:            ensureDTLSPort(peer, 56000),
		Password:        password,
		Hashes:          hashes,
		Workers:         workers,
		ListenPort:      listenPort,
		Description:     description,
		SubscriptionURL: sourceURL,
	}, nil
}

func parseQwdttConfig(raw, sourceURL, fallbackName string) (*SubscriptionImportResult, error) {
	raw = strings.Replace(raw, "qwdtt:config?", "qwdtt://config?", 1)
	u, err := url.Parse(raw)
	if err != nil {
		return nil, fmt.Errorf("неверный qwdtt профиль")
	}
	q := u.Query()
	peer := strings.TrimSpace(q.Get("peer"))
	password := q.Get("pass")
	if password == "" {
		password = q.Get("password")
	}
	if peer == "" || password == "" {
		return nil, fmt.Errorf("qwdtt профиль не содержит peer/password")
	}
	hashes := splitHashes(q.Get("hashes"))
	if len(hashes) == 0 {
		return nil, fmt.Errorf("qwdtt профиль не содержит VK-хэши")
	}
	workers, _ := strconv.Atoi(q.Get("workers"))
	if workers <= 0 {
		workers = len(hashes) * 9
	}
	listenPort, _ := strconv.Atoi(q.Get("port"))
	if listenPort <= 0 {
		listenPort = 9000
	}
	name := strings.TrimSpace(q.Get("name"))
	if name == "" {
		name = fallbackName
	}
	if name == "" {
		name = "OBhoD_BLOK"
	}
	return &SubscriptionImportResult{
		Name: name, Peer: ensureDTLSPort(peer, 56000), Password: password,
		Hashes: hashes, Workers: workers, ListenPort: listenPort,
		SubscriptionURL: sourceURL,
	}, nil
}

func parseSubscriptionHashes(raw json.RawMessage) []string {
	if len(raw) == 0 || string(raw) == "null" {
		return nil
	}
	var s string
	if json.Unmarshal(raw, &s) == nil {
		return splitHashes(s)
	}
	var list []string
	if json.Unmarshal(raw, &list) == nil {
		out := make([]string, 0, len(list))
		for _, h := range list {
			h = strings.TrimSpace(h)
			if h != "" {
				out = append(out, h)
			}
		}
		return out
	}
	return nil
}

func splitHashes(v string) []string {
	fields := strings.FieldsFunc(v, func(r rune) bool {
		return r == ',' || r == ';' || r == '\n' || r == '\r'
	})
	out := make([]string, 0, len(fields))
	for _, h := range fields {
		h = strings.TrimSpace(h)
		if h != "" {
			out = append(out, h)
		}
	}
	return out
}

func ensureDTLSPort(peer string, defaultPort int) string {
	if peer == "" {
		return peer
	}
	if host, port, err := net.SplitHostPort(peer); err == nil && host != "" && port != "" {
		return peer
	}
	if ip := net.ParseIP(peer); ip != nil && strings.Contains(peer, ":") {
		return net.JoinHostPort(peer, strconv.Itoa(defaultPort))
	}
	if strings.HasPrefix(peer, "[") && strings.HasSuffix(peer, "]") {
		return peer + ":" + strconv.Itoa(defaultPort)
	}
	if i := strings.LastIndex(peer, ":"); i > 0 {
		if _, err := strconv.Atoi(peer[i+1:]); err == nil {
			return peer
		}
	}
	return peer + ":" + strconv.Itoa(defaultPort)
}
