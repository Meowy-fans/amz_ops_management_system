import os
import time
import io
import json
import zipfile
from socketserver import ThreadingMixIn
from http.server import HTTPServer, BaseHTTPRequestHandler
import cgi
from pathlib import Path
import logging
import sys
import threading
import queue

# Global log queue for real-time streaming
log_queue = queue.Queue()

class QueueHandler(logging.Handler):
    """Custom logging handler to send logs to a queue"""
    def emit(self, record):
        try:
            msg = self.format(record)
            log_queue.put(msg)
        except Exception:
            self.handleError(record)

# Configure logging to use both stream and queue
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# Add queue handler to root logger
queue_handler = QueueHandler()
queue_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(queue_handler)

class MultiStream:
    """Redirects stream output to both original stream and queue"""
    def __init__(self, stream, queue):
        self.stream = stream
        self.queue = queue

    def write(self, message):
        self.stream.write(message)
        if message:
            self.queue.put(message)

    def flush(self):
        self.stream.flush()

# Ensure project root is in sys.path so we can import main
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def _run_task(task, category, file_path, auto_confirm):
    import importlib
    try:
        m = importlib.import_module("main")
        if hasattr(m, "run_task"):
            return m.run_task(task, category=category, file_path=file_path, auto_confirm=auto_confirm)
    except Exception as e:
        logger.error(f"Task execution failed: {e}", exc_info=True)
        raise e
    return None


def _readiness_snapshot():
    """Return a compact operational snapshot for the web console."""
    import importlib
    from sqlalchemy import text

    m = importlib.import_module("main")
    with m.SessionLocal() as db:
        counts = db.execute(text("""
            SELECT 'amazon_records' AS metric, count(*) FROM amz_all_listing_report
            UNION ALL SELECT 'giga_products', count(*) FROM giga_product_sync_records
            UNION ALL SELECT 'llm_details', count(*) FROM ds_api_product_details
            UNION ALL SELECT 'sku_mappings', count(*) FROM meow_sku_map
            UNION ALL SELECT 'base_prices', count(*) FROM giga_product_base_prices
            UNION ALL SELECT 'inventory_skus', count(*) FROM giga_inventory
            UNION ALL SELECT 'listing_logs', count(*) FROM amz_listing_log
            UNION ALL SELECT 'templates', count(*) FROM amazon_cat_templates
        """)).fetchall()

        pending_rows = db.execute(text("""
            SELECT
                upper(COALESCE(NULLIF(scm.standard_category_name, ''), 'UNMAPPED')) AS category,
                count(DISTINCT m.meow_sku) AS sku_count
            FROM meow_sku_map m
                LEFT JOIN amz_all_listing_report r ON m.meow_sku = r."seller-sku"
                JOIN giga_product_sync_records psr
                    ON m.vendor_sku = psr.giga_sku
                    AND m.vendor_source = 'giga'
                JOIN giga_product_base_prices pbp ON m.vendor_sku = pbp.giga_sku
                LEFT JOIN supplier_categories_map scm
                    ON LOWER(psr.category_code) = LOWER(scm.supplier_category_code)
                    AND scm.supplier_platform = 'giga'
            WHERE r."seller-sku" IS NULL
              AND psr.is_oversize IS NOT TRUE
              AND psr.raw_data -> 'sellerInfo' ->> 'sellerType' = 'GENERAL'
              AND pbp.sku_available IS TRUE
            GROUP BY upper(COALESCE(NULLIF(scm.standard_category_name, ''), 'UNMAPPED'))
            ORDER BY sku_count DESC, category
        """)).fetchall()

        supported_rows = db.execute(text("""
            WITH mapped AS (
                SELECT lower(NULLIF(standard_category_name, '')) AS category
                FROM supplier_categories_map
                WHERE NULLIF(standard_category_name, '') IS NOT NULL
            ),
            templated AS (
                SELECT lower(category) AS category FROM amazon_cat_templates
            )
            SELECT DISTINCT upper(mapped.category) AS category
            FROM mapped
                JOIN templated USING (category)
            ORDER BY upper(mapped.category)
        """)).fetchall()

        unmapped_rows = db.execute(text("""
            SELECT supplier_category_code, supplier_category_name
            FROM supplier_categories_map
            WHERE standard_category_name IS NULL OR btrim(standard_category_name) = ''
            ORDER BY supplier_category_code
        """)).fetchall()

    pending_by_category = {
        row.category.upper(): int(row.sku_count) for row in pending_rows
    }
    supported_categories = [row.category for row in supported_rows]
    return {
        "counts": {row.metric: int(row.count) for row in counts},
        "pending_by_category": pending_by_category,
        "supported_categories": supported_categories,
        "unmapped_categories": [
            {
                "code": row.supplier_category_code,
                "name": row.supplier_category_name,
            }
            for row in unmapped_rows
        ],
        "ready_for_listing": bool(supported_categories)
        and any(pending_by_category.get(cat, 0) > 0 for cat in supported_categories),
    }


INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <title>AMZ Listing Management System</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --primary: #2563eb;
            --primary-hover: #1d4ed8;
            --bg: #f8fafc;
            --card-bg: #ffffff;
            --text-main: #1e293b;
            --text-muted: #64748b;
            --border: #e2e8f0;
            --danger: #ef4444;
            --success: #22c55e;
            --warning: #f59e0b;
        }
        body {
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            background: var(--bg);
            color: var(--text-main);
            margin: 0;
            padding: 0;
            line-height: 1.5;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 40px 20px;
        }
        header {
            margin-bottom: 40px;
            text-align: center;
        }
        h1 {
            font-size: 2rem;
            font-weight: 700;
            color: var(--text-main);
            margin: 0 0 10px 0;
            letter-spacing: -0.025em;
        }
        .subtitle {
            color: var(--text-muted);
            font-size: 1.1rem;
        }
        
        /* Section Styling */
        .section {
            background: var(--card-bg);
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05), 0 1px 2px rgba(0,0,0,0.1);
            margin-bottom: 30px;
            overflow: hidden;
            border: 1px solid var(--border);
        }
        .section-header {
            padding: 20px 24px;
            border-bottom: 1px solid var(--border);
            background: #fafafa;
        }
        .section-title {
            font-size: 1.1rem;
            font-weight: 600;
            color: var(--text-main);
            margin: 0;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .overview-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 1px;
            background: var(--border);
        }
        .metric {
            background: var(--card-bg);
            padding: 16px 20px;
        }
        .metric-value {
            font-size: 1.35rem;
            font-weight: 700;
            color: var(--text-main);
        }
        .metric-label {
            color: var(--text-muted);
            font-size: 0.82rem;
            margin-top: 2px;
        }
        .status-strip {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            padding: 16px 20px;
            border-top: 1px solid var(--border);
            background: #fbfdff;
        }
        .pill {
            display: inline-flex;
            align-items: center;
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 4px 10px;
            font-size: 0.82rem;
            background: white;
            color: var(--text-main);
        }
        .pill.ready {
            border-color: #86efac;
            background: #f0fdf4;
            color: #166534;
        }
        .pill.warn {
            border-color: #fcd34d;
            background: #fffbeb;
            color: #92400e;
        }
        
        /* Task Grid */
        .task-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 1px;
            background: var(--border);
        }
        .task-card {
            background: var(--card-bg);
            padding: 20px;
            transition: all 0.2s;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .task-card:hover {
            background: #f8fafc;
        }
        .task-id {
            font-size: 0.85rem;
            font-weight: 600;
            color: var(--primary);
            margin-bottom: 8px;
            display: inline-block;
            background: #eff6ff;
            padding: 2px 8px;
            border-radius: 4px;
        }
        .task-name {
            font-weight: 500;
            margin-bottom: 16px;
            color: var(--text-main);
        }
        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 8px 16px;
            border-radius: 6px;
            font-weight: 500;
            font-size: 0.9rem;
            cursor: pointer;
            transition: all 0.2s;
            border: none;
            outline: none;
            width: 100%;
        }
        .btn-primary {
            background: var(--primary);
            color: white;
        }
        .btn-primary:hover {
            background: var(--primary-hover);
            transform: translateY(-1px);
        }
        .btn-secondary {
            background: white;
            border: 1px solid var(--border);
            color: var(--text-main);
        }
        .btn-secondary:hover {
            background: #f1f5f9;
        }
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            background: #e2e8f0;
            color: #94a3b8;
        }

        /* Modal */
        .modal-overlay {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.5);
            backdrop-filter: blur(4px);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 50;
            opacity: 0;
            transition: opacity 0.2s;
        }
        .modal-overlay.active {
            display: flex;
            opacity: 1;
        }
        .modal {
            background: var(--card-bg);
            border-radius: 12px;
            width: 100%;
            max-width: 500px;
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
            transform: scale(0.95);
            transition: transform 0.2s;
            padding: 24px;
        }
        .modal-overlay.active .modal {
            transform: scale(1);
        }
        .modal-title {
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 20px;
        }
        .log-container {
            background: #1e293b;
            color: #e2e8f0;
            padding: 12px;
            border-radius: 6px;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', 'Consolas', monospace;
            font-size: 0.85rem;
            height: 200px;
            overflow-y: auto;
            margin-bottom: 16px;
            white-space: pre-wrap;
            display: none;
            border: 1px solid #334155;
        }
        .log-line {
            margin: 2px 0;
            line-height: 1.4;
        }
        .form-group {
            margin-bottom: 16px;
        }
        .form-label {
            display: block;
            font-size: 0.9rem;
            font-weight: 500;
            margin-bottom: 6px;
            color: var(--text-main);
        }
        .form-input {
            width: 100%;
            padding: 10px;
            border: 1px solid var(--border);
            border-radius: 6px;
            font-size: 0.95rem;
            box-sizing: border-box;
            transition: border-color 0.2s;
        }
        .form-input:focus {
            border-color: var(--primary);
            outline: none;
            box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
        }
        select.form-input {
            background: white;
        }
        .checkbox-wrapper {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-top: 10px;
            cursor: pointer;
        }
        .checkbox-wrapper input {
            width: 16px;
            height: 16px;
        }
        .modal-actions {
            display: flex;
            gap: 12px;
            margin-top: 24px;
        }

        /* Toast */
        #toast {
            position: fixed;
            bottom: 24px;
            left: 50%;
            transform: translateX(-50%) translateY(20px);
            background: #1e293b;
            color: white;
            padding: 12px 24px;
            border-radius: 50px;
            font-weight: 500;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
            opacity: 0;
            pointer-events: none;
            transition: all 0.3s cubic-bezier(0.68, -0.55, 0.265, 1.55);
            z-index: 100;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        #toast.show {
            opacity: 1;
            transform: translateX(-50%) translateY(0);
        }
        
        /* Spinner */
        .spinner {
            width: 18px;
            height: 18px;
            border: 2px solid #ffffff;
            border-bottom-color: transparent;
            border-radius: 50%;
            display: inline-block;
            box-sizing: border-box;
            animation: rotation 1s linear infinite;
            margin-right: 8px;
            display: none;
        }
        @keyframes rotation {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .badge-new {
            background-color: var(--success);
            color: white;
            font-size: 0.7rem;
            padding: 2px 6px;
            border-radius: 4px;
            margin-left: 6px;
            vertical-align: middle;
        }
    </style>
</head>
<body>

<div class="container">
    <header>
        <h1>🚀 Amazon Listing Management</h1>
        <div class="subtitle">自动化运营管理系统</div>
    </header>

    <section class="section">
        <div class="section-header">
            <h2 class="section-title">生产就绪状态</h2>
        </div>
        <div id="readinessOverview" class="overview-grid">
            <div class="metric">
                <div class="metric-value">--</div>
                <div class="metric-label">加载中</div>
            </div>
        </div>
        <div id="readinessPills" class="status-strip"></div>
    </section>

    <div id="app">
        <!-- Generated Content -->
    </div>
    
    <div style="text-align: center; margin-top: 40px; color: var(--text-muted); font-size: 0.9rem;">
        <p>System Status: <span id="statusIndicator">Checking...</span></p>
    </div>
</div>

<!-- Modal -->
<div id="modal" class="modal-overlay">
    <div class="modal">
        <div id="modalTitle" class="modal-title"></div>
        
        <div id="logBox" class="log-container"></div>

        <div id="fileRow" class="form-group" style="display:none">
            <label id="fileHint" class="form-label">文件上传</label>
            <input type="file" id="fileInput" class="form-input">
        </div>
        
        <div id="categoryRow" class="form-group" style="display:none">
            <label class="form-label">品类 (Category)</label>
            <select id="categoryInput" class="form-input">
                <option value="CABINET">CABINET</option>
                <option value="HOME_MIRROR">HOME_MIRROR</option>
            </select>
        </div>
        
        <label class="checkbox-wrapper">
            <input type="checkbox" id="autoConfirm" value="true">
            <span>自动确认 (Auto Confirm)</span>
        </label>
        
        <div class="modal-actions">
            <button id="runBtn" class="btn btn-primary">
                <span class="spinner" id="runSpinner"></span>
                开始运行
            </button>
            <button id="cancelBtn" class="btn btn-secondary">取消</button>
        </div>
    </div>
</div>

<div id="toast"></div>

<script>
    // 任务定义
    let readiness = null;
    const tasks = [
        {
            group: "Giga 商品管理",
            items: [
                {id:'1.1', name:'同步全量 Giga 收藏商品详情', code:'sync-products'},
                {id:'1.2', name:'导入亚马逊全量 Listing 数据', code:'import-amz-report', file:true, fileHint:'上传 Amazon 报告 (.txt)'},
                {id:'1.3', name:'更新亚马逊父品发品状态', code:'update-listing-status'},
                {id:'1.4', name:'AI 生成商品详情 (自动映射 SKU)', code:'generate-details'},
                {id:'1.5', name:'同步 Giga 商品价格', code:'sync-prices'},
                {id:'1.6', name:'同步 Giga 商品库存', code:'sync-inventory'},
                {id:'1.7', name:'更新售价', code:'update-prices'},
                {id:'1.8', name:'生成亚马逊发品文件', code:'generate-listing', category:true}
            ]
        },
        {
            group: "数据查询",
            items: [
                {id:'2.1', name:'查看数据统计', code:'view-statistics'},
                {id:'2.2', name:'查看待发品统计', code:'pending-statistics'},
                {id:'2.3', name:'查看最近发品记录', code:'recent-listings'}
            ]
        },
        {
            group: "类目配置",
            items: [
                {id:'3.1', name:'列出所有可用品类', code:'list-categories'},
                {id:'3.2', name:'解析新的亚马逊类目模板', code:'template-update', file:true, fileHint:'上传模板 (.xlsm)', category:true},
                {id:'3.3', name:'从报错文件矫正模板规则', code:'template-correction', file:true, fileHint:'上传报错文件 (.xlsm)', category:true},
                {id:'3.4', name:'更新 Giga 维护品类', code:'sync-giga-categories'},
                {id:'3.5', name:'CSV 批量更新品类映射', code:'update-mappings-from-csv', file:true, fileHint:'上传 CSV'}
            ]
        },
        {
            group: "系统维护 & 日常",
            items: [
                {id:'4.1', name:'CSV 批量同步 SKU 映射', code:'sku-sync-from-csv', disabled:true},
                {id:'5.1', name:'一键生成价格与库存更新文件', code:'generate-update-file'}
            ]
        }
    ];

    // 渲染界面
    const app = document.getElementById('app');
    
    tasks.forEach(group => {
        const section = document.createElement('div');
        section.className = 'section';
        
        let gridHtml = '';
        group.items.forEach(item => {
            const disabledAttr = item.disabled ? 'disabled' : '';
            const btnText = item.disabled ? '暂不可用' : '运行任务';
            
            gridHtml += `
                <div class="task-card">
                    <div>
                        <div class="task-id">${item.id}</div>
                        <div class="task-name">${item.name}</div>
                    </div>
                    <button class="btn ${item.disabled ? '' : 'btn-primary'}" 
                            ${disabledAttr}
                            data-code="${item.code}" 
                            data-file="${item.file?'1':'0'}" 
                            data-category="${item.category?'1':'0'}"
                            onclick="openModal(this)">
                        ${btnText}
                    </button>
                </div>
            `;
        });
        
        section.innerHTML = `
            <div class="section-header">
                <h2 class="section-title">${group.group}</h2>
            </div>
            <div class="task-grid">
                ${gridHtml}
            </div>
        `;
        app.appendChild(section);
    });

    // 状态管理
    let currentTask = {};
    const modal = document.getElementById('modal');
    const modalTitle = document.getElementById('modalTitle');
    const fileRow = document.getElementById('fileRow');
    const categoryRow = document.getElementById('categoryRow');
    const fileInput = document.getElementById('fileInput');
    const categoryInput = document.getElementById('categoryInput');
    const autoConfirm = document.getElementById('autoConfirm');
    const runBtn = document.getElementById('runBtn');
    const runSpinner = document.getElementById('runSpinner');
    const logBox = document.getElementById('logBox');

    function renderReadiness(data) {
        readiness = data;
        const counts = data.counts || {};
        const pending = data.pending_by_category || {};
        const supported = data.supported_categories || [];
        const unmapped = data.unmapped_categories || [];
        const totalPending = Object.values(pending).reduce((sum, n) => sum + Number(n || 0), 0);
        const readyPending = supported.reduce((sum, cat) => sum + Number(pending[cat] || 0), 0);

        const metrics = [
            ['可发品 SKU', readyPending],
            ['待发品总数', totalPending],
            ['Giga 商品', counts.giga_products || 0],
            ['SKU 映射', counts.sku_mappings || 0],
            ['价格 SKU', counts.base_prices || 0],
            ['库存 SKU', counts.inventory_skus || 0],
            ['Listing 记录', counts.listing_logs || 0],
            ['模板记录', counts.templates || 0]
        ];

        document.getElementById('readinessOverview').innerHTML = metrics.map(([label, value]) => `
            <div class="metric">
                <div class="metric-value">${value}</div>
                <div class="metric-label">${label}</div>
            </div>
        `).join('');

        const categoryPills = supported.map(cat => `
            <span class="pill ready">${cat}: ${pending[cat] || 0}</span>
        `).join('');
        document.getElementById('readinessPills').innerHTML = `
            <span class="pill ${data.ready_for_listing ? 'ready' : 'warn'}">
                ${data.ready_for_listing ? '发品链路可用' : '暂无可发品类'}
            </span>
            ${categoryPills}
            <span class="pill warn">未映射类目: ${unmapped.length}</span>
        `;

        const options = supported.length ? supported : ['CABINET', 'HOME_MIRROR'];
        categoryInput.innerHTML = options.map(cat => `<option value="${cat}">${cat}</option>`).join('');
    }
    
    // 打开模态框
    window.openModal = (btn) => {
        const code = btn.dataset.code;
        const flatTasks = tasks.flatMap(g => g.items);
        const taskDef = flatTasks.find(t => t.code === code);
        
        if (!taskDef) return;
        
        currentTask = {
            code: code,
            file: btn.dataset.file === '1',
            category: btn.dataset.category === '1',
            fileHint: taskDef.fileHint || '选择文件'
        };
        
        modalTitle.textContent = taskDef.name;
        
        // Reset logs
        logBox.innerHTML = '';
        logBox.style.display = 'none';
        
        // Show inputs
        fileRow.style.display = currentTask.file ? 'block' : 'none';
        document.getElementById('fileHint').textContent = currentTask.fileHint;
        fileInput.value = '';
        
        categoryRow.style.display = currentTask.category ? 'block' : 'none';
        if (currentTask.category && readiness && readiness.supported_categories && readiness.supported_categories.length) {
            categoryInput.value = readiness.supported_categories[0];
        }
        
        autoConfirm.checked = false;
        // Show inputs wrapper
        document.querySelectorAll('.form-group, .checkbox-wrapper').forEach(el => el.style.display = '');
        // Hide inputs based on task config
        if (!currentTask.file) fileRow.style.display = 'none';
        if (!currentTask.category) categoryRow.style.display = 'none';
        
        modal.classList.add('active');
    };
    
    // 关闭模态框
    document.getElementById('cancelBtn').onclick = () => {
        if (runBtn.disabled) return; // Running
        modal.classList.remove('active');
    };
    
    // 点击背景关闭
    modal.onclick = (e) => {
        if (runBtn.disabled) return; // Running
        if (e.target === modal) modal.classList.remove('active');
    };

    // Poll logs
    async function pollLogs() {
        if (!runBtn.disabled) return;
        try {
            const res = await fetch('/logs');
            if (res.ok) {
                const logs = await res.json();
                if (logs && logs.length > 0) {
                    logs.forEach(msg => {
                        const div = document.createElement('div');
                        div.className = 'log-line';
                        div.textContent = msg;
                        logBox.appendChild(div);
                    });
                    logBox.scrollTop = logBox.scrollHeight;
                }
            }
        } catch (e) {
            console.error('Log polling error:', e);
        }
        if (runBtn.disabled) {
            setTimeout(pollLogs, 1000);
        }
    }

    // Toast 提示
    function showToast(msg, type = 'info') {
        const t = document.getElementById('toast');
        let icon = 'ℹ️';
        if (type === 'success') icon = '✅';
        if (type === 'error') icon = '❌';
        
        t.textContent = `${icon} ${msg}`;
        t.className = type; // Reset class
        t.classList.add('show');
        
        setTimeout(() => {
            t.classList.remove('show');
        }, 3000);
    }

    // 运行任务
    runBtn.onclick = async () => {
        if (currentTask.file && !fileInput.files[0]) {
            showToast('请先选择文件', 'error');
            return;
        }
        
        // UI Loading State
        runBtn.disabled = true;
        runSpinner.style.display = 'inline-block';
        logBox.style.display = 'block';
        logBox.innerHTML = '<div class="log-line">🚀 Task started...</div>';
        
        // Start polling logs
        pollLogs();
        
        try {
            const fd = new FormData();
            fd.append('task', currentTask.code);
            
            if (currentTask.category) {
                fd.append('category', categoryInput.value || '');
            }
            if (autoConfirm.checked) {
                fd.append('auto_confirm', 'true');
            }
            if (currentTask.file) {
                const f = fileInput.files[0];
                fd.append('file', f, f.name);
            }

            const res = await fetch('/run', {
                method: 'POST',
                body: fd
            });

            if (!res.ok) {
                const errText = await res.text();
                try {
                    const errJson = JSON.parse(errText);
                    throw new Error(errJson.message || 'Unknown error');
                } catch(e) {
                    throw new Error(errText.slice(0, 100) || 'Server error');
                }
            }

            const ct = res.headers.get('Content-Type') || '';
            const cd = res.headers.get('Content-Disposition') || '';

            // 处理文件下载
            if (ct.includes('application/zip') || ct.includes('application/octet-stream') || cd.includes('attachment')) {
                const blob = await res.blob();
                let filename = 'output.zip';
                const m = /filename="?([^";]+)"?/i.exec(cd);
                if (m) filename = m[1];
                
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                a.remove();
                URL.revokeObjectURL(a.href);
                
                showToast('任务完成，开始下载文件', 'success');
            } else {
                const text = await res.text();
                // 尝试解析JSON消息
                try {
                    const jsonRes = JSON.parse(text);
                    if (jsonRes.status === 'ok') {
                        showToast(jsonRes.message || '任务执行成功', 'success');
                    } else {
                        showToast(jsonRes.message || text.slice(0, 50), 'info');
                    }
                } catch {
                    showToast(text.slice(0, 50) + '...', 'info');
                }
            }
            
            modal.classList.remove('active');
            
        } catch (e) {
            console.error(e);
            showToast(e.message, 'error');
        } finally {
            runBtn.disabled = false;
            runSpinner.style.display = 'none';
        }
    };

    // 健康检查
    async function checkHealth() {
        const indicator = document.getElementById('statusIndicator');
        try {
            const res = await fetch('/diagnostics');
            if (res.ok) {
                indicator.textContent = '🟢 Online (DB Connected)';
                indicator.style.color = 'var(--success)';
            } else {
                indicator.textContent = '🔴 Offline';
                indicator.style.color = 'var(--danger)';
            }
        } catch (e) {
            indicator.textContent = '🔴 Connection Failed';
            indicator.style.color = 'var(--danger)';
        }
    }

    async function loadReadiness() {
        try {
            const res = await fetch('/api/readiness');
            if (res.ok) {
                renderReadiness(await res.json());
            }
        } catch (e) {
            console.error('Readiness error:', e);
        }
    }
    
    // 初始化检查
    checkHealth();
    loadReadiness();
