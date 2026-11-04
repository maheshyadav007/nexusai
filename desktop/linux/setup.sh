#!/usr/bin/env bash
# Run by desktop.cmd server-setup through sudo. Does not replace other nginx sites.
set -euo pipefail
release_root=$1
owner=$2
port=$3
certificate=${4:-}
certificate_key=${5:-}
[[ $(id -u) == 0 ]] || { echo 'Server setup requires sudo/root.' >&2; exit 1; }
[[ $release_root =~ ^/[a-zA-Z0-9_/-]+$ && $release_root != / && $release_root != *..* ]]
owner_id=$(id -u -- "$owner")
[[ $port =~ ^[0-9]+$ && $port -ge 1 && $port -le 65535 ]]
if ! command -v nginx >/dev/null || ! command -v python3 >/dev/null; then
  if command -v apt-get >/dev/null; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y nginx python3
  elif command -v dnf >/dev/null; then
    dnf install -y nginx python3
  else
    echo 'Install nginx and Python >=3.8 first (supported automatic setup: apt/dnf).' >&2
    exit 1
  fi
fi
python3 -c 'import sys; assert sys.version_info >= (3, 8), "Server publication requires Python >=3.8"'
if [[ -d $release_root && ! -f $release_root/.nexusai-release-host && -n $(ls -A "$release_root") ]]; then
  echo 'Refusing to take over a nonempty directory not created by NexusAI. Choose a dedicated server.root.' >&2
  exit 1
fi
for directory in "$release_root" "$release_root/windows/x64" "$release_root/windows/x64/unsigned"; do
  install -d -m 755 -o "$owner_id" "$directory"
done
touch "$release_root/.nexusai-release-host"
for directory in "$release_root/windows/x64/.incoming" "$release_root/windows/x64/unsigned/.incoming"; do
  install -d -m 700 -o "$owner_id" "$directory"
done
tls=''
if [[ -n $certificate || -n $certificate_key ]]; then
  [[ -f $certificate && -f $certificate_key ]] || { echo 'TLS certificate/key missing.' >&2; exit 1; }
  tls="ssl_certificate $certificate; ssl_certificate_key $certificate_key;"
  listen="$port ssl"
else
  listen=$port
fi
conf=$(mktemp)
trap 'rm -f "$conf"' EXIT
cat > "$conf" <<EOF
# Managed by NexusAI desktop server-setup. Other nginx sites are unchanged.
server {
    listen $listen;
    server_name _;
    $tls
    root $release_root;
    autoindex off;
    location ~ /\. { deny all; }
    location ~ \.yml\$ {
        add_header Cache-Control "no-store" always;
        default_type application/yaml;
        try_files \$uri =404;
    }
    location / {
        add_header Cache-Control "public, max-age=31536000, immutable";
        try_files \$uri =404;
    }
}
EOF
config=/etc/nginx/conf.d/nexusai-updates.conf
backup=$(mktemp)
had_previous=false
if [[ -f $config ]]; then cp "$config" "$backup"; had_previous=true; fi
install -m 644 "$conf" "$config"
if ! nginx -t; then
  if $had_previous; then cp "$backup" "$config"; else rm -f "$config"; fi
  rm -f "$backup"
  exit 1
fi
rm -f "$backup"
if command -v getenforce >/dev/null && [[ $(getenforce) != Disabled ]]; then
  if command -v semanage >/dev/null; then
    semanage fcontext -a -t httpd_sys_content_t "${release_root}(/.*)?" 2>/dev/null || semanage fcontext -m -t httpd_sys_content_t "${release_root}(/.*)?"
    semanage port -a -t http_port_t -p tcp "$port" 2>/dev/null || true
    restorecon -R "$release_root"
  else
    echo 'SELinux is enabled: configure httpd_sys_content_t and allow the nginx TCP port before testing.' >&2
  fi
fi
systemctl enable --now nginx
systemctl reload nginx
if command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port="${port}/tcp"
  firewall-cmd --reload
fi
echo "NexusAI host configured on port $port. Check any UFW, external firewall or company network rules separately."
echo "Artifacts root: $release_root/windows/x64/"
