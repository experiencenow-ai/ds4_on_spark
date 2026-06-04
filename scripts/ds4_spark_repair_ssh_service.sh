#!/usr/bin/env bash
set -euo pipefail

echo "== identity =="
hostname || true
date -u +"%Y-%m-%dT%H:%M:%SZ" || true

echo "== network =="
ip -brief addr show || true
ip route get 10.20.0.1 || true

echo "== ssh units before =="
systemctl --no-pager --full status ssh.service || true
systemctl --no-pager --full status ssh.socket || true

echo "== repair ssh service =="
sudo systemctl disable --now ssh.socket || true
sudo systemctl enable ssh.service
sudo systemctl restart ssh.service

echo "== ssh listener =="
ss -ltnp | grep -E '(:22[[:space:]]|:22$)' || true

echo "== ssh units after =="
systemctl --no-pager --full status ssh.service || true
systemctl --no-pager --full status ssh.socket || true
