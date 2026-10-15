# AI 机会雷达（AI Opportunity Radar）

每天北京时间 08:00 自动采集十个公开信源，生成 **24H 热点榜** 和 **本周机会榜** 的中文情报网站。零成本运行。

🌐 在线访问：https://zhengweilong2008-long.github.io/ai-opportunity-radar/

- 技术栈：Python 采集器 + SQLite + 静态站生成（Jinja2），GitHub Pages 托管
- 定时：cron，每天 08:00（北京时间）采集 → 评分 → 翻译 → 构建 → 自动推送
- 大模型：默认关闭，零费用；可选接入 DeepSeek/硅基流动做中文翻译摘要
- 费用：¥0/月（GitHub Pages 免费托管）

## 十个信源

| 信源 | 采集方式 |
|---|---|
| GitHub Trending | 社区 RSS 镜像 |
| Hacker News | 官方 Firebase API（topstories） |
| Product Hunt | 官方 GraphQL v2 |
| OpenAI News | RSS |
| Hugging Face Blog | RSS |
| TechCrunch | RSS |
| Reuters | Google News RSS 间接覆盖（已标注） |
| SEC EDGAR | 官方 8-K Atom |
| Google DeepMind | RSS |
| Google Trends | 官方 Trending Now RSS（US） |

## 快速开始（本机）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 初始化数据库（含十个信源）
python -c "from app import db; db.init_db()"

# 采集一次（约 1 分钟）
python scripts/collect.py
# 评分一次
python scripts/score.py
# 构建静态站到 site/
python scripts/build_static.py
# 本地预览
cd site && python3 -m http.server 8000
```

密钥（Product Hunt Token、大模型 Key）全部走环境变量/`.env`，参考 `.env.example`，默认全关闭即可运行。

## 每日流水线

```
scripts/daily_publish.sh
  collect.py   采集十个信源 → SQLite
  score.py     热度/机会评分
  translate.py 中文标题摘要
  export_json.py 导出 site-data.json
  build_static.py 生成静态站 → site/
  推送：site/ → gh-pages 分支（网站），data/site-data.json → main 分支（数据快照）
```

## 目录结构

```
  app/                 采集器 + 评分 + 数据库
    collectors/        十个信源采集器（每个信源一个文件）
  scripts/
    collect.py / score.py / translate.py   流水线步骤
    daily_publish.sh   每日总入口（cron 调用它）
    build_static.py    静态站生成
  site_templates/      页面模板（主页/热点/机会）
  data/                数据库与数据快照（.db 不提交）
  docs/                费用说明、测试报告、功能清单
  tests/               自动化测试
```

## 灵感来源

本项目的创意来自一位抖音博主分享的点子，代码与数据管线为独立实现。感谢所有开源信源提供方。

## License

MIT（见 `LICENSE`）
