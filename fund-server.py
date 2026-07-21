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
import json
import time
import datetime

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
LOG_FILE = os.path.join(SCRIPT_DIR, 'proxy.log')

# 启动时间，用于健康检查
START_TIME = time.time()

# 数据源连通性统计
sina_stats = {'success': 0, 'fail': 0, 'last_success': 0, 'last_error': '', 'last_error_time': 0}

# ============================================================
# 日志
# ============================================================
def log(msg):
    """同时输出到控制台和日志文件"""
    ts = datetime.datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass  # 日志写入失败不阻断服务


# ============================================================
# 启动诊断：测试新浪 API 连通性
# ============================================================
def check_sina_connectivity():
    """测试是否能够访问新浪基金 API"""
    log('--- 启动诊断 ---')
    log(f'  Python 版本: {sys.version.split()[0]}')
    log(f'  工作目录: {SCRIPT_DIR}')
    log(f'  HTML 文件: {DEFAULT_HTML}')

    test_code = '000001'  # 华夏成长混合
    test_url = f'https://hq.sinajs.cn/list=fu_{test_code}'
    headers = {
        'Referer': 'https://finance.sina.com.cn/',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    }

    try:
        req = urllib.request.Request(test_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            code = resp.getcode()
            charset = resp.headers.get_content_charset() or 'gbk'
            text = body.decode(charset, errors='replace')

            # 解析返回数据验证格式
            if 'hq_str_fu_' in text and ',' in text:
                parts = text.split('=')[-1].strip(';').strip().strip('"').split(',')
                fund_name = parts[0] if len(parts) > 0 else '?'
                fund_date = parts[7] if len(parts) > 7 else '?'
                log(f'  [OK] 新浪 API 连通性正常 → {fund_name} (日期: {fund_date})')
                return True
            else:
                log(f'  [WARN] 新浪 API 返回格式异常: {text[:100]}')
                return False
    except urllib.error.HTTPError as e:
        log(f'  [FAIL] 新浪 API HTTP 错误: {e.code} {e.reason}')
        return False
    except urllib.error.URLError as e:
        log(f'  [FAIL] 新浪 API 连接失败: {e.reason}')
        log(f'  可能原因: 网络问题 / DNS 解析失败 / 防火墙拦截')
        return False
    except Exception as e:
        log(f'  [FAIL] 新浪 API 未知错误: {e}')
        return False


# ============================================================
# HTTP 请求处理器
# ============================================================
class ProxyHandler(http.server.BaseHTTPRequestHandler):
    html_file = DEFAULT_HTML

    def log_message(self, format, *args):
        """简洁日志"""
        if '/list=fu_' in str(args[0]):
            # 基金数据请求不打印详细日志避免刷屏
            pass
        else:
            log(f'  [{self.client_address[0]}] {args[0]}')

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path in ('/', '/index.html'):
            self.serve_html()
            return

        if parsed.path.startswith('/list=fu_'):
            self.proxy_sina()
            return

        if parsed.path == '/health':
            self.serve_health()
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
        elif parsed.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
        else:
            self.send_error(404)

    def serve_html(self):
        """提供投资看板 HTML 文件"""
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

    def serve_health(self):
        """健康检查 + 数据源诊断 endpoint"""
        uptime = int(time.time() - START_TIME)
        health = {
            'status': 'running',
            'uptime_sec': uptime,
            'uptime': f'{uptime // 3600}h {(uptime % 3600) // 60}m {uptime % 60}s',
            'port': DEFAULT_PORT,
            'html_file': self.html_file,
            'sina_ok': sina_stats['last_success'] > 0,
            'sina_success': sina_stats['success'],
            'sina_fail': sina_stats['fail'],
            'sina_last_success_ago_sec': int(time.time() - sina_stats['last_success']) if sina_stats['last_success'] > 0 else -1,
            'sina_last_error': sina_stats['last_error'],
            'sina_last_error_ago_sec': int(time.time() - sina_stats['last_error_time']) if sina_stats['last_error_time'] > 0 else -1,
            'current_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(json.dumps(health, ensure_ascii=False, indent=2).encode('utf-8'))

    def proxy_sina(self):
        """转发请求到新浪 API，添加 Referer 头"""
        target_url = f'https://hq.sinajs.cn{self.path}'
        headers = {
            'Referer': 'https://finance.sina.com.cn/',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        code = self.path.replace('/list=fu_', '').split('?')[0]

        try:
            req = urllib.request.Request(target_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read()
                charset = resp.headers.get_content_charset() or 'gbk'
                try:
                    text = body.decode(charset)
                except (UnicodeDecodeError, LookupError):
                    text = body.decode('gbk', errors='replace')

                # 验证返回数据有效性
                if 'hq_str_fu_' in text and ',' in text:
                    sina_stats['success'] += 1
                    sina_stats['last_success'] = time.time()
                else:
                    sina_stats['fail'] += 1
                    sina_stats['last_error'] = f'Invalid response format: {text[:80]}'
                    sina_stats['last_error_time'] = time.time()
                    log(f'  [WARN] 基金 {code} 返回格式异常: {text[:80]}')

                self.send_response(200)
                self.send_header('Content-Type', 'application/javascript; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(text.encode('utf-8'))
        except urllib.error.HTTPError as e:
            sina_stats['fail'] += 1
            error_msg = f'HTTP {e.code}: {e.reason}'
            sina_stats['last_error'] = error_msg
            sina_stats['last_error_time'] = time.time()
            log(f'  [ERROR] 基金 {code} → {error_msg}')
            self.send_error(502)
        except urllib.error.URLError as e:
            sina_stats['fail'] += 1
            error_msg = f'Connection: {e.reason}'
            sina_stats['last_error'] = error_msg
            sina_stats['last_error_time'] = time.time()
            log(f'  [ERROR] 基金 {code} → {error_msg}')
            self.send_error(502)
        except Exception as e:
            sina_stats['fail'] += 1
            error_msg = str(e)
            sina_stats['last_error'] = error_msg
            sina_stats['last_error_time'] = time.time()
            log(f'  [ERROR] 基金 {code} → {error_msg}')
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

    # 清空旧日志
    try:
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            f.write(f'=== 投资看板代理日志 {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")} ===\n')
    except Exception:
        pass

    print('=' * 50)
    print('  投资看板 - 本地代理服务')
    print('  macOS 便携版 v2.0')
    print('=' * 50)
    log(f'代理地址: http://localhost:{port}/')
    log(f'HTML 文件: {ProxyHandler.html_file}')
    log(f'日志文件: {LOG_FILE}')
    print('=' * 50)

    if not os.path.exists(ProxyHandler.html_file):
        log('[WARN] HTML 文件不存在，服务仍会启动')
        log('[WARN] 可使用 --html 参数指定正确路径')

    # 启动诊断
    sina_ok = check_sina_connectivity()
    if not sina_ok:
        log('[WARN] 新浪 API 连接失败，基金将回退到东方财富历史净值（可能显示前一日数据）')
    print('=' * 50)

    server = http.server.HTTPServer(('127.0.0.1', port), ProxyHandler)
    server.allow_reuse_address = True
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        log('[OK] 服务已启动\n')
        server.serve_forever()
    except KeyboardInterrupt:
        log('服务已停止')
        server.server_close()
    except OSError as e:
        if e.errno == 48 or 'Address already in use' in str(e):
            log(f'[ERROR] 端口 {port} 已被占用！')
            log(f'  请运行: lsof -ti:{port} | xargs kill -9')
        else:
            log(f'[ERROR] {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
