# AI 机会雷达（AI Opportunity Radar）

每天北京时间 08:00 自动采集十个公开信源，生成 24H 热点榜（10 条）
和本周机会榜（5 条）的中文情报网站。

- 技术栈：Python + FastAPI + Jinja2 + SQLite（单进程，无构建步骤）
- 定时：系统 cron，每天 08:00（北京时间）
- 大模型：默认关闭，零费用；可选接入 DeepSeek/硅基流动做中文翻译摘要
- 月预算：≤ ¥100（见 `docs/费用说明.md`）

## 快速开始（本机）

```bash
cd radar
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 初始化数据库（含十个信源）
python -c "from app import db; db.init_db()"

# 采集一次（约 1 分钟）
python scripts/collect.py
# 评分一次
python scripts/score.py

# 启动网站
uvicorn app.main:app --host 127.0.0.1 --port 8000
# 打开 http://127.0.0.1:8000
```

## 每日任务

```bash
# 手动跑一次完整每日任务（采集+评分）
python scripts/daily.py
# 生成今日日报文本（推送用）
python scripts/push_report.py
```

## 云服务器部署教程

目标：腾讯云轻量应用服务器（2核2G，约 ¥60/月，首年常有 ¥30/月左右的优惠），
预算 ¥100/月内。阿里云轻量应用服务器同理。

### 第 1 步：买服务器
1. 腾讯云官网搜"轻量应用服务器"，选 2核2G、系统 Ubuntu 22.04/24.04，地域选广州/上海（离你近）。
2. 买完记下公网 IP，控制台重置 root 密码（或设置密钥登录）。

### 第 2 步：连上服务器做基础配置
```bash
ssh root@你的服务器IP
# 设为北京时间（定时任务 08:00 靠它）
timedatectl set-timezone Asia/Shanghai
apt update && apt install -y python3-venv python3-pip nginx sqlite3
```

### 第 3 步：上传项目
```bash
# 在服务器上
mkdir -p /opt/radar && cd /opt/radar
# 方法A：用 scp 从你电脑上传（在你电脑上执行）：
#   scp -r radar/ root@你的服务器IP:/opt/radar/
# 方法B：先打包传上去再解压
```

### 第 4 步：安装依赖、初始化
```bash
cd /opt/radar
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -c "from app import db; db.init_db()"
cp .env.example .env   # 按需填写（默认全关闭即可运行）
```

### 第 5 步：先手动跑一次，确认有数据
```bash
.venv/bin/python scripts/daily.py
# 看到 "每日任务成功"，再打开网站确认有内容（下一步配好 nginx 后）
```

### 第 6 步：网站开机自启（systemd）
```bash
cp deploy/radar-web.service /etc/systemd/system/
# 把文件里的 /opt/radar 确认是你的实际路径
systemctl daemon-reload
systemctl enable --now radar-web
systemctl status radar-web   # 看到 active (running) 就是正常
```

### 第 7 步：nginx 反向代理（让外网能访问）
```bash
cat > /etc/nginx/sites-available/radar <<'EOF'
server {
    listen 80;
    server_name 你的服务器IP;   # 有域名就填域名
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
EOF
ln -s /etc/nginx/sites-available/radar /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
# 浏览器打开 http://你的服务器IP 应该能看到网站
```

### 第 8 步：每天 08:00 自动任务
```bash
crontab -e
# 粘贴 deploy/crontab.txt 里那一行（确认路径是 /opt/radar）
# 0 8 * * * /opt/radar/.venv/bin/python /opt/radar/scripts/daily.py >> /opt/radar/logs/cron.log 2>&1
```

### 第 9 步（可选）：Product Hunt Token
Product Hunt 官方 API 需要免费 Developer Token：
访问 https://www.producthunt.com/v2/oauth/applications 创建应用，
把 Token 填入 `/opt/radar/.env` 的 `PH_TOKEN=`，第二天采集自动生效。
不填则该信源自动跳过，不影响其他九个。

### 第 10 步（可选）：中文翻译
默认关闭（零费用）。想开的话：
1. 去 DeepSeek 开放平台申请 API key（platform.deepseek.com）。
2. 填入 `.env`：`LLM_ENABLED=true`、`LLM_API_KEY=你的key`。
3. 每天上限 60 次、每月 ¥20 预算，超了自动停。费用实测见状态页。

## 目录结构

```
radar/
  app/                 网站 + 采集器 + 评分 + 通知
    collectors/        十个信源采集器（每个信源一个文件）
    templates/         页面模板（主页/热点/机会/状态）
    static/            样式（手机+电脑自适应）
    db.py              数据库（SQLite，UTC 存储、北京时间展示）
    scoring.py         热度/机会/投资评分
    llm.py             可配置大模型接口（默认关闭）
    notify.py          邮件/Telegram 通知（默认关闭）
    main.py            FastAPI 路由
  scripts/
    collect.py         采集入口        scripts/score.py   评分入口
    daily.py           每日总入口（cron 调用它）
    push_report.py     日报推送（聊天/邮件/Telegram）
  deploy/              上线配置：crontab、systemd
  docs/                费用说明、测试报告、功能清单
  tests/               26 项自动化测试
  data/radar.db        数据库文件（首次运行自动创建）
  logs/                每日运行日志
```

## 常见问题

- **网站打不开**：`systemctl status radar-web` 看服务是否在跑；`curl 127.0.0.1:8000/healthz` 应返回 `{"ok":true}`。
- **定时任务没跑**：看 `logs/daily-YYYY-MM-DD.log`；确认服务器时区是 Asia/Shanghai（`timedatectl`）。
- **某信源失败**：正常，状态页会显示原因，其他信源不受影响；第二天自动重试。
- **想清空重来**：删掉 `data/radar.db`，重新跑 `db.init_db()` + `daily.py`。
