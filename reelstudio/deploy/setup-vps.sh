#!/usr/bin/env bash
# One-shot setup on a fresh Ubuntu 24.04 VPS. Run from the repo:  cd reelstudio && bash deploy/setup-vps.sh
# - installs Docker + Compose, opens only SSH/80/443
# - checks your DuckDNS name points at THIS server (needed for Let's Encrypt)
# - generates secrets locally into .env (chmod 600) without printing them; asks (silently) for your Meta app ID/secret
# - starts the stack. It never enables Instagram publishing and never publishes anything.
set -euo pipefail
cd "$(dirname "$0")/.."
. deploy/lib.sh

grep -q "Ubuntu" /etc/os-release || { echo "This script targets Ubuntu 24.04 LTS."; exit 1; }
echo "==> Installing Docker, Compose, firewall"
sudo apt-get update -y
sudo apt-get install -y docker.io docker-compose-v2 ufw curl dnsutils
sudo systemctl enable --now docker
docker_c() { sudo docker "$@"; }
docker_c compose version >/dev/null || { echo "docker compose v2 missing; use Ubuntu 24.04"; exit 1; }

if [ "$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)" -lt 1800 ] && ! swapon --show | grep -q .; then
  echo "==> Low RAM: adding a 2 GB swapfile so rendering does not get OOM-killed"
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
  echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
fi

echo "==> Firewall: allow SSH, 80, 443 only"
sudo ufw allow OpenSSH >/dev/null
sudo ufw allow 80/tcp >/dev/null
sudo ufw allow 443/tcp >/dev/null
sudo ufw --force enable >/dev/null

if [ -e .env ]; then
  echo "==> Using existing .env (not modified)"
else
  read -r -p "Your DuckDNS subdomain (just the name, e.g. anurag-reels): " SUB
  valid_subdomain "$SUB" || { echo "invalid subdomain (lowercase letters, digits, hyphens)"; exit 1; }
  DOMAIN="$SUB.duckdns.org"
  MYIP="$(curl -4 -fsS https://api.ipify.org)"
  DNSIP="$(dig +short A "$DOMAIN" | tail -n1)"
  echo "This server's public IPv4: $MYIP;  $DOMAIN resolves to: ${DNSIP:-nothing}"
  [ "$MYIP" = "$DNSIP" ] || { echo "DNS mismatch: set the IP for '$SUB' at duckdns.org to $MYIP, wait a minute, re-run."; exit 1; }
  read -r -p "Meta INSTAGRAM app ID (Instagram > API setup with Instagram login): " MID
  read -r -s -p "Meta INSTAGRAM app secret (hidden as you type): " MSEC; echo
  safe_value "$MID" && safe_value "$MSEC" || { echo "unexpected characters in app id/secret"; exit 1; }
  write_env .env "$DOMAIN" "$MID" "$MSEC"
  unset MSEC
  echo "==> .env created (chmod 600). Secrets were generated locally and not printed."
fi

echo "==> Building and starting (first build takes several minutes)"
docker_c compose up -d --build
echo "==> Waiting for the API to become healthy"
for i in $(seq 1 60); do
  [ "$(docker_c compose ps --format '{{.Health}}' api 2>/dev/null)" = "healthy" ] && break; sleep 5
done
docker_c compose exec -T api reelstudio setup --check || true
DOMAIN="$(grep '^RS_DOMAIN=' .env | cut -d= -f2)"
echo
echo "Dashboard:      https://$DOMAIN/   (login token = RS_DASHBOARD_TOKEN inside .env; view it only on this server)"
echo "Meta callback:  https://$DOMAIN/api/instagram/callback   <- register EXACTLY this in Meta (OAuth redirect URIs)"
echo "Next: register the Meta callback above, then run:   sudo docker compose exec api reelstudio setup"
echo "      (it prints your Instagram Connect URL, waits while you authorize in the browser, then verifies permissions)."
echo "Publishing is OFF and every post needs your approval."
