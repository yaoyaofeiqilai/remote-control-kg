const state = {
    bridge: null,
    bootstrap: null,
    shell: null,
    configItems: [],
    runtime: null,
    info: null,
    audioInfo: null,
    audioHealth: null,
    videoHealth: null,
    logCursor: 0,
    logLines: [],
    intervals: [],
    layoutSyncFrame: 0,
};

const STATUS_LABELS = {
    running: '运行中',
    starting: '启动中',
    stopped: '已停止',
    stopping: '停止中',
    restarting: '重启中',
    security_locked: '安全锁定',
    error: '异常',
    ok: '正常',
    fallback: '已回退',
    ready: '已就绪',
    idle: '空闲',
};

const CHOICE_LABELS = {
    auto: '自动',
    dxgi: 'DXGI',
    mss: 'MSS',
};

const SOURCE_LABELS = {
    file: '已保存',
    environment: '环境变量',
    default: '默认值',
};

const STREAM_LABELS = {
    shell: '壳层',
    stdout: '输出',
    stderr: '诊断',
    access: '访问',
};

function $(id) {
    return document.getElementById(id);
}

function setText(id, text) {
    const el = $(id);
    if (el) el.textContent = text;
}

function formatNumber(value, fallback = '--') {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return fallback;
    return String(value);
}

function formatScale(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '--';
    return `${Number(value).toFixed(2).replace(/\.00$/, '.0')}x`;
}

function formatStatusLabel(status) {
    return STATUS_LABELS[String(status || 'stopped')] || '未知';
}

function formatChoiceLabel(value) {
    return CHOICE_LABELS[String(value || '').toLowerCase()] || String(value || '--');
}

function formatConfigKeyLabel(key) {
    const items = state.configItems?.length ? state.configItems : state.bootstrap?.config_items || [];
    const match = items.find((item) => item.key === key);
    return match?.label || key;
}

function formatCaptureStatusText(captureMode) {
    const mode = formatChoiceLabel(captureMode?.mode || '--');
    const status = formatStatusLabel(captureMode?.status || 'stopped');
    const message = String(captureMode?.message || '').trim();
    return message ? `采集方式：${mode}，状态：${status}，说明：${message}` : `采集方式：${mode}，状态：${status}`;
}

function showToast(message, kind = '') {
    const stack = $('toast-stack');
    if (!stack) return;
    const toast = document.createElement('div');
    toast.className = `toast ${kind}`.trim();
    toast.textContent = message;
    stack.appendChild(toast);
    window.setTimeout(() => toast.remove(), 3200);
}

function syncPanelHeights() {
    const configPanel = document.querySelector('.config-panel');
    const logsPanel = document.querySelector('.logs-panel');
    if (!configPanel || !logsPanel) return;
    if (window.innerWidth <= 1220) {
        logsPanel.style.removeProperty('height');
        return;
    }
    const configHeight = Math.ceil(configPanel.getBoundingClientRect().height);
    if (configHeight > 0) {
        logsPanel.style.height = `${configHeight}px`;
    }
}

function schedulePanelSync() {
    if (state.layoutSyncFrame) return;
    state.layoutSyncFrame = window.requestAnimationFrame(() => {
        state.layoutSyncFrame = 0;
        syncPanelHeights();
    });
}

async function waitForBridge(timeoutMs = 8000) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
        if (window.pywebview && window.pywebview.api) return window.pywebview.api;
        await new Promise((resolve) => window.setTimeout(resolve, 120));
    }
    return null;
}

async function callBridge(method, ...args) {
    if (!state.bridge || typeof state.bridge[method] !== 'function') {
        throw new Error(`桥接方法不可用：${method}`);
    }
    return state.bridge[method](...args);
}

