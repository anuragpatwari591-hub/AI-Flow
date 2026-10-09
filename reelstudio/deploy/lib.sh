# Helper functions for deploy/setup-vps.sh (sourced; also unit-tested). No function here prints a secret.
valid_subdomain() { [[ "$1" =~ ^[a-z0-9]([a-z0-9-]{0,58}[a-z0-9])?$ ]]; }
gen_fernet_key()  { head -c 32 /dev/urandom | base64 | tr '+/' '-_'; }          # 44-char urlsafe base64 = valid Fernet key
gen_token()       { head -c 48 /dev/urandom | base64 | tr -d '=+/\n' | head -c 48; }
gen_password()    { head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
safe_value()      { [[ "$1" =~ ^[A-Za-z0-9._:-]+$ ]]; }                         # no spaces/quotes/#/$ that break .env
# write_env FILE DOMAIN META_ID META_SECRET  -> creates FILE (chmod 600) refusing to overwrite
write_env() {
  local f="$1" domain="$2" mid="$3" msec="$4"
  [ -e "$f" ] && { echo "refusing to overwrite existing $f" >&2; return 1; }
  ( umask 077
    {
      echo "RS_DOMAIN=$domain"
      echo "POSTGRES_PASSWORD=$(gen_password)"
      echo "RS_SECRET_KEY=$(gen_fernet_key)"
      echo "RS_DASHBOARD_TOKEN=$(gen_token)"
      echo "RS_META_APP_ID=$mid"
      echo "RS_META_APP_SECRET=$msec"
      echo "RS_GRAPH_VERSION=${RS_GRAPH_VERSION:-v21.0}"
      echo "RS_AI_PROVIDER=local"
    } > "$f" )
  chmod 600 "$f"
}
