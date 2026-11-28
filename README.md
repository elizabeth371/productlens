# ProductLens · AI 产品分析助手

输入一个 Amazon 商品链接，自动完成：**商品信息整理 → 产品深度分析 → 短视频口播文案（中/英）→ AI 质量自检**。

> AI 工程师实习生笔试项目 · Flask + Qwen（OpenAI 兼容端点，可切 DeepSeek）+ 可插拔视觉模型

**线上体验**：<http://106.53.205.157/>

## 功能与流程

| 阶段 | 做了什么 | 实现要点 |
|---|---|---|
| 1. 抓取 | 拉取 Amazon 商品页 | 三级降级：直连 → 公共代理 → reader 服务；强制美元价格、注入美国收货地；剔除 p13n/sims 推荐位的串号价格 |
| 2. 信息提取 | 名称/品牌/品类/价格/评分/卖点/规格 | LLM JSON mode 结构化抽取；与图片理解**并行**执行 |
| 3. 产品分析 | 定位、人群、场景、痛点、卖点、视觉建议 | 结合图片洞察（可插拔视觉模型），不做纯参数罗列 |
| 4. 文案生成 | 中文口播（≤150 字）+ 5 秒钩子 + 英文版 | 结构模板 + 禁用词表 + 对照示例抑制 AI 腔；代码级字数硬约束 |
| 5. 质量自检 | 夸大/幻觉/字数/钩子/AI 味 五项检查 | 不合格自动重写；实测拦截并修正过无依据表述 |

架构上是**异步任务 + 前端轮询**：`POST /api/analyze` 立即返回任务 ID，流水线在后台线程执行，前端轮询 `GET /api/job/<id>` 拿分阶段进度。这样单次分析耗时 80–120 秒也不会触发任何平台的 HTTP 超时限制。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `LLM_API_KEY` | 是 | 任意 OpenAI 兼容端点的 key |
| `LLM_BASE_URL` | 是 | 例如百炼 `https://dashscope.aliyuncs.com/compatible-mode/v1`，DeepSeek 为 `https://api.deepseek.com` |
| `LLM_MODEL` | 否 | 默认 `qwen-plus` |
| `VL_MODEL` | 否 | 默认 `qwen3-vl-plus`；缺省复用 `LLM_*`，端点不支持视觉时自动跳过图片理解 |
| `JINA_API_KEY` | 否 | 提升抓取兜底通道稳定性 |

## 部署

### 方式 A：云服务器 + systemd（当前线上采用）

```bash
# 1. 装依赖
dnf install -y git python3-pip        # Debian/Ubuntu 用 apt-get install -y git python3-pip

# 2. 拉代码
git clone https://github.com/elizabeth371/productlens.git /opt/productlens
cd /opt/productlens
python3 -m pip install --break-system-packages -r requirements.txt

# 3. 写 systemd 服务（把 4 个环境变量换成你自己的）
cat > /etc/systemd/system/productlens.service <<'EOF'
[Unit]
Description=ProductLens AI product analyst
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/productlens
Environment="LLM_API_KEY=sk-xxx" "LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1" "LLM_MODEL=qwen-plus" "VL_MODEL=qwen3-vl-plus"
ExecStart=/usr/local/bin/gunicorn --bind 0.0.0.0:80 --workers 1 --threads 8 --timeout 600 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 4. 启动
systemctl daemon-reload && systemctl enable --now productlens
curl -s http://127.0.0.1/api/health    # 应返回 {"status":"ok",...}
```

云厂商安全组/防火墙需放行 **80** 端口。

### 方式 B：Docker

```bash
docker build -t productlens .
docker run -d --name productlens --restart always -p 80:7860 \
  -e LLM_API_KEY=sk-xxx \
  -e LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1 \
  -e LLM_MODEL=qwen-plus -e VL_MODEL=qwen3-vl-plus \
  productlens
```

容器内监听 7860（可用 `PORT` 覆盖），所以映射写成 `-p 80:7860`。

## 本地运行

```bash
pip install -r requirements.txt
cp .env.example .env   # 填入 LLM_API_KEY 等
python app.py          # http://127.0.0.1:5000
```

## 实测可用的测试链接

以下链接均通过完整流水线（真实抓取 + LLM 生成 + 质检）验证：

| 品类 | 链接 | 备注 |
|---|---|---|
| 智能音箱 | `https://www.amazon.com/dp/B09B8V1LZ3` | Echo Dot 5 |
| 高端耳机 | `https://www.amazon.com/dp/B0BDHWDR12` | AirPods Pro 2，质检修正过幻觉 |
| 露营椅 | `https://www.amazon.com/dp/B0CXT9RSGQ` | 完整 slug 格式 |
| 蓝牙音箱 | `https://www.amazon.com/dp/B07QK2SPP7` | JBL Flip 5，线上实测 76.5 秒 |
| 电子书阅读器 | `https://www.amazon.com/dp/B08KTZ8249` | 无买盒价页面，验证容错 |
| 美妆小商品 | `https://www.amazon.com/dp/B09BC4FCL2` | 廉价非电子品类 |
| URL 形态 | `https://www.amazon.com/gp/product/B0CXT9RSGQ` | `/gp/product/` 格式 |

批量回归测试：`python tests/batch_verify.py`（轻量抓取筛选）→ `python tests/batch_full.py`（完整流水线）。

> 笔试原文示例 `B0F6YQ96L5` 已在 Amazon 下架（真实 404），系统会正确提示"商品不存在"而不是报错。

## 目录结构

```
app.py          Flask 入口：异步任务管理 + 进度轮询 + 视图
scraper.py      抓取与解析：三级降级、价格/图片提取、URL 校验
llm.py          文本模型：信息抽取、产品分析、双语文案、质量自检
vision.py       视觉模型插槽：商品图理解（不可用则自动跳过）
config.py       环境变量与能力探测
templates/      前端页面
static/         样式与交互（轮询进度、图片灯箱）
tests/          批量回归脚本
```