function serializeConfigForm() {
    const payload = {};
    for (const item of state.configItems || []) {
        const input = document.querySelector(`[data-config-key="${item.key}"]`);
        if (!input) continue;
        if (item.kind === 'bool') {
            payload[item.key] = !!input.checked;
        } else if (item.kind === 'int') {
            payload[item.key] = Number.parseInt(input.value || item.default, 10);
        } else if (item.kind === 'float') {
            payload[item.key] = Number.parseFloat(input.value || item.default);
        } else {
            payload[item.key] = input.value;
        }
    }
    return payload;
}

function hasConfigChanges() {
    const current = serializeConfigForm();
    for (const item of state.configItems || []) {
        const nextValue = current[item.key];
        const currentValue = item.value;
        if (item.kind === 'float') {
            if (Math.abs(Number(nextValue) - Number(currentValue)) > 0.0001) return true;
        } else if (String(nextValue) !== String(currentValue)) {
            return true;
        }
    }
    return false;
}

function renderConfigDirtyState() {
    const dirty = hasConfigChanges();
    setText('config-dirty-text', dirty ? '有未保存的改动，请记得保存。' : '当前没有未保存的改动。');
}

function renderConfig() {
    const container = $('config-sections');
    if (!container) return;
    container.innerHTML = '';

    const groups = new Map();
    for (const section of state.bootstrap.config_sections || []) {
        groups.set(section, []);
    }
    for (const item of state.configItems || []) {
        if (!groups.has(item.section)) groups.set(item.section, []);
        groups.get(item.section).push(item);
    }

    for (const [section, items] of groups.entries()) {
        const group = document.createElement('section');
        group.className = 'config-group';
        group.innerHTML = `
            <div class="config-group-head">
                <h3>${section}</h3>
                <span class="field-meta">共 ${items.length} 项</span>
            </div>
            <div class="config-group-grid"></div>
        `;
        const grid = group.querySelector('.config-group-grid');

        for (const item of items) {
            const card = document.createElement('article');
            card.className = 'field-card';
            const sourceClass = `source-${item.source}`;
            const sourceLabel = SOURCE_LABELS[item.source] || '默认值';
            const restartBadge = item.restart_required
                ? '<span class="field-badge restart">重启生效</span>'
                : '<span class="field-badge">立即生效</span>';

            let controlHtml = '';
            if (item.kind === 'bool') {
                controlHtml = `
                    <label class="config-toggle">
                        <span>${item.value ? '开启' : '关闭'}</span>
                        <input data-config-key="${item.key}" type="checkbox" ${item.value ? 'checked' : ''}>
                    </label>
                `;
            } else if (item.kind === 'choice') {
                const options = (item.choices || [])
                    .map((choice) => `<option value="${choice}" ${choice === item.value ? 'selected' : ''}>${formatChoiceLabel(choice)}</option>`)
                    .join('');
                controlHtml = `<select data-config-key="${item.key}" class="config-select">${options}</select>`;
            } else if (item.kind === 'int' || item.kind === 'float') {
                const step = item.step ?? (item.kind === 'float' ? 0.1 : 1);
                const min = item.minimum ?? '';
                const max = item.maximum ?? '';
                controlHtml = `<input data-config-key="${item.key}" class="config-input" type="number" value="${item.value}" step="${step}" min="${min}" max="${max}">`;
            } else {
                const placeholder = item.placeholder || '';
                controlHtml = `<input data-config-key="${item.key}" class="config-input" type="text" value="${item.value}" placeholder="${placeholder}">`;
            }

            card.innerHTML = `
                <div class="field-head">
                    <div>
                        <h4 class="field-title">${item.label}</h4>
                        <p class="field-description">${item.description}</p>
                    </div>
                    <div class="field-badges">
                        ${restartBadge}
                        <span class="field-badge ${sourceClass}">${sourceLabel}</span>
                    </div>
                </div>
                ${controlHtml}
            `;
            grid.appendChild(card);
        }

        container.appendChild(group);
    }

    container.querySelectorAll('[data-config-key]').forEach((input) => {
        input.addEventListener('input', renderConfigDirtyState);
        input.addEventListener('change', renderConfigDirtyState);
    });
    renderConfigDirtyState();
    schedulePanelSync();
}

