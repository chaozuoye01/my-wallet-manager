"""
EVM 多地址资产管理系统
基于 OKX Wallet API (all-token-balances-by-address)
"""

import json
import hmac
import hashlib
import base64
import time
import os
import threading
import requests
from collections import deque
from datetime import datetime, timezone
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from urllib.parse import urlencode

app = Flask(__name__)

CONFIG_FILE = "wallets.json"
API_CONFIG_FILE = "api_config.json"
RATE_CONFIG_FILE = "rate_config.json"

EVM_CHAINS = {
    "1":     {"name": "Ethereum",   "symbol": "ETH",  "color": "#627EEA"},
    "56":    {"name": "BNB Chain",  "symbol": "BNB",  "color": "#F0B90B"},
    "137":   {"name": "Polygon",    "symbol": "MATIC","color": "#8247E5"},
    "42161": {"name": "Arbitrum",   "symbol": "ETH",  "color": "#28A0F0"},
    "10":    {"name": "Optimism",   "symbol": "ETH",  "color": "#FF0420"},
    "43114": {"name": "Avalanche",  "symbol": "AVAX", "color": "#E84142"},
    "8453":  {"name": "Base",       "symbol": "ETH",  "color": "#0052FF"},
    "324":   {"name": "zkSync Era", "symbol": "ETH",  "color": "#1755F4"},
    "59144": {"name": "Linea",      "symbol": "ETH",  "color": "#61DFFF"},
    "250":   {"name": "Fantom",     "symbol": "FTM",  "color": "#1969FF"},
    "25":    {"name": "Cronos",     "symbol": "CRO",  "color": "#002D74"},
    "100":   {"name": "Gnosis",     "symbol": "XDAI", "color": "#04795B"},
}

# ============================================================
# 限速管理器
# ============================================================
class RateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._request_times = deque()   # 最近请求的时间戳
        self._interval = 1.0            # 请求间隔（秒）
        self._max_retries = 3           # 限速时最大重试次数
        self._retry_backoff = 2.0       # 重试退避系数
        self._total_requests = 0        # 累计请求数
        self._total_errors = 0          # 累计错误数
        self._total_retries = 0         # 累计重试数
        self._last_request_time = 0     # 上次请求时间
        self._window = 60               # 统计窗口（秒）

    def configure(self, interval: float, max_retries: int = 3):
        with self._lock:
            self._interval = max(0.2, float(interval))
            self._max_retries = max(1, int(max_retries))

    def wait(self):
        """等待直到可以发出下一个请求"""
        with self._lock:
            now = time.time()
            elapsed = now - self._last_request_time
            wait_time = self._interval - elapsed
            if wait_time > 0:
                time.sleep(wait_time)
            self._last_request_time = time.time()
            self._request_times.append(self._last_request_time)
            # 清理窗口外的记录
            cutoff = self._last_request_time - self._window
            while self._request_times and self._request_times[0] < cutoff:
                self._request_times.popleft()
            self._total_requests += 1

    def get_status(self) -> dict:
        with self._lock:
            now = time.time()
            cutoff = now - self._window
            recent = [t for t in self._request_times if t >= cutoff]
            rpm = len(recent)
            rps = round(1.0 / self._interval, 2) if self._interval > 0 else 0
            last_ago = round(now - self._last_request_time, 1) if self._last_request_time else None
            return {
                "interval": self._interval,
                "max_retries": self._max_retries,
                "rps_limit": rps,
                "rpm_actual": rpm,
                "total_requests": self._total_requests,
                "total_errors": self._total_errors,
                "total_retries": self._total_retries,
                "last_request_ago": last_ago,
            }

    def record_error(self):
        with self._lock:
            self._total_errors += 1

    def record_retry(self):
        with self._lock:
            self._total_retries += 1

    @property
    def interval(self):
        return self._interval

    @property
    def max_retries(self):
        return self._max_retries

# 全局限速器
rate_limiter = RateLimiter()

# ============================================================
# 本地存储
# ============================================================
def load_wallets():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_wallets(wallets):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(wallets, f, ensure_ascii=False, indent=2)

def load_api_config():
    if os.path.exists(API_CONFIG_FILE):
        with open(API_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"api_key": "", "secret_key": "", "passphrase": "", "project_id": ""}

