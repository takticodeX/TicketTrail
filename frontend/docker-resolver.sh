#!/bin/sh
# Point Nginx at the container's DNS server, so it re-resolves "api" when that
# container is recreated with a new address instead of keeping the old one.
# Docker and Podman use different DNS addresses, so read it at start-up.
# Written under /tmp: the container's filesystem is otherwise read-only.
set -eu

nameserver=$(awk '/^nameserver/ { print $2; exit }' /etc/resolv.conf)
case "$nameserver" in
  *:*) nameserver="[$nameserver]" ;;  # IPv6 needs brackets
esac
mkdir -p /tmp/nginx
echo "resolver ${nameserver:-127.0.0.11} valid=10s ipv6=off;" > /tmp/nginx/resolver.conf