function syncRuntimeLabels() {
    setText('runtime-quality-value', formatNumber($('runtime-quality')?.value));
    setText('runtime-fps-value', formatNumber($('runtime-fps')?.value));
    setText('runtime-scale-value', formatScale($('runtime-scale')?.value));
}

function updateRuntimeControlsFromData() {
    if (!state.runtime) return;
    const runtime = state.runtime;
    if ($('runtime-quality')) $('runtime-quality').value = Number(runtime.quality ?? 95);
    if ($('runtime-fps')) $('runtime-fps').value = Number(runtime.webrtc_fps ?? 45);
    if ($('runtime-scale')) $('runtime-scale').value = Number(runtime.webrtc_scale ?? 1);
    syncRuntimeLabels();
    document.querySelectorAll('[data-capture-mode]').forEach((button) => {
        button.classList.toggle('is-active', button.dataset.captureMode === runtime.capture_mode?.mode);
    });
}

function renderShellState() {
    const shell = state.shell;
    if (!shell) return;

    const pill = $('service-status-pill');
    if (pill) {
        pill.textContent = formatStatusLabel(shell.status);
        pill.className = `status-pill status-${String(shell.status || 'stopped')}`;
    }

    setText('service-status-text', shell.status_message || '正在等待服务状态。');
    setText('service-pid-text', shell.pid ? `进程 PID ${shell.pid}` : '进程 PID --');
    setText('service-exit-text', shell.last_exit_code === null || shell.last_exit_code === undefined ? '暂无退出码' : `最近退出码 ${shell.last_exit_code}`);
    setText('recovery-mode-text', shell.auto_restart ? '自动重启已开启' : '自动重启已关闭');
    setText('recovery-detail-text', `等待 ${formatNumber(shell.restart_delay_sec, '--')} 秒`);
    setText('security-lock-text', shell.security_locked ? '已锁定' : '正常');
    setText('security-lock-detail', shell.security_locked ? '需要手动恢复后才能再次启动。' : '尚未触发安全锁定');
    setText('local-url-text', shell.control_url_local || 'http://127.0.0.1:5000');
    setText('lan-url-text', shell.control_url_lan || 'http://127.0.0.1:5000');
    setText('config-path-text', shell.config_path || 'config/runtime.env');

    $('start-server-btn').textContent = shell.security_locked ? '恢复并启动' : '启动服务';
    $('stop-server-btn').disabled = !(shell.status === 'running' || shell.status === 'starting' || shell.status === 'restarting');
    $('restart-server-btn').disabled = !(shell.status === 'running' || shell.status === 'starting' || shell.status === 'restarting');
}