def save_api_config(config):
    with open(API_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def load_rate_config():
    if os.path.exists(RATE_CONFIG_FILE):
        with open(RATE_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"interval": 1.0, "max_retries": 3}

def save_rate_config(cfg):
    with open(RATE_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

# 启动时加载限速配置
_rc = load_rate_config()
rate_limiter.configure(_rc.get("interval", 1.0), _rc.get("max_retries", 3))

# ============================================================
# OKX API 签名
# ============================================================
def generate_signature(timestamp, method, request_path, body, secret_key):
    message = timestamp + method.upper() + request_path + (body or "")
    mac = hmac.new(secret_key.encode(), message.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def get_okx_headers(method, path, params, config):
    ts = datetime.now(timezone.utc)
    timestamp = ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"
    query_string = ("?" + urlencode(params)) if method.upper() == "GET" and params else ""
    full_path = path + query_string
    body = "" if method.upper() == "GET" else json.dumps(params)
    sign = generate_signature(timestamp, method, full_path, body, config["secret_key"])
    return {
        "Content-Type": "application/json",
        "OK-ACCESS-KEY": config["api_key"],
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": config["passphrase"],
        "OK-ACCESS-PROJECT": config["project_id"],
    }

# ============================================================
# 带限速 + 重试的 API 请求
# ============================================================
def fetch_balances(address: str, chains: list, config: dict) -> list:
    url = "https://web3.okx.com/api/v5/wallet/asset/all-token-balances-by-address"
    path = "/api/v5/wallet/asset/all-token-balances-by-address"
    params = {"address": address, "chains": ",".join(chains), "filter": "0"}

    last_err = None
    for attempt in range(rate_limiter.max_retries + 1):
        rate_limiter.wait()  # 限速等待
        try:
            headers = get_okx_headers("GET", path, params, config)
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            data = resp.json()

            # 429 限速错误 → 退避重试
            if resp.status_code == 429 or data.get("code") == "50011":
                if attempt < rate_limiter.max_retries:
                    backoff = 2.0 ** attempt
                    rate_limiter.record_retry()
                    time.sleep(backoff)
                    continue
                raise Exception("API 限速（429），已达最大重试次数")

            if data.get("code") != "0":
                raise Exception(f"API错误: {data.get('msg','未知')} (code:{data.get('code')})")

            return data["data"][0].get("tokenAssets", [])

        except Exception as e:
            last_err = e
            rate_limiter.record_error()
            if attempt < rate_limiter.max_retries:
                rate_limiter.record_retry()
                time.sleep(1.5 * (attempt + 1))
            else:
                raise last_err

    raise last_err or Exception("未知错误")

# ============================================================
# 数据处理
# ============================================================
def process_assets(token_assets: list) -> dict:
    by_chain = {}
    total_usd = 0.0
    for token in token_assets:
        chain_id = token.get("chainIndex", "unknown")
        try:
            balance = float(token.get("balance", 0))
            price = float(token.get("tokenPrice", 0))
            usd_value = balance * price
        except:
            usd_value = balance = price = 0.0
        if usd_value < 0.01:
            continue
        total_usd += usd_value
        if chain_id not in by_chain:
            ci = EVM_CHAINS.get(chain_id, {"name": f"Chain {chain_id}", "color": "#888"})
            by_chain[chain_id] = {"chain_name": ci["name"], "chain_color": ci["color"], "chain_usd": 0.0, "tokens": []}
        by_chain[chain_id]["chain_usd"] += usd_value
        by_chain[chain_id]["tokens"].append({
            "symbol": token.get("symbol", "?"),
            "balance": f"{balance:.6f}".rstrip("0").rstrip("."),
            "price": f"${price:,.4f}" if price > 0 else "$0",
            "usd_value": usd_value,
            "usd_display": f"${usd_value:,.2f}",
            "token_address": token.get("tokenAddress", ""),
            "is_risk": token.get("isRiskToken", False),
        })
    for cid in by_chain:
        by_chain[cid]["tokens"].sort(key=lambda x: x["usd_value"], reverse=True)
        by_chain[cid]["chain_usd_display"] = f"${by_chain[cid]['chain_usd']:,.2f}"
    return {
        "total_usd": total_usd,
        "total_usd_display": f"${total_usd:,.2f}",
        "by_chain": dict(sorted(by_chain.items(), key=lambda x: x[1]["chain_usd"], reverse=True))
    }

# ============================================================
# Flask 路由
# ============================================================
@app.route("/")
def index():
    wallets = load_wallets()
    api_config = load_api_config()
    chain_list = [{"id": k, **v} for k, v in EVM_CHAINS.items()]
    rate_cfg = load_rate_config()
    return render_template("index.html", wallets=wallets, api_config=api_config,
                           chain_list=chain_list, rate_cfg=rate_cfg)

@app.route("/api/save-config", methods=["POST"])
def save_config():
    save_api_config(request.json)
    return jsonify({"success": True})

@app.route("/api/rate-config", methods=["GET"])
def get_rate_config():
    return jsonify({**load_rate_config(), **rate_limiter.get_status()})

@app.route("/api/rate-config", methods=["POST"])
def set_rate_config():
    data = request.json
    interval = float(data.get("interval", 1.0))
    max_retries = int(data.get("max_retries", 3))
    interval = max(0.2, min(10.0, interval))
    max_retries = max(1, min(10, max_retries))
    rate_limiter.configure(interval, max_retries)
    cfg = {"interval": interval, "max_retries": max_retries}
    save_rate_config(cfg)
    return jsonify({"success": True, **cfg})

@app.route("/api/rate-status")
def rate_status():
    return jsonify(rate_limiter.get_status())

@app.route("/api/wallets", methods=["GET"])
def get_wallets():
    return jsonify(load_wallets())

@app.route("/api/wallets", methods=["POST"])
def add_wallet():
    data = request.json
    wallets = load_wallets()
    address = data.get("address", "").lower().strip()
    label = data.get("label", "").strip() or f"钱包 {len(wallets)+1}"
    if any(w["address"].lower() == address for w in wallets):
        return jsonify({"success": False, "error": "地址已存在"}), 400
    wallets.append({"address": address, "label": label,
                    "added_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "chains": data.get("chains", list(EVM_CHAINS.keys()))})
    save_wallets(wallets)
    return jsonify({"success": True})

@app.route("/api/wallets/<address>", methods=["DELETE"])
def delete_wallet(address):
    wallets = [w for w in load_wallets() if w["address"].lower() != address.lower()]
    save_wallets(wallets)
    return jsonify({"success": True})

@app.route("/api/wallets/<address>/label", methods=["PUT"])
def update_label(address):
    data = request.json
    wallets = load_wallets()
    for w in wallets:
        if w["address"].lower() == address.lower():
            w["label"] = data.get("label", w["label"])
    save_wallets(wallets)
    return jsonify({"success": True})

@app.route("/api/query/<address>")
def query_wallet(address):
    config = load_api_config()
    if not config.get("api_key"):
        return jsonify({"error": "请先配置 OKX API Key"}), 400
    wallets = load_wallets()
    wallet = next((w for w in wallets if w["address"].lower() == address.lower()), None)
    chains = wallet.get("chains", list(EVM_CHAINS.keys())) if wallet else list(EVM_CHAINS.keys())
    try:
        token_assets = fetch_balances(address, chains, config)
        result = process_assets(token_assets)
        return jsonify({"success": True, "data": result, "address": address})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ── SSE 流式查询所有钱包（实时进度推送）──
@app.route("/api/query-all-stream")
def query_all_stream():
    config = load_api_config()
    if not config.get("api_key"):
        def err():
            yield "data: " + json.dumps({"type":"error","msg":"请先配置 OKX API Key"}) + "\n\n"
        return Response(stream_with_context(err()), mimetype="text/event-stream")

    wallets = load_wallets()
    if not wallets:
        def err():
            yield "data: " + json.dumps({"type":"error","msg":"请先添加钱包地址"}) + "\n\n"
        return Response(stream_with_context(err()), mimetype="text/event-stream")

    def generate():
        results = []
        grand_total = 0.0
        chain_totals = {}
        total = len(wallets)

        yield "data: " + json.dumps({"type":"start","total":total}) + "\n\n"

        for i, wallet in enumerate(wallets):
            addr = wallet["address"]
            lbl  = wallet["label"]
            chains = wallet.get("chains", list(EVM_CHAINS.keys()))

            # 推送：开始查询该地址
            yield "data: " + json.dumps({
                "type": "querying",
                "index": i, "total": total,
                "address": addr, "label": lbl,
                "pct": round(i / total * 100),
                "rate_status": rate_limiter.get_status()
            }) + "\n\n"

            try:
                token_assets = fetch_balances(addr, chains, config)
                result = process_assets(token_assets)
                grand_total += result["total_usd"]

                for cid, cd in result["by_chain"].items():
                    if cid not in chain_totals:
                        chain_totals[cid] = {"name": cd["chain_name"], "color": cd["chain_color"], "usd": 0.0}
                    chain_totals[cid]["usd"] += cd["chain_usd"]

                results.append({"address": addr, "label": lbl, "data": result, "error": None})

                yield "data: " + json.dumps({
                    "type": "done_one",
                    "index": i, "total": total,
                    "address": addr, "label": lbl,
                    "total_usd": result["total_usd_display"],
                    "pct": round((i + 1) / total * 100),
                    "rate_status": rate_limiter.get_status()
                }) + "\n\n"

            except Exception as e:
                results.append({"address": addr, "label": lbl, "data": None, "error": str(e)})
                yield "data: " + json.dumps({
                    "type": "error_one",
                    "index": i, "total": total,
                    "address": addr, "label": lbl,
                    "error": str(e),
                    "pct": round((i + 1) / total * 100),
                    "rate_status": rate_limiter.get_status()
                }) + "\n\n"

        for cid in chain_totals:
            chain_totals[cid]["usd_display"] = f"${chain_totals[cid]['usd']:,.2f}"
        chain_totals_sorted = dict(sorted(chain_totals.items(), key=lambda x: x[1]["usd"], reverse=True))

        yield "data: " + json.dumps({
            "type": "complete",
            "results": results,
            "grand_total": grand_total,
            "grand_total_display": f"${grand_total:,.2f}",
            "chain_totals": chain_totals_sorted,
            "rate_status": rate_limiter.get_status()
        }) + "\n\n"

    return Response(stream_with_context(generate()),
                    mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

if __name__ == "__main__":
    print("🚀 我的钱包管理 启动中...")
    print("📡 访问地址: http://127.0.0.1:5000")
    app.run(debug=False, host="0.0.0.0", port=5000)
