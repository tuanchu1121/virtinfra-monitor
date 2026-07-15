# Domain, Nginx and HTTPS

Recommended production path:

```text
Internet → Nginx :443 → Gunicorn 127.0.0.1:8080 → PostgreSQL loopback
```

## First install

1. Point A/AAAA records at the Monitor.
2. Allow inbound TCP 80 and 443.
3. Run:

```bash
curl -fsSL \
https://raw.githubusercontent.com/tuanchu1121/bw-monitor-production.1/main/install.sh \
| bash -s -- \
--domain monitor.example.com \
--email ops@example.com
```

## Switch an existing IP install to domain

```bash
virtinfra-monitorctl domain set monitor.example.com ops@example.com
```

The PostgreSQL volume, users, Agent token, settings and data are preserved.

## Switch back to IP

```bash
virtinfra-monitorctl domain remove 203.0.113.10 8080
```

## Certificate checks

```bash
certbot certificates
systemctl status certbot.timer --no-pager
nginx -t
curl -I https://monitor.example.com/login
```

## DNS/CAA failures

```bash
dig +short monitor.example.com A
dig +short monitor.example.com AAAA
dig +short monitor.example.com CAA
```

The A/AAAA record must resolve to this server. CAA must permit Let's Encrypt or be absent.