function renderTelemetry() {
    const info = state.info || {};
    const runtime = state.runtime || {};
    const audioHealth = state.audioHealth || {};
    const videoHealth = state.videoHealth || {};
    const audioInfo = state.audioInfo || {};

    setText('clients-metric', formatNumber(info.clients, '0'));
    const screen = info.screen_size ? `${info.screen_size.width} × ${info.screen_size.height}` : '屏幕尺寸 --';
    setText('screen-metric', screen);

    const videoUp = videoHealth.client_up ? '活跃' : state.shell?.server_ready ? '待命' : '离线';
    setText('video-metric', videoUp);
    setText('video-detail', `采集 FPS ${formatNumber(videoHealth.capture_fps ?? info.capture_fps, '--')}`);

    const audioUp = audioHealth.client_up ? '活跃' : audioInfo.enabled ? '已准备' : '已关闭';
    setText('audio-metric', audioUp);
    setText('audio-detail', `设备 ${audioInfo.status?.selected_device || audioInfo.device_name_hint || '--'}`);

    setText('pair-metric', runtime.pair_enabled ? '配对门禁已开启' : '配对门禁已关闭');
    setText('pair-detail', `剩余 ${formatNumber(runtime.pair_remaining_attempts, '--')} 次 / 已失败 ${formatNumber(runtime.pair_failed_attempts, '--')} 次`);

    setText('codec-metric', `${info.video_encoder_effective || '--'} / ${formatChoiceLabel(info.webrtc_capture_backend || '--')}`);
    setText('codec-detail', `当前采集 ${formatChoiceLabel(runtime.capture_mode?.mode || '--')} / 码率 ${formatNumber(runtime.webrtc_bitrate_kbps, '--')} kbps`);

    const decodeFps = videoHealth.client_stats?.frames_per_second;
    const delayMs = videoHealth.client_stats?.playout_delay_ms;
    setText('video-health-metric', `解码 ${formatNumber(decodeFps, '--')} FPS`);
    setText('video-health-detail', `播放延迟 ${formatNumber(delayMs, '--')} ms / 丢包 ${formatNumber(videoHealth.client_stats?.packets_lost, '--')}`);

    setText('capture-status-text', formatCaptureStatusText(runtime.capture_mode));
    const muteState = runtime.system_mute?.available ? (runtime.system_mute?.muted ? '已静音' : '有声音') : '暂不可用';
    setText('system-mute-text', `电脑静音状态：${muteState}`);

    const localAddress = String(state.shell?.control_url_local || 'http://127.0.0.1:5000').replace(/^https?:\/\//, '');
    const captureModeLabel = formatChoiceLabel(runtime.capture_mode?.mode || info.webrtc_capture_backend || '--');
    const pairModeLabel = runtime.pair_enabled ? '需配对' : '免配对';
    const audioDeviceLabel = audioInfo.status?.selected_device || audioInfo.device_name_hint || '--';
    const audioSummary = audioInfo.enabled
        ? (runtime.system_mute?.available && runtime.system_mute?.muted ? '电脑已静音' : '电脑有声音')
        : '声音已关闭';

    setText('runtime-summary-performance', `${formatNumber(runtime.quality ?? 95)} 画质 / ${formatNumber(runtime.webrtc_fps ?? 45)} FPS`);
    setText('runtime-summary-performance-detail', `缩放 ${formatScale(runtime.webrtc_scale ?? 1)} · 目标码率 ${formatNumber(runtime.webrtc_bitrate_kbps, '--')} kbps`);

    setText('runtime-summary-stream', `${info.video_encoder_effective || '--'} / ${captureModeLabel}`);
    setText('runtime-summary-stream-detail', `${videoUp} · 采集 FPS ${formatNumber(videoHealth.capture_fps ?? info.capture_fps, '--')}`);

    setText('runtime-summary-access', `${formatNumber(info.clients, '0')} 台在线 / ${pairModeLabel}`);
    setText('runtime-summary-access-detail', `本机 ${localAddress} · 剩余尝试 ${formatNumber(runtime.pair_remaining_attempts, '--')} 次`);

    setText('runtime-summary-audio', audioSummary);
    setText('runtime-summary-audio-detail', `${audioUp} · 设备 ${audioDeviceLabel}`);

    updateRuntimeControlsFromData();
}

function renderLogs(entries) {
    if (!entries || !entries.length) return;
    for (const entry of entries) {
        const tag = (STREAM_LABELS[entry.stream] || String(entry.stream || '日志')).padEnd(2, ' ');
        state.logLines.push(`[${entry.ts}] ${tag}  ${entry.text}`);
    }
    if (state.logLines.length > 360) {
        state.logLines = state.logLines.slice(-360);
    }
    const stream = $('logs-stream');
    if (!stream) return;
    const shouldStick = stream.scrollTop + stream.clientHeight >= stream.scrollHeight - 30;
    stream.textContent = state.logLines.join('\n');
    if (shouldStick) stream.scrollTop = stream.scrollHeight;
    setText('logs-status-text', `当前视图 ${state.logLines.length} 行，日志游标 ${state.logCursor}`);
}

async function fetchServerJson(path, { admin = false, method = 'GET', body = null } = {}) {
    const base = state.shell?.api_base_local || state.bootstrap?.server_base_local;
    if (!base) throw new Error('服务地址不可用');
    const headers = {};
    if (admin) headers['X-Admin-Token'] = state.bootstrap.admin_token;
    if (body) headers['Content-Type'] = 'application/json';
    const response = await fetch(`${base}${path}`, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined,
        cache: 'no-store',
    });
    if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `请求失败：${response.status}`);
    }
    return response.json();
}

