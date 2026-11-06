"""
ipv4_guard.py — Transparent local IPv4 loopback proxy for Google Cloud / Antigravity APIs.

Bypasses ISP IPv6 route degradation, PMTU black holes, and packet drops by strictly
tunneling HTTP/HTTPS CONNECT requests over AF_INET (IPv4). Also forces netdns=cgo for Go binaries.
"""

import os
import sys
import socket
import select
import threading

_RUNNING_PROXY = None
_LOCK = threading.Lock()

class _LocalIPv4Proxy:
    def __init__(self):
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind(("127.0.0.1", 0))
        self.server_sock.listen(100)
        self.port = self.server_sock.getsockname()[1]
        self.running = True
        self.thread = threading.Thread(target=self._listen_loop, daemon=True, name="IPv4ProxyThread")
        self.thread.start()

    def _listen_loop(self):
        while self.running:
            try:
                client_sock, _ = self.server_sock.accept()
                threading.Thread(target=self._handle_client, args=(client_sock,), daemon=True).start()
            except Exception:
                break

    def _handle_client(self, client_sock):
        try:
            req = b""
            while b"\r\n\r\n" not in req:
                chunk = client_sock.recv(4096)
                if not chunk:
                    client_sock.close()
                    return
                req += chunk

            lines = req.split(b"\r\n")
            first_line = lines[0].decode("latin1", errors="replace")
            parts = first_line.split(" ")
            if len(parts) >= 2 and parts[0].upper() == "CONNECT":
                host_port = parts[1]
                host, port_str = host_port.split(":", 1) if ":" in host_port else (host_port, "443")
                port = int(port_str)
                addrs = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
                remote_sock = None
                for addr in addrs:
                    try:
                        remote_ip = addr[4][0]
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(10)
                        s.connect((remote_ip, port))
                        s.settimeout(None)
                        remote_sock = s
                        break
                    except Exception:
                        continue

                if remote_sock:
                    client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    self._tunnel(client_sock, remote_sock)
                else:
                    client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                    client_sock.close()
            else:
                host = None
                for line in lines[1:]:
                    if line.lower().startswith(b"host:"):
                        host_header = line.split(b":", 1)[1].strip().decode("latin1")
                        host = host_header.split(":")[0]
                        port = int(host_header.split(":")[1]) if ":" in host_header else 80
                        break
                if host:
                    addrs = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
                    remote_sock = None
                    for addr in addrs:
                        try:
                            remote_ip = addr[4][0]
                            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            s.settimeout(10)
                            s.connect((remote_ip, port))
                            s.settimeout(None)
                            remote_sock = s
                            break
                        except Exception:
                            continue

                    if remote_sock:
                        remote_sock.sendall(req)
                        self._tunnel(client_sock, remote_sock)
                    else:
                        client_sock.close()
                else:
                    client_sock.close()
        except Exception:
            try:
                client_sock.close()
            except Exception:
                pass

    def _tunnel(self, s1, s2):
        s1.settimeout(300.0)
        s2.settimeout(300.0)

        def pipe(src, dst):
            try:
                while self.running:
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
            except Exception:
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except Exception:
                    pass
                try:
                    dst.close()
                except Exception:
                    pass

        t1 = threading.Thread(target=pipe, args=(s1, s2), daemon=True)
        t2 = threading.Thread(target=pipe, args=(s2, s1), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        try:
            s1.close()
        except Exception:
            pass
        try:
            s2.close()
        except Exception:
            pass

    def stop(self):
        self.running = False
        try:
            self.server_sock.close()
        except Exception:
            pass


def _ensure_hosts_localhost():
    if sys.platform != "win32":
        return
    try:
        hosts_file = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), r"System32\drivers\etc\hosts")
        if os.path.isfile(hosts_file):
            with open(hosts_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if "127.0.0.1 localhost" not in content and "127.0.0.1\tlocalhost" not in content:
                with open(hosts_file, "a", encoding="utf-8") as f:
                    f.write("\n127.0.0.1 localhost\n::1 localhost\n")
    except Exception:
        pass


def start_ipv4_guard(force: bool = False) -> int:
    global _RUNNING_PROXY
    with _LOCK:
        if _RUNNING_PROXY and _RUNNING_PROXY.running:
            return _RUNNING_PROXY.port

        _ensure_hosts_localhost()

        existing = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        if existing and not force and "127.0.0.1" not in existing:
            return 0

        proxy = _LocalIPv4Proxy()
        _RUNNING_PROXY = proxy
        proxy_url = f"http://127.0.0.1:{proxy.port}"

        os.environ["HTTP_PROXY"] = proxy_url
        os.environ["HTTPS_PROXY"] = proxy_url
        os.environ["http_proxy"] = proxy_url
        os.environ["https_proxy"] = proxy_url

        no_proxy_val = "localhost,127.0.0.1,::1,*.ngrok-free.dev,*.ngrok.io,ngrok-free.dev,ngrok.io"
        curr_no = os.environ.get("NO_PROXY", "")
        os.environ["NO_PROXY"] = f"{curr_no},{no_proxy_val}".strip(",")
        os.environ["no_proxy"] = os.environ["NO_PROXY"]

        godebug = os.environ.get("GODEBUG", "")
        parts = [p for p in godebug.split(",") if not p.startswith("netdns=") and p]
        parts.append("netdns=cgo")
        os.environ["GODEBUG"] = ",".join(parts)

        return proxy.port


def stop_ipv4_guard():
    global _RUNNING_PROXY
    with _LOCK:
        if _RUNNING_PROXY:
            _RUNNING_PROXY.stop()
            _RUNNING_PROXY = None
            for key in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
                val = os.environ.get(key, "")
                if "127.0.0.1" in val:
                    os.environ.pop(key, None)
