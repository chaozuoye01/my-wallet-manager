# 我的钱包管理

> 一个基于 OKX Wallet API 的 EVM 多地址资产管理工具，支持批量查询 12 条链的资产，本地运行，数据不上传。

![Python](https://img.shields.io/badge/Python-3.8+-blue)
![Flask](https://img.shields.io/badge/Flask-3.0+-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## ✨ 功能特性

- **多链支持**：ETH / ARB / BASE / zkSync / Linea / BNB / Polygon 等 12 条 EVM 链
- **批量管理**：支持一次导入数百个地址，兼容多种格式，自动去重
- **实时进度**：批量查询时 SSE 流式推送，每一笔查询状态实时可见
- **限速管理**：可视化控制请求频率，自动退避重试，防止 API 429 错误
- **本地存储**：所有数据保存在本地 JSON 文件，隐私安全
- **风险过滤**：自动过滤 OKX 标记的风险空投代币

---

## 🚀 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/你的用户名/my-wallet-manager.git
cd my-wallet-manager
```

### 2. 安装依赖

```bash
pip install flask requests

# Windows 用户如果 pip 报错：
py -m pip install flask requests
```

### 3. 启动

```bash
python3 app.py

# Windows：
py app.py
```

浏览器打开 **http://localhost:5000**

---

## 🔑 获取 OKX API Key

1. 访问 [web3.okx.com/build](https://web3.okx.com/build)
2. 注册/登录 → 创建项目
3. 获取：**API Key / Secret Key / Passphrase / Project ID**
4. 在应用右上角「⚙ API 配置」填入保存

> API Key 免费申请，无需充值。

---

## 📖 使用说明

### 批量导入地址

点击右上角「📥 批量导入」，支持三种格式混用：

```
0xAbCd...1234
0xAbCd...1234, 主钱包
0xAbCd...1234 撸毛钱包01
```

### 限速设置

OKX API 默认限制 **1 req/s**，点击顶部绿色徽章进入限速面板可调整：

- 请求间隔：0.2s ~ 5s（建议 ≥ 1s）
- 自动重试：最多 10 次，遇 429 自动退避

---

## 🌐 支持的链

| Chain ID | 链名 | Chain ID | 链名 |
|----------|------|----------|------|
| 1 | Ethereum | 8453 | Base |
| 56 | BNB Chain | 324 | zkSync Era |
| 137 | Polygon | 59144 | Linea |
| 42161 | Arbitrum | 250 | Fantom |
| 10 | Optimism | 25 | Cronos |
| 43114 | Avalanche | 100 | Gnosis |

---

## 📁 项目结构

```
my-wallet-manager/
├── app.py              # Flask 后端 + OKX API + 限速管理器
├── templates/
│   └── index.html      # 前端 UI
├── requirements.txt    # 依赖
├── wallets.json        # 钱包数据（自动生成，已加入 .gitignore）
├── api_config.json     # API 凭证（⚠️ 已加入 .gitignore，勿上传）
└── rate_config.json    # 限速配置（自动生成）
```

---

## ⚠️ 安全提示

`api_config.json` 包含你的 OKX API 凭证，**请勿提交到 GitHub**。

已在 `.gitignore` 中排除。

---

## 🛠️ 常见问题

**浏览器访问超时？**
用了 VPN 导致本地请求被拦截。解决：暂时关闭 VPN，或在代理「例外」中添加 `127.0.0.1;localhost`。

**API 返回 429？**
触发频率限制，进入限速面板将请求间隔调到 1.5s 或更大。

**pip 命令不存在？**
先安装 Python：[python.org/downloads](https://python.org/downloads)，安装时勾选 **Add Python to PATH**。

---

## 📄 License

MIT License — 自由使用、修改、分发。

---

## 🙏 致谢

- [OKX Wallet API](https://web3.okx.com/build) — 链上数据支持
- [Flask](https://flask.palletsprojects.com/) — Web 框架
