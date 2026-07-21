#!/usr/bin/env python3
"""
投资看板本地代理服务器 (macOS 便携版 - 可分享给他人使用)
所有文件放在同一目录即可运行，无需修改任何路径。

用法：
    python3 fund-server.py                    # 自动查找同目录下的 HTML 文件
    python3 fund-server.py --port 8888        # 自定义端口
    python3 fund-server.py --html /path/to/file.html  # 手动指定 HTML
"""
import http.server
import urllib.request
import urllib.parse
import urllib.error
import os
import sys
import argparse
import socket

# ============================================================
# 自动检测：HTML 文件与本脚本/可执行文件在同一目录
# 兼容 PyInstaller --onefile 打包和普通 Python 脚本
# ============================================================
if getattr(sys, 'frozen', False):
    # PyInstaller 打包的独立可执行文件
    SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    # 普通 Python 脚本
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def find_html():
    """搜索同目录下的 HTML 文件，优先 基金股票查看.html"""
    candidates = ['基金股票查看.html']
    try:
        for f in sorted(os.listdir(SCRIPT_DIR)):
            if f.endswith('.html') and f not in candidates:
                candidates.append(f)
    except OSError:
        pass

    for name in candidates:
        path = os.path.join(SCRIPT_DIR, name)
        if os.path.isfile(path):
            return path
    return os.path.join(SCRIPT_DIR, '基金股票查看.html')


DEFAULT_HTML = find_html()
DEFAULT_PORT = 8765


# ============================================================
# HTTP 请求处理器
# ============================================================
class ProxyHandler(http.server.BaseHTTPRequestHandler):
    html_file = DEFAULT_HTML

    def log_message(self, format, *args):
        print(f"  [{self.log_date_time_string()}] {args[0]}")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path in ('/', '/index.html'):
            self.serve_html()
            return

        if parsed.path.startswith('/list=fu_'):
            self.proxy_sina()
            return

        if parsed.path == '/favicon.ico':
            self.send_error(404)
            return

        self.send_error(404, 'Not Found')

    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ('/', '/index.html'):
            try:
                with open(self.html_file, 'r', encoding='utf-8') as f:
                    f.read(1)
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
            except (FileNotFoundError, PermissionError):
                self.send_error(404)
        elif parsed.path.startswith('/list=fu_'):
            self.send_response(200)
            self.send_header('Content-Type', 'application/javascript; charset=utf-8')
            self.end_headers()
        else:
            self.send_error(404)

    def serve_html(self):
        try:
            with open(self.html_file, 'r', encoding='utf-8') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(content.encode('utf-8'))
        except FileNotFoundError:
            self.send_error(404, 'HTML file not found')
        except PermissionError:
            self.send_error(403, 'Permission denied')

    def proxy_sina(self):
        target_url = f'https://hq.sinajs.cn{self.path}'
        headers = {
            'Referer': 'https://finance.sina.com.cn/',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        try:
            req = urllib.request.Request(target_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read()
                charset = resp.headers.get_content_charset() or 'gbk'
                try:
                    text = body.decode(charset)
                except (UnicodeDecodeError, LookupError):
                    text = body.decode('gbk', errors='replace')
                self.send_response(200)
                self.send_header('Content-Type', 'application/javascript; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(text.encode('utf-8'))
        except urllib.error.HTTPError as e:
            print(f"    [ERROR] Sina HTTP {e.code}")
            self.send_error(502)
        except urllib.error.URLError as e:
            print(f"    [ERROR] Connection: {e.reason}")
            self.send_error(502)
        except Exception as e:
            print(f"    [ERROR] {e}")
            self.send_error(500)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='投资看板本地代理 (macOS 便携版)')
    parser.add_argument('--html', default=None,
                        help='HTML 文件路径 (默认: 自动查找同目录)')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT,
                        help=f'监听端口 (默认: {DEFAULT_PORT})')
    args = parser.parse_args()

    # 确定 HTML 文件
    html_path = args.html if args.html else DEFAULT_HTML
    ProxyHandler.html_file = html_path
    port = args.port

    print('=' * 50)
    print('  投资看板 - 本地代理服务')
    print('  macOS 便携版')
    print('=' * 50)
    print(f'  代理地址: http://localhost:{port}/')
    print(f'  HTML 文件: {ProxyHandler.html_file}')
    print(f'  按 Ctrl+C 停止服务')
    print('=' * 50)

    if not os.path.exists(ProxyHandler.html_file):
        print(f'  [WARN] HTML 文件不存在，服务仍会启动')
        print(f'  [WARN] 可使用 --html 参数指定正确路径')

    server = http.server.HTTPServer(('127.0.0.1', port), ProxyHandler)
    server.allow_reuse_address = True
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        print(f'  [OK] 服务已启动\n')
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n  服务已停止')
        server.server_close()
    except OSError as e:
        if e.errno == 48 or 'Address already in use' in str(e):
            print(f'\n  [ERROR] 端口 {port} 已被占用！')
            print(f'  请运行: lsof -ti:{port} | xargs kill -9')
        else:
            print(f'\n  [ERROR] {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
