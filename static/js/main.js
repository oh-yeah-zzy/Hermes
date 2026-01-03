/**
 * Hermes API Gateway 前端脚本
 */

// 调试模式
const DEBUG = window.DEBUG || false;

/**
 * 通用 API 请求函数
 * @param {string} url - 请求 URL
 * @param {object} options - fetch 选项
 * @returns {Promise} 响应数据
 */
async function apiRequest(url, options = {}) {
    try {
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers,
            },
            ...options,
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: '请求失败' }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        // 处理 204 No Content
        if (response.status === 204) {
            return null;
        }

        return await response.json();
    } catch (error) {
        console.error('API 请求错误:', error);
        throw error;
    }
}

/**
 * 格式化日期时间
 * @param {string} dateString - ISO 日期字符串
 * @returns {string} 格式化后的日期时间
 */
function formatDateTime(dateString) {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
}

/**
 * 格式化数字
 * @param {number} num - 数字
 * @returns {string} 格式化后的数字
 */
function formatNumber(num) {
    if (num >= 1000000) {
        return (num / 1000000).toFixed(1) + 'M';
    }
    if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    }
    return num.toString();
}

/**
 * 显示提示消息
 * @param {string} message - 消息内容
 * @param {string} type - 消息类型 (success, error, warning)
 */
function showToast(message, type = 'success') {
    // 简单的 alert 实现，后续可以替换为更好看的 toast
    if (type === 'error') {
        alert('错误: ' + message);
    } else {
        alert(message);
    }
}

/**
 * 页面加载完成后执行
 */
document.addEventListener('DOMContentLoaded', () => {
    if (DEBUG) {
        console.log('Hermes 前端已加载 (调试模式)');
    }

    // 添加活动链接高亮
    const currentPath = window.location.pathname;
    document.querySelectorAll('.nav-links a').forEach(link => {
        if (link.getAttribute('href') === currentPath) {
            link.classList.add('active');
        }
    });
});

/**
 * 获取实时统计数据
 * @returns {Promise} 统计数据
 */
async function getStats() {
    return await apiRequest('/api/stats');
}

/**
 * 刷新统计数据并更新页面
 */
async function refreshStats() {
    try {
        const stats = await getStats();

        // 更新统计数值（如果页面上有对应元素）
        const elements = {
            'uptime': stats.uptime,
            'total_requests': formatNumber(stats.total_requests),
            'success_rate': stats.success_rate + '%',
            'route_count': stats.route_count,
        };

        for (const [key, value] of Object.entries(elements)) {
            const el = document.querySelector(`[data-stat="${key}"]`);
            if (el) {
                el.textContent = value;
            }
        }
    } catch (error) {
        console.error('刷新统计数据失败:', error);
    }
}