async function refreshShell() {
    state.shell = await callBridge('get_shell_state');
    renderShellState();
}

async function refreshConfig() {
    const result = await callBridge('get_config');
    state.configItems = result.items || [];
    setText('config-path-text', result.config_path || 'config/runtime.env');
    renderConfig();
}

async function refreshLogs() {
    const result = await callBridge('get_recent_logs', state.logCursor);
    state.logCursor = Number(result.cursor || state.logCursor || 0);
    renderLogs(result.entries || []);
    schedulePanelSync();
}

async function refreshServerData() {
    if (!state.shell?.server_ready) return;
    const [info, audioInfo, audioHealth, videoHealth, runtime] = await Promise.all([
        fetchServerJson('/api/info'),
        fetchServerJson('/api/audio_info'),
        fetchServerJson('/api/audio_health'),
        fetchServerJson('/api/video_health'),
        fetchServerJson('/api/admin/runtime', { admin: true }),
    ]);
    state.info = info;
    state.audioInfo = audioInfo;
    state.audioHealth = audioHealth;
    state.videoHealth = videoHealth;
    state.runtime = runtime;
    renderTelemetry();
}

async function withAction(task, successMessage, failurePrefix) {
    try {
        const result = await task();
        if (successMessage) showToast(successMessage);
        return result;
    } catch (error) {
        showToast(`${failurePrefix}：${error.message || error}`, 'error');
        throw error;
    }
}

async function saveConfig() {
    const payload = serializeConfigForm();
    const result = await withAction(
        () => callBridge('save_config', payload),
        '默认配置已保存。',
        '保存配置失败'
    );
    state.configItems = result.items || state.configItems;
    renderConfig();
    if (result.hot_applied?.length) showToast(`已立即同步：${result.hot_applied.map(formatConfigKeyLabel).join('、')}`);
    if (result.hot_failed?.length) showToast(`以下项目未能立即同步：${result.hot_failed.map(formatConfigKeyLabel).join('、')}`, 'error');
}

async function applyRuntimeStream() {
    const payload = {
        quality: Number.parseInt($('runtime-quality').value, 10),
        webrtc_fps: Number.parseInt($('runtime-fps').value, 10),
        webrtc_scale: Number.parseFloat($('runtime-scale').value),
    };
    await withAction(
        () => fetchServerJson('/api/admin/runtime', { admin: true, method: 'POST', body: payload }),
        '实时参数已应用。',
        '应用实时参数失败'
    );
    await refreshServerData();
}

async function setCaptureMode(mode) {
    await withAction(
        () => fetchServerJson('/api/admin/runtime', { admin: true, method: 'POST', body: { capture_mode: mode } }),
        `采集方式已切换为 ${formatChoiceLabel(mode)}。`,
        '切换采集方式失败'
    );
    await refreshServerData();
}

async function toggleSystemMute() {
    const nextMuted = !(state.runtime?.system_mute?.muted);
    await withAction(
        () => fetchServerJson('/api/admin/runtime', { admin: true, method: 'POST', body: { system_mute: nextMuted } }),
        nextMuted ? '电脑已设为静音。' : '电脑已取消静音。',
        '切换静音失败'
    );
    await refreshServerData();
}

