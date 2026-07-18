#!/usr/bin/env bash
set -Eeuo pipefail
DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
echo 'VirtInfra Monitor v50 setup wizard'
read -r -p 'Use domain? [y/N]: ' use_domain
if [[ "$use_domain" =~ ^[Yy]$ ]]; then
  read -r -p 'Domain: ' domain
  read -r -p "Let's Encrypt email: " email
  exec bash "$DIR/install.sh" --domain "$domain" --email "$email" "$@"
else
  read -r -p 'Public IP (blank = auto): ' ip
  if [[ -n "$ip" ]]; then exec bash "$DIR/install.sh" --public-ip "$ip" "$@"; else exec bash "$DIR/install.sh" "$@"; fi
fi
