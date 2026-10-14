"""静态网站构建：data/site-data.json -> site/*.html。

读取 JSON 数据，用 Jinja2 渲染 site_templates/ 下的 3 个页面，
输出到 site/ 目录（index.html / hot.html / opportunities.html），
并复制静态资源。GitHub Pages 直接托管 site/ 目录即可。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from jinja2 import Environment, FileSystemLoader  # noqa: E402

TEMPLATES_DIR = BASE / "site_templates"
DATA_JSON = BASE / "data" / "site-data.json"
OUT_DIR = BASE / "site"
STATIC_SRC = BASE / "app" / "static"

PAGES = [
    ("index.html", "home"),
    ("hot.html", "hot"),
    ("opportunities.html", "opportunities"),
]


def build(data_path: Path = DATA_JSON, out_dir: Path = OUT_DIR) -> list[str]:
    """构建静态站，返回生成的文件列表。"""
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    ctx = {
        "date": payload.get("date"),
        "generated_at": payload.get("generated_at", "")[:16].replace("T", " "),
        "hot": payload.get("hot", []),
        "opportunities": payload.get("opportunities", []),
        "stats": payload.get("stats", {}),
        "sources": payload.get("sources", []),
        "runs": payload.get("runs", []),
    }
    built = []
    for tpl_name, active in PAGES:
        tpl = env.get_template(tpl_name)
        # hot.html / opportunities.html 模板里用 items 变量
        page_ctx = dict(ctx, active=active)
        if tpl_name == "hot.html":
            page_ctx["items"] = ctx["hot"]
        elif tpl_name == "opportunities.html":
            page_ctx["items"] = ctx["opportunities"]
        html = tpl.render(**page_ctx)
        dest = out_dir / tpl_name
        dest.write_text(html, encoding="utf-8")
        built.append(str(dest))

    # 静态资源（样式表）
    static_dest = out_dir / "static"
    if STATIC_SRC.exists():
        shutil.rmtree(static_dest, ignore_errors=True)
        shutil.copytree(STATIC_SRC, static_dest)
        built.append(str(static_dest / "style.css"))
    return built


if __name__ == "__main__":
    files = build()
    print(f"静态站已生成到 {OUT_DIR}，共 {len(files)} 个文件")
    for f in files:
        print(" -", f)