async function copyText(text, label) {
    try {
        await navigator.clipboard.writeText(text);
        showToast(`${label}已复制。`);
    } catch (error) {
        showToast(`复制失败：${error.message || error}`, 'error');
    }
}

function bindEvents() {
    $('runtime-quality')?.addEventListener('input', syncRuntimeLabels);
    $('runtime-fps')?.addEventListener('input', syncRuntimeLabels);
    $('runtime-scale')?.addEventListener('input', syncRuntimeLabels);

    $('start-server-btn')?.addEventListener('click', async () => {
        await withAction(() => callBridge('start_server'), '已发起启动请求。', '启动服务失败');
        await refreshShell();
        await refreshLogs();
        await refreshServerData().catch(() => {});
    });

    $('stop-server-btn')?.addEventListener('click', async () => {
        await withAction(() => callBridge('stop_server'), '已发起停止请求。', '停止服务失败');
        await refreshShell();
    });

    $('restart-server-btn')?.addEventListener('click', async () => {
        await withAction(() => callBridge('restart_server'), '已发起重启请求。', '重启服务失败');
        await refreshShell();
    });

    $('open-logs-btn')?.addEventListener('click', async () => {
        await withAction(() => callBridge('open_logs_dir'), '日志目录已打开。', '打开日志目录失败');
    });

    $('apply-stream-btn')?.addEventListener('click', applyRuntimeStream);
    $('system-mute-btn')?.addEventListener('click', toggleSystemMute);

    document.querySelectorAll('[data-capture-mode]').forEach((button) => {
        button.addEventListener('click', () => setCaptureMode(button.dataset.captureMode));
    });

    $('save-config-btn')?.addEventListener('click', saveConfig);
    $('reload-config-btn')?.addEventListener('click', () => {
        refreshConfig()
            .then(() => showToast('配置已重新读取。'))
            .catch((error) => showToast(`重新读取失败：${error.message || error}`, 'error'));
    });

    $('clear-log-view-btn')?.addEventListener('click', () => {
        state.logLines = [];
        $('logs-stream').textContent = '';
        setText('logs-status-text', '当前视图已清空，新的日志会继续追加。');
    });

    $('copy-local-url')?.addEventListener('click', () => copyText($('local-url-text').textContent, '本机地址'));
    $('copy-lan-url')?.addEventListener('click', () => copyText($('lan-url-text').textContent, '局域网地址'));
}

function startPolling() {
    state.intervals.push(window.setInterval(() => refreshShell().catch(() => {}), 1200));
    state.intervals.push(window.setInterval(() => refreshLogs().catch(() => {}), 1000));
    state.intervals.push(window.setInterval(() => refreshServerData().catch(() => {}), 1800));
}

async function boot() {
    state.bridge = await waitForBridge();
    if (!state.bridge) {
        $('bridge-warning')?.classList.remove('hidden');
        return;
    }

    state.bootstrap = await callBridge('get_bootstrap');
    state.configItems = state.bootstrap.config_items || [];
    state.shell = state.bootstrap.shell_state || null;

    renderShellState();
    renderConfig();
    bindEvents();
    syncRuntimeLabels();
    schedulePanelSync();

    await refreshLogs().catch(() => {});
    await refreshShell().catch(() => {});
    await refreshConfig().catch(() => {});
    await refreshServerData().catch(() => {});
    schedulePanelSync();
    startPolling();
}

window.addEventListener('beforeunload', () => {
    for (const timer of state.intervals) {
        window.clearInterval(timer);
    }
    if (state.layoutSyncFrame) {
        window.cancelAnimationFrame(state.layoutSyncFrame);
        state.layoutSyncFrame = 0;
    }
});

window.addEventListener('resize', schedulePanelSync);

window.addEventListener('DOMContentLoaded', () => {
    boot().catch((error) => {
        showToast(`初始化失败：${error.message || error}`, 'error');
    });
});
