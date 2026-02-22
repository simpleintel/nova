#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# Nova — GCP Deployment Script
# Run this on your GCP VM after cloning/uploading the project
# ═══════════════════════════════════════════════════════════════════════

set -e

echo ""
echo "  ╔═══════════════════════════════════════╗"
echo "  ║     Nova — GCP Deployment Setup        ║"
echo "  ╚═══════════════════════════════════════╝"
echo ""

# ── System packages ──────────────────────────────────────────────────
echo "[1/5] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv nginx

# ── Python environment ───────────────────────────────────────────────
echo "[2/5] Setting up Python environment..."
cd /opt/talktome 2>/dev/null || { sudo mkdir -p /opt/talktome; sudo cp -r . /opt/talktome/; cd /opt/talktome; }
sudo python3 -m venv venv
sudo ./venv/bin/pip install --quiet flask flask-socketio gunicorn gevent gevent-websocket

# ── Environment file ─────────────────────────────────────────────────
echo "[3/5] Setting up environment..."
if [ ! -f /opt/talktome/.env ]; then
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    sudo tee /opt/talktome/.env > /dev/null <<EOF
GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID:-""}
SECRET_KEY=${SECRET}
RETENTION_DAYS=730
EOF
    echo "  → Created /opt/talktome/.env"
    echo "  → IMPORTANT: Edit this file to set your GOOGLE_CLIENT_ID"
else
    echo "  → .env already exists, skipping"
fi

# ── Systemd service ──────────────────────────────────────────────────
echo "[4/5] Installing systemd service..."
sudo tee /etc/systemd/system/talktome.service > /dev/null <<'EOF'
[Unit]
Description=Nova P2P Chat Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/talktome
EnvironmentFile=/opt/talktome/.env
ExecStart=/opt/talktome/venv/bin/gunicorn \
    --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker \
    --workers 1 \
    --bind 0.0.0.0:5000 \
    --timeout 120 \
    --keep-alive 65 \
    app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable talktome
sudo systemctl restart talktome

# ── Nginx reverse proxy ──────────────────────────────────────────────
echo "[5/5] Configuring Nginx..."
sudo tee /etc/nginx/sites-available/talktome > /dev/null <<'EOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/talktome /etc/nginx/sites-enabled/talktome
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

echo ""
echo "  ✅ Nova deployed successfully!"
echo ""
echo "  App:     http://$(curl -s ifconfig.me 2>/dev/null || echo 'YOUR_VM_IP')"
echo "  Service: sudo systemctl status talktome"
echo "  Logs:    sudo journalctl -u talktome -f"
echo "  Config:  /opt/talktome/.env"
echo ""
echo "  Next steps:"
echo "    1. Edit /opt/talktome/.env and set GOOGLE_CLIENT_ID"
echo "    2. Add your VM's external IP to Google OAuth Authorized Origins"
echo "    3. sudo systemctl restart talktome"
echo ""