</script>
</body>
</html>
"""

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""
    daemon_threads = True

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
            return
            
        if self.path == "/diagnostics":
            try:
                import importlib
                from sqlalchemy import text
                
                m = importlib.import_module("main")
                if hasattr(m, "SessionLocal"):
                    with m.SessionLocal() as db:
                        db.execute(text("SELECT 1"))
                msg = {"status": "ok", "db": "connected"}
                body = json.dumps(msg).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                logger.error(f"Diagnostics failed: {e}")
                body = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return

        if self.path == "/api/readiness":
            try:
                body = json.dumps(_readiness_snapshot()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                logger.error(f"Readiness snapshot failed: {e}", exc_info=True)
                body = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return

        if self.path == "/logs":
            logs = []
            while not log_queue.empty():
                try:
                    logs.append(log_queue.get_nowait())
                except queue.Empty:
                    break
            
            body = json.dumps(logs).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
            
        if self.path == "/" or self.path.startswith("/index"):
            data = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
            
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path != "/run":
            self.send_response(404)
            self.end_headers()
            return
            
        try:
            content_type = self.headers.get("Content-Type")
            # 增加对 POST 数据大小的限制检查（可选）
            
            form = cgi.FieldStorage(
                fp=self.rfile, 
                headers=self.headers, 
                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type}
            )
            
            task = form.getvalue("task")
            category = form.getvalue("category")
            auto_confirm_raw = form.getvalue("auto_confirm")
            auto_confirm = str(auto_confirm_raw).lower() in ("1", "true", "yes")
            upload_field = form["file"] if "file" in form else None
            
            if not task:
                self.send_error_json(400, "task is required")
                return

            # 处理文件上传
            start_ts = time.time()
            uploads_dir = Path("uploads")
            uploads_dir.mkdir(exist_ok=True)
            saved_path = None
            
            if upload_field is not None and upload_field.file:
                # 安全清理文件名
                safe_filename = Path(upload_field.filename or "upload.bin").name
                saved_path = uploads_dir / f"{int(start_ts)}_{safe_filename}"
                with open(saved_path, "wb") as f:
                    f.write(upload_field.file.read())
                    
            # 执行任务
            result = _run_task(task, category, str(saved_path) if saved_path else None, auto_confirm)
            
            # 检查是否有明确的 Excel 文件返回
            excel_path = None
            if isinstance(result, dict) and "excel_file" in result:
                excel_path = result.get("excel_file")
            
            if excel_path and os.path.exists(excel_path):
                self.send_file(excel_path)
                return
                
            # 检查 Output 目录是否有新生成的文件
            output_dir = Path("output")
            generated = []
            if output_dir.exists():
                for root, _, files in os.walk(output_dir):
                    for name in files:
                        p = Path(root) / name
                        try:
                            # 稍微放宽时间判断，防止文件系统时间微小差异
                            if p.stat().st_mtime >= (start_ts - 1.0):
                                generated.append(p)
                        except FileNotFoundError:
                            pass
            
            if generated:
                self.send_zip(generated, output_dir)
                return
                
            # 默认返回成功
            self.send_json({"status": "ok", "message": "Task completed successfully (no output file)."})
            
        except Exception as e:
            logger.error(f"Error handling POST /run: {e}", exc_info=True)
            self.send_error_json(500, str(e))

    def send_error_json(self, code, message):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "error", "message": message}).encode("utf-8"))

    def send_json(self, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path):
        try:
            p = Path(path)
            with open(p, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{p.name}"')
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            logger.error(f"Failed to send file: {e}")
            self.send_error_json(500, "Failed to send output file")

    def send_zip(self, files, root_dir):
        try:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for p in files:
                    z.write(p, arcname=str(p.relative_to(root_dir)))
            data = buf.getvalue()
            
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", "attachment; filename=output.zip")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            logger.error(f"Failed to create zip: {e}")
            self.send_error_json(500, "Failed to create output zip")

def run():
    # Redirect stdout to queue
    sys.stdout = MultiStream(sys.stdout, log_queue)

    port = int(os.getenv("PORT") or os.getenv("IO_SERVER_PORT", "8080"))
    host = os.getenv("IO_SERVER_HOST", "0.0.0.0")
    print(f"🚀 Starting IO Server on {host}:{port}...")
    try:
        import importlib

        m = importlib.import_module("main")
        from src.services.listing_issue_scheduler import start_listing_issue_scheduler

        if start_listing_issue_scheduler(m.SessionLocal):
            print("Amazon listing issue scheduler enabled.")
    except Exception as e:
        logger.error("Failed to start listing issue scheduler: %s", e, exc_info=True)
    server = ThreadedHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("Server stopped.")

if __name__ == "__main__":
    run()
