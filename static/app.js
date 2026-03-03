/**
 * 杩滅▼鎺у埗瀹㈡埛绔?- 骞虫澘绔帶鍒剁晫闈?
 * 浼樺寲鐗堟湰锛氫綆寤惰繜銆佹棤閬尅UI
 */

// ============ 鍏ㄥ眬閰嶇疆 ============

const CONFIG = {
    mouseSensitivity: 3.0,
    deadzone: 0.2,
    maxStickDistance: 90,
    lowLatencyMode: true,  // 浣庡欢杩熸ā寮?
    touchThrottleMs: 8,    // 瑙︽懜鑺傛祦(绾?20Hz)
    gameMode: {
        cameraSensitivity: 100,
        pinchSensitivity: 0.25,  // 鍙屾寚缂╂斁鐏垫晱搴︼紙deltaDist -> 婊氳疆 dy锛?
        webrtcScale: 1.0,
        showCursorDot: true,     // 鏄惁鏄剧ず榧犳爣绾㈢偣
    }
};


const DEBUG_LOG_ENABLED = false;

function debugLog(...args) {
    if (DEBUG_LOG_ENABLED) {
        console.info(...args);
    }
}


// ============ 鐘舵€佺鐞?============
const state = {
    socket: null,
    connected: false,
    currentMode: 'touch', // touch, gamepad, keyboard
    screenWidth: 1920,
    screenHeight: 1080,
    lastMouseX: 0,
    lastMouseY: 0,
    isMouseDown: false,
    isRightMouseDown: false,
    lastTouchTime: 0,
    isTouching: false,
    virtualMouse: null,
    sticks: {
        left: { x: 0, y: 0, active: false, touchId: null },
        right: { x: 0, y: 0, active: false, touchId: null },
    },
    gamepadAltLocked: false,
    gamepadTabWheelActive: false,
    webrtc: {
        pc: null,
        using: false,
        starting: false,
        restartTimer: null,
        restartAttempts: 0,
        maxRestartAttempts: 6,
        lastFrameAt: 0,
        freezeWatchdogTimer: null,
        hasFrameCallback: false,
    },
    audio: {
        unlocked: false,
        hasTrack: false,
        lastError: '',
    },
    webrtcStats: {
        bitrateMbps: 0,
        audioKbps: 0,
        audioBytes: 0,
        audioLevel: 0,
        audioPacketsLost: 0,
        audioJitterMs: 0,
        audioLastBytes: 0,
        audioLastTs: 0,
        packetsLost: 0,
        framesDropped: 0,
        framesDecoded: 0,
        framesPerSecond: 0,
        decodeMs: 0,
        decodeTotalSec: 0,
        decodeTotalFrames: 0,
        jitterMs: 0,
        lastBytes: 0,
        lastTs: 0,
        timer: null,
    },
    physicalGamepad: {
        active: false,
        index: null,
        enabled: false,
        connected: false,
        serverAttached: false,
        pollTimer: null,
        missCount: 0,
        lastConnectAt: 0,
        lastSentAt: 0,
        lastPayloadKey: '',
    },
    keyboardVisible: false,
    videoFps: 0,
    videoFrameCount: 0,
    lastVideoFpsUpdate: Date.now(),
    fps: 0,
    frameCount: 0,
    lastFpsUpdate: Date.now(),
};

let fpsEmitTimer = null;
let lastSentFps = null;

function sendFpsSetting(value, immediate = false) {
    const v = parseInt(value, 10);
    if (!Number.isFinite(v)) return;
    const doSend = () => {
        if (lastSentFps === v) return;
        lastSentFps = v;
        emit('set_fps', { fps: v });
    };
    if (immediate) {
        if (fpsEmitTimer) {
            clearTimeout(fpsEmitTimer);
            fpsEmitTimer = null;
        }
        doSend();
        return;
    }
    if (fpsEmitTimer) clearTimeout(fpsEmitTimer);
    fpsEmitTimer = setTimeout(() => {
        fpsEmitTimer = null;
        doSend();
    }, 120);
}

function isGamepadPointerActive() {
    return state.gamepadAltLocked || state.gamepadTabWheelActive;
}

function getScreenElement() {
    const videoEl = document.getElementById('screen-video');
    if (videoEl && !videoEl.classList.contains('hidden')) return videoEl;
    return document.getElementById('screen');
}

function getAudioElement() {
    return document.getElementById('remote-audio');
}

function updateAudioUnlockButton() {
    const btn = document.getElementById('audio-unlock-btn');
    if (!btn) return;
    if (state.audio.unlocked || !state.audio.hasTrack) {
        btn.classList.add('hidden');
        return;
    }
    btn.classList.remove('hidden');
}

async function unlockRemoteAudio(reportError = true) {
    const audioEl = getAudioElement();
    if (!audioEl) return false;

    try {
        audioEl.muted = false;
        audioEl.volume = 1;
        await audioEl.play();
        state.audio.unlocked = true;
        state.audio.lastError = '';
        updateAudioUnlockButton();
        emit('audio_client_stats', {
            unlocked: true,
            playing: !audioEl.paused,
            error: '',
        });
        return true;
    } catch (err) {
        const msg = err && err.message ? err.message : String(err);
        state.audio.lastError = msg;
        if (reportError) {
            emit('audio_client_stats', {
                unlocked: false,
                playing: false,
                error: msg,
            });
        }
        updateAudioUnlockButton();
        return false;
    }
}

function attachRemoteAudioStream(stream) {
    const audioEl = getAudioElement();
    if (!audioEl || !stream) return;
    if (audioEl.srcObject !== stream) {
        audioEl.srcObject = stream;
    }
    state.audio.hasTrack = true;
    updateAudioUnlockButton();
    unlockRemoteAudio(false);
}

function socketOnce(eventName, timeoutMs = 8000) {
    return new Promise((resolve, reject) => {
        if (!state.socket) {
            reject(new Error('no_socket'));
            return;
        }
        let timer = null;
        const handler = (data) => {
            if (timer) clearTimeout(timer);
            state.socket.off(eventName, handler);
            resolve(data);
        };
        state.socket.on(eventName, handler);
        timer = setTimeout(() => {
            state.socket.off(eventName, handler);
            reject(new Error('timeout_' + eventName));
        }, timeoutMs);
    });
}

function clearWebRTCRestartTimer() {
    if (state.webrtc.restartTimer) {
        clearTimeout(state.webrtc.restartTimer);
        state.webrtc.restartTimer = null;
    }
}

function stopMJPEG() {
    const screenImg = document.getElementById('screen');
    if (!screenImg) return;
    // Force-close multipart MJPEG request when switching to WebRTC.
    if (screenImg.src) {
        screenImg.src = '';
    }
    screenImg.classList.add('hidden');
}

function startWebRTCFreezeWatchdog() {
    if (state.webrtc.freezeWatchdogTimer) return;
    state.webrtc.lastFrameAt = Date.now();
    state.webrtc.freezeWatchdogTimer = setInterval(() => {
        if (!state.webrtc.using || !state.webrtc.pc) return;
        const last = state.webrtc.lastFrameAt || 0;
        const stalledMs = Date.now() - last;
        if (stalledMs < 5000) return;
        scheduleWebRTCRestart('video_stalled', 1200);
    }, 2000);
}

function scheduleWebRTCRestart(reason, delayMs = 1200) {
    debugLog('[WebRTC] restart scheduled:', reason);
    stopWebRTC();
    stopMJPEG();

    if (!state.connected) return;
    if (state.webrtc.restartTimer) return;
    if (state.webrtc.restartAttempts >= state.webrtc.maxRestartAttempts) {
        debugLog('[WebRTC] restart capped');
        return;
    }

    state.webrtc.restartAttempts += 1;
    const nextDelay = Math.min(8000, Math.max(800, delayMs));
    state.webrtc.restartTimer = setTimeout(async () => {
        state.webrtc.restartTimer = null;
        if (!state.connected) return;
        if (state.webrtc.starting) {
            scheduleWebRTCRestart('start_busy', nextDelay);
            return;
        }
        try {
            await startWebRTC();
            state.webrtc.restartAttempts = 0;
        } catch (e) {
            scheduleWebRTCRestart('restart_failed', nextDelay * 2);
        }
    }, nextDelay);
}

function stopWebRTC() {
    if (state.webrtc.freezeWatchdogTimer) {
        clearInterval(state.webrtc.freezeWatchdogTimer);
        state.webrtc.freezeWatchdogTimer = null;
    }
    if (state.webrtcStats.timer) {
        clearInterval(state.webrtcStats.timer);
        state.webrtcStats.timer = null;
    }
    if (state.webrtc.pc) {
        try {
            state.webrtc.pc.close();
        } catch (e) {
        }
        state.webrtc.pc = null;
    }
    const audioEl = getAudioElement();
    if (audioEl) {
        try {
            audioEl.pause();
        } catch (e) {
        }
        audioEl.srcObject = null;
    }
    state.audio.hasTrack = false;
    state.webrtc.using = false;
    state.webrtc.hasFrameCallback = false;
    updateAudioUnlockButton();
}

function startWebRTCStats() {
    if (!state.webrtc.pc) return;
    if (state.webrtcStats.timer) return;
    if (typeof state.webrtc.pc.getStats !== 'function') return;

    state.webrtcStats.lastBytes = 0;
    state.webrtcStats.lastTs = 0;
    state.webrtcStats.audioLastBytes = 0;
    state.webrtcStats.audioLastTs = 0;
    state.webrtcStats.decodeTotalSec = 0;
    state.webrtcStats.decodeTotalFrames = 0;

    state.webrtcStats.timer = setInterval(async () => {
        if (!state.webrtc.using || !state.webrtc.pc) return;
        try {
            const stats = await state.webrtc.pc.getStats();
            let videoInbound = null;
            let audioInbound = null;
            stats.forEach((r) => {
                if (r.type === 'inbound-rtp' && r.kind === 'video') videoInbound = r;
                if (r.type === 'inbound-rtp' && r.kind === 'audio') audioInbound = r;
            });
            if (videoInbound) {
                const nowTs = videoInbound.timestamp || performance.now();
                const bytes = videoInbound.bytesReceived || 0;
                const prevDecoded = Number(state.webrtcStats.framesDecoded || 0);
                const decodedNow = Number(videoInbound.framesDecoded || 0);
                const fpsNow = Number(videoInbound.framesPerSecond || 0);
                const bytesAdvanced = bytes > state.webrtcStats.lastBytes;
                const hasDecodedCounter = typeof videoInbound.framesDecoded === 'number';
                let codecMime = '';
                let decoderImpl = '';
                let powerEfficient = false;
                if (videoInbound.codecId && typeof stats.get === 'function') {
                    const codecReport = stats.get(videoInbound.codecId);
                    if (codecReport) {
                        codecMime = codecReport.mimeType || codecReport.mime_type || '';
                    }
                }
                decoderImpl = videoInbound.decoderImplementation || '';
                powerEfficient = !!videoInbound.powerEfficientDecoder;
                if (decodedNow > prevDecoded || fpsNow > 0) {
                    state.webrtc.lastFrameAt = Date.now();
                } else if (!state.webrtc.hasFrameCallback && !hasDecodedCounter && bytesAdvanced) {
                    // Fallback for very old browsers that do not expose decode counters.
                    state.webrtc.lastFrameAt = Date.now();
                }
                if (state.webrtcStats.lastTs) {
                    const dt = (nowTs - state.webrtcStats.lastTs) / 1000;
                    const db = bytes - state.webrtcStats.lastBytes;
                    if (dt > 0) state.webrtcStats.bitrateMbps = (db * 8) / 1e6 / dt;
                }
                state.webrtcStats.lastTs = nowTs;
                state.webrtcStats.lastBytes = bytes;
                state.webrtcStats.packetsLost = videoInbound.packetsLost || 0;
                state.webrtcStats.framesDropped = videoInbound.framesDropped || 0;
                state.webrtcStats.framesDecoded = decodedNow;
                state.webrtcStats.framesPerSecond = fpsNow;
                state.webrtcStats.jitterMs = videoInbound.jitter ? videoInbound.jitter * 1000 : 0;
                const totalDecodeTime = Number(videoInbound.totalDecodeTime || 0);
                const totalDecoded = Number(videoInbound.framesDecoded || 0);
                if (
                    totalDecodeTime > 0 &&
                    totalDecoded > 0 &&
                    totalDecodeTime >= state.webrtcStats.decodeTotalSec &&
                    totalDecoded >= state.webrtcStats.decodeTotalFrames
                ) {
                    const dSec = totalDecodeTime - state.webrtcStats.decodeTotalSec;
                    const dFrames = totalDecoded - state.webrtcStats.decodeTotalFrames;
                    if (dFrames > 0) {
                        state.webrtcStats.decodeMs = (dSec * 1000) / dFrames;
                    }
                    state.webrtcStats.decodeTotalSec = totalDecodeTime;
                    state.webrtcStats.decodeTotalFrames = totalDecoded;
                }
                emit('video_client_stats', {
                    bytes_received: bytes,
                    packets_lost: state.webrtcStats.packetsLost,
                    frames_decoded: state.webrtcStats.framesDecoded,
                    frames_dropped: state.webrtcStats.framesDropped,
                    frames_per_second: state.webrtcStats.framesPerSecond,
                    decode_ms: state.webrtcStats.decodeMs || 0,
                    jitter_ms: state.webrtcStats.jitterMs,
                    codec: codecMime,
                    decoder_impl: decoderImpl,
                    power_efficient: powerEfficient,
                });
            }

            if (audioInbound) {
                const nowTs = audioInbound.timestamp || performance.now();
                const bytes = audioInbound.bytesReceived || 0;
                if (state.webrtcStats.audioLastTs) {
                    const dt = (nowTs - state.webrtcStats.audioLastTs) / 1000;
                    const db = bytes - state.webrtcStats.audioLastBytes;
                    if (dt > 0) state.webrtcStats.audioKbps = (db * 8) / 1000 / dt;
                }
                state.webrtcStats.audioLastTs = nowTs;
                state.webrtcStats.audioLastBytes = bytes;
                state.webrtcStats.audioBytes = bytes;
                state.webrtcStats.audioPacketsLost = audioInbound.packetsLost || 0;
                state.webrtcStats.audioJitterMs = audioInbound.jitter ? audioInbound.jitter * 1000 : 0;
                state.webrtcStats.audioLevel = audioInbound.audioLevel || 0;

                const audioEl = getAudioElement();
                emit('audio_client_stats', {
                    bytes_received: state.webrtcStats.audioBytes,
                    packets_lost: state.webrtcStats.audioPacketsLost,
                    jitter_ms: state.webrtcStats.audioJitterMs,
                    audio_level: state.webrtcStats.audioLevel,
                    playing: !!(audioEl && !audioEl.paused),
                    unlocked: !!state.audio.unlocked,
                    error: state.audio.lastError || '',
                });
            }
        } catch (e) {
        }
    }, 1000);
}

function startVideoFrameMonitor() {
    const videoEl = document.getElementById('screen-video');
    const supportsFrameCallback = !!(videoEl && typeof videoEl.requestVideoFrameCallback === 'function');
    state.webrtc.hasFrameCallback = supportsFrameCallback;
    if (!supportsFrameCallback) return;

    const onFrame = () => {
        state.videoFrameCount++;
        state.webrtc.lastFrameAt = Date.now();
        const now = Date.now();
        const elapsed = now - state.lastVideoFpsUpdate;
        if (elapsed >= 1000) {
            state.videoFps = Math.round((state.videoFrameCount * 1000) / elapsed);
            state.videoFrameCount = 0;
            state.lastVideoFpsUpdate = now;
        }
        if (state.webrtc.using) {
            videoEl.requestVideoFrameCallback(onFrame);
        }
    };

    state.videoFrameCount = 0;
    state.lastVideoFpsUpdate = Date.now();
    videoEl.requestVideoFrameCallback(onFrame);
}

async function startWebRTC() {
    if (!window.RTCPeerConnection || !state.socket) return false;
    if (state.webrtc.starting) return false;
    state.webrtc.starting = true;

    const videoEl = document.getElementById('screen-video');
    const screenImg = document.getElementById('screen');
    if (!videoEl || !screenImg) {
        state.webrtc.starting = false;
        return false;
    }

    try {
        clearWebRTCRestartTimer();
        stopMJPEG();
        stopWebRTC();

        const pc = new RTCPeerConnection({ iceServers: [] });
        state.webrtc.pc = pc;

        pc.addTransceiver('video', { direction: 'recvonly' });
        pc.addTransceiver('audio', { direction: 'recvonly' });

        pc.ontrack = (e) => {
            if (pc !== state.webrtc.pc) return;
            const stream = (e.streams && e.streams[0]) ? e.streams[0] : null;
            if (e.track && e.track.kind === 'audio') {
                const audioStream = stream || new MediaStream([e.track]);
                attachRemoteAudioStream(audioStream);
                return;
            }
            if (e.track && e.track.kind === 'video' && stream) {
                stopMJPEG();
                videoEl.srcObject = stream;
                videoEl.classList.remove('hidden');
                screenImg.classList.add('hidden');
                state.webrtc.using = true;
                state.webrtc.lastFrameAt = Date.now();
                state.webrtc.restartAttempts = 0;
                startVideoFrameMonitor();
                startWebRTCStats();
                startWebRTCFreezeWatchdog();
                if (e.track) {
                    e.track.onended = () => {
                        if (pc !== state.webrtc.pc) return;
                        scheduleWebRTCRestart('video_track_ended', 1200);
                    };
                }
            }
        };

        pc.onconnectionstatechange = () => {
            if (pc !== state.webrtc.pc) return;
            const s = pc.connectionState;
            if (s === 'failed' || s === 'closed' || s === 'disconnected') {
                scheduleWebRTCRestart('connection_' + s, 1200);
            }
        };

        pc.oniceconnectionstatechange = () => {
            if (pc !== state.webrtc.pc) return;
            const s = pc.iceConnectionState;
            if (s === 'failed' || s === 'closed' || s === 'disconnected') {
                scheduleWebRTCRestart('ice_' + s, 1200);
            }
        };

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        emit('webrtc_offer', { sdp: offer.sdp, type: offer.type });

        const answer = await socketOnce('webrtc_answer', 12000);
        if (!answer || !answer.sdp) throw new Error('bad_answer');
        await pc.setRemoteDescription(answer);
        return true;
    } finally {
        state.webrtc.starting = false;
    }
}

async function startVideoTransport() {
    try {
        await startWebRTC();
    } catch (e) {
        scheduleWebRTCRestart('startup_failed', 1200);
    }
}


function initAudioUnlockControls() {
    const unlockBtn = document.getElementById('audio-unlock-btn');
    if (unlockBtn) {
        unlockBtn.addEventListener('click', async () => {
            await unlockRemoteAudio(true);
        });
    }

    document.addEventListener('pointerdown', () => {
        if (state.audio.hasTrack && !state.audio.unlocked) {
            unlockRemoteAudio(false);
        }
    }, { passive: true });

    updateAudioUnlockButton();
}
// ============ Socket.IO 连接 ============
function initSocket() {
    const statusEl = document.getElementById('connection-status');
    statusEl.textContent = '连接中...';
    statusEl.className = 'connecting';

    state.socket = io({
        transports: ['websocket', 'polling'],
        reconnection: true,
        reconnectionAttempts: 10,
        reconnectionDelay: 1000,
    });

    state.socket.on('connect', () => {
        debugLog('[Socket] connected');
        state.connected = true;
        statusEl.textContent = '已连接';
        statusEl.className = 'connected';
        if (state.currentMode === 'controller' &&
            state.physicalGamepad &&
            typeof state.physicalGamepad.setEnabled === 'function') {
            state.physicalGamepad.setEnabled(true);
        }
    });

    state.socket.on('disconnect', () => {
        debugLog('[Socket] disconnected');
        state.connected = false;
        clearWebRTCRestartTimer();
        state.webrtc.restartAttempts = 0;
        if (state.physicalGamepad) {
            state.physicalGamepad.serverAttached = false;
            state.physicalGamepad.connected = false;
        }
        statusEl.textContent = '已断开';
        statusEl.className = 'disconnected';
        stopWebRTC();
    });

    state.socket.on('connect_error', (err) => {
        console.error('[Socket] connect error:', err);
        statusEl.textContent = '连接失败';
        statusEl.className = 'disconnected';
    });

    state.socket.on('connected', (data) => {
        state.screenWidth = data.screen_width;
        state.screenHeight = data.screen_height;
        debugLog('[Socket] screen size:', state.screenWidth, 'x', state.screenHeight);

        // 初始化虚拟鼠标位置到屏幕中心
        if (!state.virtualMouse) {
            state.virtualMouse = { x: state.screenWidth / 2, y: state.screenHeight / 2 };
        }

        // 启动鼠标位置同步
        startMouseSync();

        const qualitySlider = document.getElementById('quality-slider');
        if (qualitySlider) {
            emit('set_quality', { quality: parseInt(qualitySlider.value) });
        }
        const fpsSlider = document.getElementById('fps-slider');
        if (fpsSlider) {
            sendFpsSetting(fpsSlider.value, true);
        }
        const webrtcScaleSlider = document.getElementById('webrtc-scale-slider');
        if (webrtcScaleSlider) {
            emit('set_webrtc_scale', { scale: parseFloat(webrtcScaleSlider.value) });
        }

        startVideoTransport();
    });

    state.socket.on('fps_updated', (data) => {
        if (!data) return;
        const maxFps = parseInt(data.webrtc_fps_max ?? 120, 10);
        const v = parseInt(data.webrtc_fps ?? data.fps ?? 60, 10);
        if (!Number.isFinite(v)) return;
        const fpsSlider = document.getElementById('fps-slider');
        const fpsValue = document.getElementById('fps-value');
        if (fpsSlider) {
            if (Number.isFinite(maxFps) && maxFps >= 30) {
                fpsSlider.max = String(maxFps);
            }
            fpsSlider.value = String(v);
        }
        lastSentFps = v;
        if (fpsValue) fpsValue.textContent = String(v);
    });

    state.socket.on('quality_updated', (data) => {
        if (!data) return;
        const v = parseInt(data.quality ?? 80, 10);
        if (!Number.isFinite(v)) return;
        const qualitySlider = document.getElementById('quality-slider');
        const qualityValue = document.getElementById('quality-value');
        if (qualitySlider) qualitySlider.value = String(v);
        if (qualityValue) qualityValue.textContent = String(v);
    });

    state.socket.on('webrtc_scale_updated', (data) => {
        if (!data) return;
        const v = parseFloat(data.scale ?? 1.0);
        if (!Number.isFinite(v)) return;
        const webrtcScaleSlider = document.getElementById('webrtc-scale-slider');
        const webrtcScaleValue = document.getElementById('webrtc-scale-value');
        if (webrtcScaleSlider) webrtcScaleSlider.value = String(v);
        if (webrtcScaleValue) webrtcScaleValue.textContent = v.toFixed(1) + 'x';
    });

    // Sync virtual cursor with server mouse position.
    state.socket.on('mouse_pos', (data) => {
        if (!state.virtualMouse) return;

        // Keep local cursor stable while touching; only warn on large drift.
        if (state.isTouching) {
            const dx = Math.abs(state.virtualMouse.x - data.x);
            const dy = Math.abs(state.virtualMouse.y - data.y);
            if (dx > 200 || dy > 200) {
                debugLog(`[警告] 触摸时位置偏差过大 (${dx.toFixed(0)}, ${dy.toFixed(0)})`);
            }
        } else {
            state.virtualMouse.x = data.x;
            state.virtualMouse.y = data.y;
            updateVirtualCursorDisplay();
        }
    });

    state.socket.on('webrtc_error', () => {
        scheduleWebRTCRestart('server_webrtc_error', 1500);
    });
}

// 定时同步鼠标位置
let mouseSyncInterval = null;

function startMouseSync() {
    if (mouseSyncInterval) return;
    const intervalMs = CONFIG.lowLatencyMode ? 50 : 90;
    mouseSyncInterval = setInterval(() => {
        if (state.connected && !state.isTouching) {
            emit('get_mouse_pos');
        }
    }, intervalMs);
}

function stopMouseSync() {
    if (mouseSyncInterval) {
        clearInterval(mouseSyncInterval);
        mouseSyncInterval = null;
    }
}

function applyLowLatencyMode(enabled) {
    CONFIG.lowLatencyMode = !!enabled;
    CONFIG.touchThrottleMs = CONFIG.lowLatencyMode ? 8 : 16;
    if (state.connected) {
        stopMouseSync();
        startMouseSync();
    }
}

// 鏇存柊铏氭嫙鎸囬拡鏄剧ず浣嶇疆
function updateVirtualCursorDisplay() {
    const virtualCursor = document.getElementById('virtual-cursor');
    if (!virtualCursor || !state.virtualMouse) return;

    if (state.currentMode === 'controller') {
        virtualCursor.classList.add('hidden');
        return;
    }

    // 娓告垙妯″紡涓嬫牴鎹缃喅瀹氭槸鍚︽樉绀虹孩鐐?
    if (state.currentMode === 'gamepad' && !isGamepadPointerActive() && !CONFIG.gameMode.showCursorDot) {
        virtualCursor.classList.add('hidden');
        return;
    }

    const screenEl = getScreenElement();
    const rect = screenEl.getBoundingClientRect();

    // 璁＄畻缂╂斁姣斾緥
    const scaleX = rect.width / state.screenWidth;
    const scaleY = rect.height / state.screenHeight;

    // 璁＄畻鏄剧ず浣嶇疆
    const displayX = rect.left + state.virtualMouse.x * scaleX;
    const displayY = rect.top + state.virtualMouse.y * scaleY;

    virtualCursor.style.left = displayX + 'px';
    virtualCursor.style.top = displayY + 'px';
    virtualCursor.classList.remove('hidden');
}

// ============ 瑙︽懜鍧愭爣杞崲 ============
function getRelativeCoordinates(touch, element) {
    const rect = element.getBoundingClientRect();
    const img = document.getElementById('screen');
    // 浣跨敤瀹為檯鏄剧ず灏哄璁＄畻姣斾緥
    const scaleX = state.screenWidth / rect.width;
    const scaleY = state.screenHeight / rect.height;

    return {
        x: Math.round((touch.clientX - rect.left) * scaleX),
        y: Math.round((touch.clientY - rect.top) * scaleY),
    };
}

// 鑺傛祦鍑芥暟
function throttle(func, limit) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

// ============ 瑙︽懜鏉挎ā寮忔帶鍒?============
// 瀵规爣绗旇鏈Е鎺ф澘閫昏緫锛?
// - 鍗曟寚绉诲姩 = 榧犳爣绉诲姩锛堜笉瑙﹀彂鐐瑰嚮锛?
// - 鍗曟寚鐐瑰嚮 = 宸﹂敭鍗曞嚮锛堝欢杩熺‘璁わ紝閬垮厤涓庡弻鍑诲啿绐侊級
// - 鍙屽嚮骞舵寜浣忥紙绗簩娆＄偣鍑讳笉閲婃斁锛? 绉诲姩 = 鎷栨嫿锛堝彲鎷栧姩绐楀彛锛?
// - 鍙屾寚鐐瑰嚮 = 鍙抽敭
// - 鍙屾寚婊戝姩 = 婊氳疆锛堜笂涓嬪乏鍙冲洓鍚戯級
function initTouchMode() {
    const overlay = document.getElementById('touch-overlay');
    const virtualCursor = document.getElementById('virtual-cursor');

    // 瑙︽懜鏉跨姸鎬?
    let touchState = {
        touchCount: 0,
        startX: 0,
        startY: 0,
        lastX: 0,
        lastY: 0,
        startTime: 0,
        isMoving: false,
        hasMoved: false,
        isDragging: false,      // 鏄惁姝ｅ湪鎷栨嫿锛堝弻鍑诲苟鎸変綇锛?
        leftButtonDown: false,  // 宸﹂敭鏄惁鎸変笅
        isSecondTap: false,     // 鏄惁鏄弻鍑讳腑鐨勭浜屾鐐瑰嚮
        pendingClick: false,    // 鏄惁鏈夊緟纭鐨勫崟鍑?
    };

    // 鍙屽嚮妫€娴?
    let lastTapTime = 0;
    let lastTapX = 0;
    let lastTapY = 0;
    let clickTimer = null;    // 鐢ㄤ簬寤惰繜鎵ц鍗曞嚮

    // 甯搁噺
    const DOUBLE_TAP_TIME = 800;      // 鍙屽嚮鏃堕棿绐楀彛锛堟绉掞級
    const DOUBLE_TAP_DISTANCE = 100;  // 鍙屽嚮鏈€澶ц窛绂伙紙鍍忕礌锛?
    const CLICK_DELAY = 200;          // 鍗曞嚮寤惰繜鏃堕棿锛堢瓑寰呯‘璁や笉鏄弻鍑伙級
    const TWO_FINGER_TAP_MOVE_THRESHOLD = 10; // 鍙屾寚杞昏Е鍏佽鐨勬姈鍔ㄨ寖鍥达紙鍍忕礌锛?
    const TWO_FINGER_SCROLL_DEADZONE = 2;     // 鍙屾寚婊氳疆鏈€灏忚Е鍙戜綅绉伙紙鍍忕礌锛?
    const TWO_FINGER_TAP_MAX_DURATION = 420;  // 鍙屾寚杞昏Е鏈€澶ф椂闀匡紙姣锛?

    // 鑾峰彇鐏垫晱搴﹂厤缃?
    function getSensitivity() {
        return CONFIG.mouseSensitivity || 1.5;
    }

    // 纭繚铏氭嫙榧犳爣宸插垵濮嬪寲
    if (!state.virtualMouse) {
        state.virtualMouse = {
            x: state.screenWidth / 2,
            y: state.screenHeight / 2,
        };
    }

    // 鍋忓樊闃堝€?- 瓒呰繃姝ゅ€兼椂杩涜鏍″噯
    const POS_SYNC_THRESHOLD = 100;

    // 娓告垙妯″紡涓嬶細鍏ㄥ睆婊戝姩 = 瑙嗚锛汚lt 閿佸畾鏃舵粦鍔?= 鍏夋爣
    let gamepadSwipeState = {
        mode: null,
        touchId: null,
        startX: 0,
        startY: 0,
        lastX: 0,
        lastY: 0,
        moved: false,
        startTime: 0,
        lastSendTime: 0,
        pinchId1: null,
        pinchId2: null,
        lastPinchDistance: 0,
    };

    function gamepadSwipeStart(e) {
        if (gamepadSwipeState.mode === 'swipe' && e.touches.length === 2 && !isGamepadPointerActive()) {
            const t1 = e.touches[0];
            const t2 = e.touches[1];
            gamepadSwipeState.mode = 'pinch';
            gamepadSwipeState.pinchId1 = t1.identifier;
            gamepadSwipeState.pinchId2 = t2.identifier;
            gamepadSwipeState.touchId = null;
            gamepadSwipeState.moved = true;
            const dx = t1.clientX - t2.clientX;
            const dy = t1.clientY - t2.clientY;
            gamepadSwipeState.lastPinchDistance = Math.sqrt(dx * dx + dy * dy);
            return;
        }

        if (gamepadSwipeState.mode !== null) return;

        gamepadSwipeState.startTime = Date.now();
        state.isTouching = true;

        if (!state.virtualMouse) {
            state.virtualMouse = {
                x: state.screenWidth / 2,
                y: state.screenHeight / 2,
            };
        }

        if (e.touches.length === 1) {
            const touch = e.touches[0];
            gamepadSwipeState.mode = 'swipe';
            gamepadSwipeState.touchId = touch.identifier;
            gamepadSwipeState.startX = touch.clientX;
            gamepadSwipeState.startY = touch.clientY;
            gamepadSwipeState.lastX = touch.clientX;
            gamepadSwipeState.lastY = touch.clientY;
            gamepadSwipeState.moved = false;
            gamepadSwipeState.lastSendTime = 0;

            if (isGamepadPointerActive()) {
                updateVirtualCursorDisplay();
            }
        } else if (e.touches.length === 2) {
            const t1 = e.touches[0];
            const t2 = e.touches[1];
            gamepadSwipeState.mode = 'pinch';
            gamepadSwipeState.pinchId1 = t1.identifier;
            gamepadSwipeState.pinchId2 = t2.identifier;
            const dx = t1.clientX - t2.clientX;
            const dy = t1.clientY - t2.clientY;
            gamepadSwipeState.lastPinchDistance = Math.sqrt(dx * dx + dy * dy);
        }
    }

    function gamepadSwipeMove(e) {
        if (gamepadSwipeState.mode === null) return;

        const now = Date.now();
        const dt = now - gamepadSwipeState.lastSendTime;
        if (dt < CONFIG.touchThrottleMs) {
            if (gamepadSwipeState.mode === 'swipe' && gamepadSwipeState.touchId !== null) {
                const touch = Array.from(e.touches).find(t => t.identifier === gamepadSwipeState.touchId);
                if (touch) {
                    gamepadSwipeState.lastX = touch.clientX;
                    gamepadSwipeState.lastY = touch.clientY;
                }
            } else if (gamepadSwipeState.mode === 'pinch' && gamepadSwipeState.pinchId1 !== null && gamepadSwipeState.pinchId2 !== null) {
                const t1 = Array.from(e.touches).find(t => t.identifier === gamepadSwipeState.pinchId1);
                const t2 = Array.from(e.touches).find(t => t.identifier === gamepadSwipeState.pinchId2);
                if (t1 && t2) {
                    const dx = t1.clientX - t2.clientX;
                    const dy = t1.clientY - t2.clientY;
                    gamepadSwipeState.lastPinchDistance = Math.sqrt(dx * dx + dy * dy);
                }
            }
            return;
        }
        gamepadSwipeState.lastSendTime = now;

        if (gamepadSwipeState.mode === 'pinch') {
            const t1 = Array.from(e.touches).find(t => t.identifier === gamepadSwipeState.pinchId1);
            const t2 = Array.from(e.touches).find(t => t.identifier === gamepadSwipeState.pinchId2);
            if (!t1 || !t2) return;

            const dx = t1.clientX - t2.clientX;
            const dy = t1.clientY - t2.clientY;
            const dist = Math.sqrt(dx * dx + dy * dy);
            const deltaDist = dist - gamepadSwipeState.lastPinchDistance;
            gamepadSwipeState.lastPinchDistance = dist;

            if (!isGamepadPointerActive()) {
                const zoom = Math.max(-80, Math.min(80, Math.round(deltaDist * CONFIG.gameMode.pinchSensitivity)));
                if (zoom !== 0) {
                    emit('mouse_scroll', { dx: 0, dy: zoom });
                }
            }
            return;
        }

        if (gamepadSwipeState.mode === 'swipe') {
            if (e.touches.length === 2 && !isGamepadPointerActive()) {
                const t1 = e.touches[0];
                const t2 = e.touches[1];
                gamepadSwipeState.mode = 'pinch';
                gamepadSwipeState.pinchId1 = t1.identifier;
                gamepadSwipeState.pinchId2 = t2.identifier;
                gamepadSwipeState.touchId = null;
                const dx = t1.clientX - t2.clientX;
                const dy = t1.clientY - t2.clientY;
                gamepadSwipeState.lastPinchDistance = Math.sqrt(dx * dx + dy * dy);
                return;
            }
            const touch = Array.from(e.touches).find(t => t.identifier === gamepadSwipeState.touchId);
            if (!touch) return;

            const deltaX = touch.clientX - gamepadSwipeState.lastX;
            const deltaY = touch.clientY - gamepadSwipeState.lastY;
            gamepadSwipeState.lastX = touch.clientX;
            gamepadSwipeState.lastY = touch.clientY;

            const totalMoveX = Math.abs(touch.clientX - gamepadSwipeState.startX);
            const totalMoveY = Math.abs(touch.clientY - gamepadSwipeState.startY);
            if (!gamepadSwipeState.moved && (totalMoveX > 6 || totalMoveY > 6)) {
                gamepadSwipeState.moved = true;
            }

            if (isGamepadPointerActive()) {
                const sens = CONFIG.mouseSensitivity || 1.5;
                const dx = deltaX * sens;
                const dy = deltaY * sens;
                const rdx = Math.round(dx);
                const rdy = Math.round(dy);
                if (rdx !== 0 || rdy !== 0) {
                    state.virtualMouse.x += dx;
                    state.virtualMouse.y += dy;
                    state.virtualMouse.x = Math.max(0, Math.min(state.virtualMouse.x, state.screenWidth));
                    state.virtualMouse.y = Math.max(0, Math.min(state.virtualMouse.y, state.screenHeight));
                    updateVirtualCursorDisplay();
                    emit('mouse_move_relative', { dx: rdx, dy: rdy, raw: false });
                }
            } else {
                const scale = (CONFIG.gameMode.cameraSensitivity / 30) * 3;
                const dx = deltaX * scale;
                const dy = deltaY * scale;
                const rdx = Math.round(dx);
                const rdy = Math.round(dy);
                if (rdx !== 0 || rdy !== 0) {
                    emit('mouse_move_relative', { dx: rdx, dy: rdy, raw: true });
                }
            }
        }
    }

    function gamepadSwipeEnd(e) {
        if (gamepadSwipeState.mode === null) return;

        if (gamepadSwipeState.mode === 'swipe') {
            const ended = Array.from(e.changedTouches).some(t => t.identifier === gamepadSwipeState.touchId);
            if (!ended) return;

            const duration = Date.now() - gamepadSwipeState.startTime;
            if (isGamepadPointerActive() && !gamepadSwipeState.moved && duration < 350) {
                doClick();
            }
        }

        if (gamepadSwipeState.mode === 'pinch') {
            const endedAny = Array.from(e.changedTouches).some(t => t.identifier === gamepadSwipeState.pinchId1 || t.identifier === gamepadSwipeState.pinchId2);
            if (!endedAny) return;

            if (e.touches.length === 1) {
                const remaining = e.touches[0];
                gamepadSwipeState.mode = 'swipe';
                gamepadSwipeState.touchId = remaining.identifier;
                gamepadSwipeState.startX = remaining.clientX;
                gamepadSwipeState.startY = remaining.clientY;
                gamepadSwipeState.lastX = remaining.clientX;
                gamepadSwipeState.lastY = remaining.clientY;
                gamepadSwipeState.moved = true;
                gamepadSwipeState.startTime = Date.now();
                gamepadSwipeState.lastSendTime = 0;
                gamepadSwipeState.pinchId1 = null;
                gamepadSwipeState.pinchId2 = null;
                gamepadSwipeState.lastPinchDistance = 0;
                state.isTouching = true;
                return;
            }
        }

        gamepadSwipeState.mode = null;
        gamepadSwipeState.touchId = null;
        gamepadSwipeState.pinchId1 = null;
        gamepadSwipeState.pinchId2 = null;
        gamepadSwipeState.moved = false;
        state.isTouching = false;
    }

    // 鍙戦€佺浉瀵圭Щ鍔ㄥ懡浠ゅ埌鏈嶅姟绔?
    function sendRelativeMove(dx, dy) {
        if (!state.virtualMouse) {
            state.virtualMouse = {
                x: state.screenWidth / 2,
                y: state.screenHeight / 2,
            };
        }

        // 鏇存柊鏈湴铏氭嫙榧犳爣浣嶇疆
        state.virtualMouse.x += dx;
        state.virtualMouse.y += dy;

        // 闄愬埗鍦ㄥ睆骞曡寖鍥村唴
        state.virtualMouse.x = Math.max(0, Math.min(state.virtualMouse.x, state.screenWidth));
        state.virtualMouse.y = Math.max(0, Math.min(state.virtualMouse.y, state.screenHeight));

        // 鏇存柊鏄剧ず
        updateVirtualCursorDisplay();

        // 鍙戦€佸埌鏈嶅姟绔?
        emit('mouse_move_relative', { dx: dx, dy: dy });
    }

    // 鍙戦€佺粷瀵逛綅缃紙鐢ㄤ簬鏍″噯锛?
    function sendAbsoluteMove(x, y) {
        state.virtualMouse.x = Math.max(0, Math.min(x, state.screenWidth));
        state.virtualMouse.y = Math.max(0, Math.min(y, state.screenHeight));
        updateVirtualCursorDisplay();
        emit('mouse_move', {
            x: Math.round(state.virtualMouse.x),
            y: Math.round(state.virtualMouse.y)
        });
    }

    // 妫€鏌ュ苟鏍″噯浣嶇疆锛堝鏋滃亸宸繃澶э級
    function checkAndCalibratePosition(serverX, serverY) {
        const dx = Math.abs(state.virtualMouse.x - serverX);
        const dy = Math.abs(state.virtualMouse.y - serverY);

        // 濡傛灉鍋忓樊瓒呰繃闃堝€硷紝杩涜鏍″噯锛堜絾鍙湪闈炴嫋鎷芥ā寮忎笅锛?
        if ((dx > POS_SYNC_THRESHOLD || dy > POS_SYNC_THRESHOLD) && !touchState.isDragging) {
            debugLog(`[Calibrate] position drift too large (${dx.toFixed(0)}, ${dy.toFixed(0)})`);
            state.virtualMouse.x = serverX;
            state.virtualMouse.y = serverY;
            updateVirtualCursorDisplay();
        }
    }

    // 鎵ц鍗曞嚮
    function doClick() {
        const closeTabAfterClick = state.currentMode === 'gamepad' && state.gamepadTabWheelActive;
        playClickAnimation();
        emit('mouse_click', { button: 'left', action: 'down' });
        setTimeout(() => {
            emit('mouse_click', { button: 'left', action: 'up' });
            if (closeTabAfterClick) {
                emit('key_event', { key: 'Tab', action: 'up' });
                state.gamepadTabWheelActive = false;
                const tabBtn = document.querySelector('.extra-btn[data-key="Tab"]');
                if (tabBtn) {
                    tabBtn.classList.remove('locked');
                }
                updateCursorDotVisibility();
            }
        }, 50);
    }

    // 鐐瑰嚮鍔ㄧ敾
    function playClickAnimation() {
        virtualCursor.classList.add('clicking');
        setTimeout(() => {
            virtualCursor.classList.remove('clicking');
        }, 150);
    }

    // 鍙栨秷寰呭鐞嗙殑鍗曞嚮
    function cancelPendingClick() {
        if (clickTimer) {
            clearTimeout(clickTimer);
            clickTimer = null;
        }
        touchState.pendingClick = false;
    }

    // 瑙︽懜寮€濮?
    overlay.addEventListener('touchstart', (e) => {
        e.preventDefault();
        if (state.currentMode === 'gamepad') {
            gamepadSwipeStart(e);
            return;
        }
        if (state.currentMode !== 'touch') {
            return;
        }

        const now = Date.now();
        const touch = e.touches[0];

        // 妫€娴嬪弻鍑伙紙绗簩娆＄偣鍑伙級
        const timeSinceLastTap = now - lastTapTime;
        const isDoubleTap = (timeSinceLastTap < DOUBLE_TAP_TIME) &&
                            lastTapX !== 0 && lastTapY !== 0 &&
                            Math.abs(touch.clientX - lastTapX) < DOUBLE_TAP_DISTANCE &&
                            Math.abs(touch.clientY - lastTapY) < DOUBLE_TAP_DISTANCE;

        state.isTouching = true;
        touchState.touchCount = e.touches.length;
        touchState.startTime = now;
        touchState.hasMoved = false;

        if (e.touches.length === 1) {
            touchState.startX = touch.clientX;
            touchState.startY = touch.clientY;
            touchState.lastX = touch.clientX;
            touchState.lastY = touch.clientY;
            touchState.isMoving = false;

            // 瑙︽懜寮€濮嬫椂锛屽彂閫佺粷瀵逛綅缃繘琛屾牎鍑嗭紙纭繚瀹㈡埛绔拰鏈嶅姟绔綅缃竴鑷达級
            // 杩欏緢閲嶈锛屽洜涓烘煇浜涚獥鍙ｄ細鎹曡幏/閲嶇疆榧犳爣浣嶇疆
            sendAbsoluteMove(state.virtualMouse.x, state.virtualMouse.y);

            // 濡傛灉鏄弻鍑伙紝杩涘叆鎷栨嫿妯″紡
            if (isDoubleTap) {
                // 鍙栨秷寰呭鐞嗙殑鍗曞嚮
                cancelPendingClick();
                touchState.isSecondTap = true;
                touchState.isDragging = true;
                touchState.leftButtonDown = true;
                // 鍙戦€?left down锛堝紑濮嬫嫋鎷斤級
                emit('mouse_click', { button: 'left', action: 'down' });
                playClickAnimation();
                debugLog('[触控] 进入拖拽模式');
            } else {
                // 绗竴娆＄偣鍑伙紝涓嶇珛鍗虫墽琛岋紝寤惰繜绛夊緟纭鏄惁鏄弻鍑?
                touchState.isSecondTap = false;
                touchState.pendingClick = true;
                clickTimer = setTimeout(() => {
                    // 寤惰繜鍚庢墽琛屽崟鍑?
                    if (touchState.pendingClick) {
                        touchState.pendingClick = false;
                        doClick();
                    }
                }, CLICK_DELAY);
            }

        } else if (e.touches.length === 2) {
            // 鍙屾寚鎸変笅 - 鍙栨秷鍗曞嚮锛屽噯澶囧彸閿垨婊氳疆
            cancelPendingClick();

            const touch1 = e.touches[0];
            const touch2 = e.touches[1];
            touchState.startX = (touch1.clientX + touch2.clientX) / 2;
            touchState.startY = (touch1.clientY + touch2.clientY) / 2;
            touchState.lastX = touchState.startX;
            touchState.lastY = touchState.startY;

            // 濡傛灉涔嬪墠鏈夊乏閿寜浣忥紝鎶捣瀹?
            if (touchState.leftButtonDown) {
                emit('mouse_click', { button: 'left', action: 'up' });
                touchState.leftButtonDown = false;
                touchState.isDragging = false;
            }
        }
    }, { passive: false });

    // 瑙︽懜绉诲姩
    overlay.addEventListener('touchmove', (e) => {
        e.preventDefault();
        if (state.currentMode === 'gamepad') {
            gamepadSwipeMove(e);
            return;
        }
        if (state.currentMode !== 'touch') {
            return;
        }
        if (!state.isTouching) return;

        if (e.touches.length === 1 && touchState.touchCount === 1) {
            // 鍗曟寚绉诲姩 - 鎺у埗榧犳爣鎴栨嫋鎷?
            const touch = e.touches[0];

            // 璁＄畻绉诲姩宸€?
            const sens = getSensitivity();
            const dx = (touch.clientX - touchState.lastX) * sens;
            const dy = (touch.clientY - touchState.lastY) * sens;

            // 鍒ゆ柇鏄惁寮€濮嬬Щ鍔?
            const totalMoveX = Math.abs(touch.clientX - touchState.startX);
            const totalMoveY = Math.abs(touch.clientY - touchState.startY);

            if (totalMoveX > 3 || totalMoveY > 3) {
                touchState.isMoving = true;
                touchState.hasMoved = true;
                cancelPendingClick();
                // 娉ㄦ剰锛氬崟鎸囨粦鍔ㄥ彧鏄Щ鍔ㄩ紶鏍囷紝涓嶄細鑷姩杩涘叆鎷栨嫿妯″紡
                // 鎷栨嫿闇€瑕侀€氳繃鍙屽嚮骞舵寜浣忔潵瀹炵幇
            }

            // 鍙戦€侀紶鏍囩Щ鍔紙鏃犺鏄惁鎷栨嫿锛岄兘瑕佺Щ鍔ㄩ紶鏍囷級
            sendRelativeMove(Math.round(dx), Math.round(dy));

            // 鏇存柊鏈€鍚庝綅缃?
            touchState.lastX = touch.clientX;
            touchState.lastY = touch.clientY;

        } else if (e.touches.length === 2) {
            // 鍙屾寚绉诲姩 - 婊氳疆锛堟敮鎸佷笂涓嬪乏鍙筹級
            const touch1 = e.touches[0];
            const touch2 = e.touches[1];
            const centerX = (touch1.clientX + touch2.clientX) / 2;
            const centerY = (touch1.clientY + touch2.clientY) / 2;

            if (touchState.lastX !== 0 && touchState.lastY !== 0) {
                const deltaX = centerX - touchState.lastX;
                const deltaY = centerY - touchState.lastY;
                const movedFromStartX = Math.abs(centerX - touchState.startX);
                const movedFromStartY = Math.abs(centerY - touchState.startY);

                if (movedFromStartX > TWO_FINGER_TAP_MOVE_THRESHOLD || movedFromStartY > TWO_FINGER_TAP_MOVE_THRESHOLD) {
                    touchState.hasMoved = true;
                }

                // 鍙屾寚婊戝姩鏄犲皠涓烘粴杞?
                // 鍨傜洿婊戝姩 = 涓婁笅婊氬姩锛屾按骞虫粦鍔?= 宸﹀彸婊氬姩
                const scrollSensitivity = 3;
                if (Math.abs(deltaX) >= TWO_FINGER_SCROLL_DEADZONE || Math.abs(deltaY) >= TWO_FINGER_SCROLL_DEADZONE) {
                    emit('mouse_scroll', {
                        dx: Math.round(deltaX * scrollSensitivity),
                        dy: Math.round(-deltaY * scrollSensitivity)
                    });
                    touchState.hasMoved = true;
                }
            }

            touchState.lastX = centerX;
            touchState.lastY = centerY;
        }
    }, { passive: false });

    // 瑙︽懜缁撴潫
    overlay.addEventListener('touchend', (e) => {
        e.preventDefault();
        if (state.currentMode === 'gamepad') {
            gamepadSwipeEnd(e);
            return;
        }
        if (state.currentMode !== 'touch') {
            return;
        }

        const touchDuration = Date.now() - touchState.startTime;
        const remainingTouches = e.touches.length;

        // 鍙屾寚妫€娴嬶細濡傛灉寮€濮嬫椂鏄弻鎸?
        if (touchState.touchCount === 2) {
            // 鍙屾寚鐐瑰嚮锛堟病鏈夌Щ鍔級= 鍙抽敭
            if (touchDuration < TWO_FINGER_TAP_MAX_DURATION && !touchState.hasMoved) {
                playClickAnimation();
                emit('mouse_click', { button: 'right', action: 'down' });
                setTimeout(() => {
                    emit('mouse_click', { button: 'right', action: 'up' });
                }, 50);
            }

            if (remainingTouches === 0) {
                // 鎵€鏈夋墜鎸囬兘鎶捣
                state.isTouching = false;
                touchState.touchCount = 0;
                touchState.isMoving = false;
                touchState.hasMoved = false;
                touchState.isDragging = false;
            } else {
                // 杩樺墿涓€鏍规墜鎸囷紝杞负鍗曟寚鐘舵€?
                touchState.touchCount = 1;
                const touch = e.touches[0];
                touchState.startX = touch.clientX;
                touchState.startY = touch.clientY;
                touchState.lastX = touch.clientX;
                touchState.lastY = touch.clientY;
                touchState.startTime = Date.now();
                touchState.hasMoved = false;
            }
            return;
        }

        // 鍗曟寚澶勭悊
        if (remainingTouches === 0) {
            const touch = e.changedTouches[0];
            const now = Date.now();

            if (touchState.isDragging) {
                // 鎷栨嫿妯″紡缁撴潫锛堝弻鍑诲悗鎸変綇锛夛紝鎶捣宸﹂敭
                emit('mouse_click', { button: 'left', action: 'up' });
                touchState.leftButtonDown = false;
                touchState.isDragging = false;
                touchState.isSecondTap = false;

                // 璁板綍鏈鐐瑰嚮锛屼絾涓嶄綔涓哄弻鍑荤殑绗竴娆＄偣鍑伙紙閬垮厤涓夊嚮璇垽锛?
                lastTapTime = 0;
                lastTapX = 0;
                lastTapY = 0;
            } else if (touchState.leftButtonDown) {
                // 纭繚宸﹂敭鎶捣
                emit('mouse_click', { button: 'left', action: 'up' });
                touchState.leftButtonDown = false;
            } else if (!touchState.hasMoved && touchDuration < 300 && touchState.pendingClick) {
                // 鐭寜涓旀病鏈夌Щ鍔紝涓旀湁寰呯‘璁ょ殑鍗曞嚮
                // 璁?timer 鍘诲鐞嗗崟鍑伙紙寤惰繜鎵ц锛?
                // 璁板綍鏈鐐瑰嚮鐢ㄤ簬鍙屽嚮妫€娴?
                lastTapTime = now;
                lastTapX = touch.clientX;
                lastTapY = touch.clientY;
            } else if (!touchState.hasMoved && touchDuration >= 300) {
                // 闀挎寜娌℃湁绉诲姩锛屾墽琛屽崟鍑伙紙鍙栨秷寰呭鐞嗙姸鎬佺洿鎺ユ墽琛岋級
                cancelPendingClick();
                doClick();
            } else {
                // 绉诲姩浜嗭紝鍙栨秷鍗曞嚮
                cancelPendingClick();
            }

            // 閲嶇疆鐘舵€?
            state.isTouching = false;
            touchState.touchCount = 0;
            touchState.isMoving = false;
            touchState.hasMoved = false;
        }
    }, { passive: false });

    overlay.addEventListener('touchcancel', (e) => {
        e.preventDefault();
        if (state.currentMode === 'gamepad') {
            gamepadSwipeEnd(e);
            return;
        }
    }, { passive: false });
}

// ============ 娓告垙鎵嬫焺妯″紡 ============
function initGamepadMode() {
    initVirtualStick('left-stick', (x, y) => {
        emit('gamepad_input', { type: 'movement', x: x, y: y });
    });

    document.querySelectorAll('.action-btn, .mouse-btn').forEach(btn => {
        const keyName = btn.dataset.key;
        const mouseButton = btn.dataset.mouse;

        const onDown = (e) => {
            e.preventDefault();
            btn.classList.add('pressed');
            if (mouseButton) {
                emit('mouse_click', { button: mouseButton, action: 'down' });
            } else if (keyName) {
                emit('key_event', { key: keyName, action: 'down' });
            }
        };

        const onUp = (e) => {
            e.preventDefault();
            btn.classList.remove('pressed');
            if (mouseButton) {
                emit('mouse_click', { button: mouseButton, action: 'up' });
                if (mouseButton === 'left' && state.gamepadTabWheelActive) {
                    emit('key_event', { key: 'Tab', action: 'up' });
                    state.gamepadTabWheelActive = false;
                    const tabBtn = document.querySelector('.extra-btn[data-key="Tab"]');
                    if (tabBtn) {
                        tabBtn.classList.remove('locked');
                    }
                    updateCursorDotVisibility();
                }
            } else if (keyName) {
                emit('key_event', { key: keyName, action: 'up' });
            }
        };

        btn.addEventListener('touchstart', onDown, { passive: false });
        btn.addEventListener('touchend', onUp, { passive: false });
        btn.addEventListener('touchcancel', onUp, { passive: false });
    });

    document.querySelectorAll('.extra-btn').forEach(btn => {
        const keyName = btn.dataset.key;
        const isToggle = btn.classList.contains('toggle') && keyName === 'Alt';

        if (isToggle) {
            btn.addEventListener('touchstart', (e) => {
                e.preventDefault();
                state.gamepadAltLocked = !state.gamepadAltLocked;
                btn.classList.toggle('locked', state.gamepadAltLocked);
                emit('key_event', { key: 'Alt', action: state.gamepadAltLocked ? 'down' : 'up' });
                if (isGamepadPointerActive()) {
                    updateVirtualCursorDisplay();
                } else {
                    updateCursorDotVisibility();
                }
            }, { passive: false });
            return;
        }

        if (keyName === 'Tab') {
            btn.addEventListener('touchstart', (e) => {
                e.preventDefault();
                state.gamepadTabWheelActive = !state.gamepadTabWheelActive;
                btn.classList.toggle('locked', state.gamepadTabWheelActive);
                emit('key_event', { key: 'Tab', action: state.gamepadTabWheelActive ? 'down' : 'up' });
                if (state.gamepadTabWheelActive) {
                    if (!state.virtualMouse) {
                        state.virtualMouse = { x: state.screenWidth / 2, y: state.screenHeight / 2 };
                    }
                    updateVirtualCursorDisplay();
                } else {
                    updateCursorDotVisibility();
                }
            }, { passive: false });
            return;
        }

        btn.addEventListener('touchstart', (e) => {
            e.preventDefault();
            btn.classList.add('pressed');
            emit('key_event', { key: keyName, action: 'down' });
        }, { passive: false });

        const onUp = (e) => {
            e.preventDefault();
            btn.classList.remove('pressed');
            emit('key_event', { key: keyName, action: 'up' });
        };

        btn.addEventListener('touchend', onUp, { passive: false });
        btn.addEventListener('touchcancel', onUp, { passive: false });
    });
}

function initPhysicalGamepadForwarding() {
    if (typeof navigator === 'undefined' || typeof navigator.getGamepads !== 'function') return;

    const toI16 = (v) => {
        const x = Math.max(-1, Math.min(1, v || 0));
        return Math.max(-32768, Math.min(32767, Math.round(x * 32767)));
    };

    const applyDeadzone = (v, dz = 0.08) => {
        const x = v || 0;
        return Math.abs(x) < dz ? 0 : x;
    };

    const getActivePad = () => {
        const pads = navigator.getGamepads();
        if (!pads) return null;
        if (state.physicalGamepad.index !== null && pads[state.physicalGamepad.index]) {
            const selected = pads[state.physicalGamepad.index];
            if (selected && selected.connected) {
                return selected;
            }
            state.physicalGamepad.index = null;
        }
        for (const p of pads) {
            if (p && p.connected) return p;
        }
        return null;
    };

    const sendNeutral = () => {
        if (!state.connected) return;
        emit('xinput_state', { lx: 0, ly: 0, rx: 0, ry: 0, lt: 0, rt: 0, buttons: 0 });
        state.physicalGamepad.lastPayloadKey = '0,0,0,0,0,0,0';
    };

    const connectIfPossible = (gp) => {
        if (!state.connected || !state.physicalGamepad.enabled) return;
        if (!gp) gp = getActivePad();
        if (!gp || !gp.connected) return;

        state.physicalGamepad.active = true;
        state.physicalGamepad.connected = true;
        state.physicalGamepad.index = gp.index;
        state.physicalGamepad.missCount = 0;
        state.physicalGamepad.lastSentAt = 0;
        state.physicalGamepad.lastPayloadKey = '';
        state.physicalGamepad.lastConnectAt = Date.now();
        emit('xinput_connect', { connected: true, id: gp.id || '' });
        sendNeutral();
    };

    const disconnectNow = (hard = false) => {
        if (state.physicalGamepad.connected) {
            sendNeutral();
            if (hard) {
                emit('xinput_disconnect', {});
            }
        }
        state.physicalGamepad.active = false;
        state.physicalGamepad.connected = false;
        state.physicalGamepad.index = null;
        state.physicalGamepad.missCount = 0;
        state.physicalGamepad.lastSentAt = 0;
        state.physicalGamepad.lastPayloadKey = '';
    };

    const pollOnce = () => {
        if (!state.physicalGamepad.enabled) return;
        if (!state.connected || document.hidden) return;
        const gp = getActivePad();
        if (!gp || !gp.connected) {
            state.physicalGamepad.missCount = (state.physicalGamepad.missCount || 0) + 1;
            // 閬垮厤娴忚鍣ㄥ伓鍙戜竴甯ф嬁涓嶅埌鎵嬫焺灏辨柇寮€
            if (state.physicalGamepad.connected && state.physicalGamepad.missCount > 30) {
                disconnectNow(false);
            }
            return;
        }
        state.physicalGamepad.missCount = 0;

        if (!state.physicalGamepad.connected) {
            connectIfPossible(gp);
            if (!state.physicalGamepad.connected) return;
        } else {
            // 蹇冭烦閲嶈繛锛氫慨澶嶆ā寮忓垏鍥炲悗鏈嶅姟绔?owner 涓㈠け瀵艰嚧鏃犲搷搴?
            const nowConnect = Date.now();
            if (!state.physicalGamepad.lastConnectAt || (nowConnect - state.physicalGamepad.lastConnectAt) > 1500) {
                state.physicalGamepad.lastConnectAt = nowConnect;
                emit('xinput_connect', { connected: true, id: gp.id || '' });
            }
        }

        const axes = gp.axes || [];
        const buttons = gp.buttons || [];

        const lx = toI16(applyDeadzone(axes[0]));
        const ly = toI16(applyDeadzone(-(axes[1] || 0)));
        const rx = toI16(applyDeadzone(axes[2] || 0));
        const ry = toI16(applyDeadzone(-(axes[3] || 0)));

        const lt = Math.max(0, Math.min(255, Math.round(((buttons[6] && buttons[6].value) || 0) * 255)));
        const rt = Math.max(0, Math.min(255, Math.round(((buttons[7] && buttons[7].value) || 0) * 255)));

        const pressed = (idx) => !!(buttons[idx] && buttons[idx].pressed);

        let mask = 0;
        if (pressed(12)) mask |= 0x0001;
        if (pressed(13)) mask |= 0x0002;
        if (pressed(14)) mask |= 0x0004;
        if (pressed(15)) mask |= 0x0008;
        if (pressed(9)) mask |= 0x0010;
        if (pressed(8)) mask |= 0x0020;
        if (pressed(10)) mask |= 0x0040;
        if (pressed(11)) mask |= 0x0080;
        if (pressed(4)) mask |= 0x0100;
        if (pressed(5)) mask |= 0x0200;
        if (pressed(16)) mask |= 0x0400;
        if (pressed(0)) mask |= 0x1000;
        if (pressed(1)) mask |= 0x2000;
        if (pressed(2)) mask |= 0x4000;
        if (pressed(3)) mask |= 0x8000;

        const key = `${lx},${ly},${rx},${ry},${lt},${rt},${mask}`;
        if (key === state.physicalGamepad.lastPayloadKey) return;

        const now = Date.now();
        const lastAt = state.physicalGamepad.lastSentAt || 0;
        if (now - lastAt < 16) return;

        state.physicalGamepad.lastSentAt = now;
        state.physicalGamepad.lastPayloadKey = key;
        emit('xinput_state', { lx, ly, rx, ry, lt, rt, buttons: mask });
    };

    state.physicalGamepad.setEnabled = (enabled) => {
        const on = !!enabled;
        if (!on) {
            state.physicalGamepad.enabled = false;
            disconnectNow();
            return;
        }

        state.physicalGamepad.enabled = true;
        state.physicalGamepad.index = null;
        state.physicalGamepad.missCount = 0;
        state.physicalGamepad.lastConnectAt = 0;
        connectIfPossible();
        if (state.physicalGamepad.connected) {
            sendNeutral();
        }
    };

    window.addEventListener('gamepadconnected', (e) => {
        const gp = e.gamepad;
        state.physicalGamepad.index = gp ? gp.index : state.physicalGamepad.index;
        if (state.physicalGamepad.enabled) {
            connectIfPossible(gp);
        }
    });

    window.addEventListener('gamepaddisconnected', (e) => {
        if (state.physicalGamepad.index === (e.gamepad && e.gamepad.index)) {
            disconnectNow();
        }
    });

    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            sendNeutral();
            return;
        }
        if (state.physicalGamepad.enabled) {
            connectIfPossible();
        }
    });

    window.addEventListener('beforeunload', () => {
        if (state.physicalGamepad.pollTimer !== null) {
            clearInterval(state.physicalGamepad.pollTimer);
            state.physicalGamepad.pollTimer = null;
        }
        disconnectNow();
    });

    // 甯搁┗杞锛?6ms锛夛細姣?RAF 鍦ㄧЩ鍔ㄧ妯″紡鍒囨崲鏃舵洿绋冲畾
    if (state.physicalGamepad.pollTimer === null) {
        state.physicalGamepad.pollTimer = setInterval(pollOnce, 16);
    }
}

function releaseGamepadToggles() {
    if (state.gamepadAltLocked) {
        emit('key_event', { key: 'Alt', action: 'up' });
        state.gamepadAltLocked = false;
        const altBtn = document.querySelector('.extra-btn.toggle[data-key="Alt"]');
        if (altBtn) {
            altBtn.classList.remove('locked');
        }
        updateCursorDotVisibility();
    }

    if (state.gamepadTabWheelActive) {
        emit('key_event', { key: 'Tab', action: 'up' });
        state.gamepadTabWheelActive = false;
        const tabBtn = document.querySelector('.extra-btn[data-key="Tab"]');
        if (tabBtn) {
            tabBtn.classList.remove('locked');
        }
        updateCursorDotVisibility();
    }
}

function initVirtualStick(elementId, callback, isMouseStick = false) {
    const stick = document.getElementById(elementId);
    const base = stick.querySelector('.stick-base');
    const handle = stick.querySelector('.stick-handle');
    let activeTouchId = null;
    let stickCenterX = 0;
    let stickCenterY = 0;

    base.addEventListener('touchstart', (e) => {
        e.preventDefault();
        if (activeTouchId !== null) return;

        const touch = e.touches[0];
        activeTouchId = touch.identifier;

        const rect = base.getBoundingClientRect();
        stickCenterX = rect.left + rect.width / 2;
        stickCenterY = rect.top + rect.height / 2;

        updateStick(touch.clientX, touch.clientY);

        if (isMouseStick) {
            state.lastMouseX = state.screenWidth / 2;
            state.lastMouseY = state.screenHeight / 2;
        }
    }, { passive: false });

    document.addEventListener('touchmove', (e) => {
        if (activeTouchId === null) return;

        const touch = Array.from(e.touches).find(t => t.identifier === activeTouchId);
        if (!touch) return;

        e.preventDefault();
        updateStick(touch.clientX, touch.clientY);
    }, { passive: false });

    document.addEventListener('touchend', (e) => {
        if (activeTouchId === null) return;

        const touch = Array.from(e.changedTouches).find(t => t.identifier === activeTouchId);
        if (!touch) return;

        e.preventDefault();
        activeTouchId = null;
        handle.style.transform = 'translate(-50%, -50%)';
        callback(0, 0);
    }, { passive: false });

    function updateStick(clientX, clientY) {
        const maxDistance = CONFIG.maxStickDistance;
        let deltaX = clientX - stickCenterX;
        let deltaY = clientY - stickCenterY;

        const distance = Math.sqrt(deltaX * deltaX + deltaY * deltaY);

        if (distance > maxDistance) {
            deltaX = (deltaX / distance) * maxDistance;
            deltaY = (deltaY / distance) * maxDistance;
        }

        handle.style.transform = `translate(calc(-50% + ${deltaX}px), calc(-50% + ${deltaY}px))`;

        const normalizedX = deltaX / maxDistance;
        const normalizedY = deltaY / maxDistance;

        const outputX = Math.abs(normalizedX) < CONFIG.deadzone ? 0 : normalizedX;
        const outputY = Math.abs(normalizedY) < CONFIG.deadzone ? 0 : normalizedY;

        callback(outputX, outputY);

        if (isMouseStick) {
            state.lastMouseX += outputX * CONFIG.mouseSensitivity * 8;
            state.lastMouseY += outputY * CONFIG.mouseSensitivity * 8;
            state.lastMouseX = Math.max(0, Math.min(state.lastMouseX, state.screenWidth));
            state.lastMouseY = Math.max(0, Math.min(state.lastMouseY, state.screenHeight));
        }
    }
}

// ============ 閿洏妯″紡 ============
function initKeyboardMode() {
    const keys = document.querySelectorAll('.kb-key');
    const pressedKeys = new Set();

    keys.forEach(key => {
        const keyName = key.dataset.key;

        key.addEventListener('touchstart', (e) => {
            e.preventDefault();
            key.classList.add('pressed');

            // 鐗规畩澶勭悊閿佸畾閿?
            if (keyName === 'CapsLock') {
                key.classList.toggle('locked');
            }

            emit('key_event', { key: keyName, action: 'down' });
            pressedKeys.add(keyName);
        }, { passive: false });

        key.addEventListener('touchend', (e) => {
            e.preventDefault();
            key.classList.remove('pressed');

            // CapsLock 鍜屽叾浠栭攣瀹氶敭涓嶉渶瑕佸彂閫?up 浜嬩欢锛堝畠浼氫繚鎸佺姸鎬侊級
            if (keyName !== 'CapsLock') {
                emit('key_event', { key: keyName, action: 'up' });
            }
            pressedKeys.delete(keyName);
        });

        // 闃叉瑙︽懜鏃惰Е鍙戦粯璁よ涓?
        key.addEventListener('touchmove', (e) => {
            e.preventDefault();
        }, { passive: false });
    });

    // 闃叉閿洏鍖哄煙鐨勯粯璁よЕ鎽歌涓?
    const keyboardControls = document.getElementById('keyboard-controls');
    if (keyboardControls) {
        keyboardControls.addEventListener('touchstart', (e) => {
            if (e.target.closest('.kb-key')) {
                e.preventDefault();
            }
        }, { passive: false });
    }
}

function initHardwareKeyboardForwarding() {
    const activeKeys = new Map(); // keyId -> remoteKey
    const repeatTimers = new Map(); // keyId -> { startTimer, repeatTimer }
    const comboConsumedKeyIds = new Set(); // keyId consumed by shortcut remap
    const KEY_REPEAT_DELAY_MS = 320;
    const KEY_REPEAT_INTERVAL_MS = 45;

    function isEditableTarget(target) {
        if (!target) return false;
        const tag = target.tagName;
        if (!tag) return false;
        const upper = tag.toUpperCase();
        return upper === 'INPUT' || upper === 'TEXTAREA' || !!target.isContentEditable;
    }

    function normalizePhysicalKey(e) {
        const key = e.key;
        if (!key || key === 'Unidentified' || key === 'Dead' || key === 'Process') return null;
        if (key === ' ') return 'Space';
        if (key === 'Spacebar') return 'Space';
        if (key === 'Esc') return 'Escape';
        if (key === 'OS' || key === 'Super') return 'Meta';
        if (key === 'Left') return 'ArrowLeft';
        if (key === 'Right') return 'ArrowRight';
        if (key === 'Up') return 'ArrowUp';
        if (key === 'Down') return 'ArrowDown';
        if (key === 'ControlLeft' || key === 'ControlRight') return 'Control';
        if (key === 'ShiftLeft' || key === 'ShiftRight') return 'Shift';
        if (key === 'AltLeft' || key === 'AltRight') return 'Alt';
        if (key === 'Del') return 'Delete';
        return key;
    }

    function keyIdForEvent(e, normalizedKey) {
        return (e.code && e.code.length > 0) ? e.code : `key:${normalizedKey || e.key || 'unknown'}`;
    }

    function sendKey(remoteKey, action) {
        emit('key_event', { key: remoteKey, action: action });
    }

    function isModifierKey(remoteKey) {
        return remoteKey === 'Control' || remoteKey === 'Shift' || remoteKey === 'Alt' || remoteKey === 'Meta';
    }

    function isRepeatableKey(remoteKey) {
        if (!remoteKey) return false;
        if (isModifierKey(remoteKey)) return false;
        return remoteKey !== 'Escape';
    }

    function hasHeldControlKey() {
        for (const remoteKey of activeKeys.values()) {
            if (remoteKey === 'Control') return true;
        }
        return false;
    }

    function stopKeyRepeat(keyId) {
        const timers = repeatTimers.get(keyId);
        if (!timers) return;
        if (timers.startTimer) clearTimeout(timers.startTimer);
        if (timers.repeatTimer) clearInterval(timers.repeatTimer);
        repeatTimers.delete(keyId);
    }

    function startKeyRepeat(keyId, remoteKey) {
        if (!isRepeatableKey(remoteKey)) return;
        stopKeyRepeat(keyId);
        const startTimer = setTimeout(() => {
            if (!activeKeys.has(keyId)) {
                repeatTimers.delete(keyId);
                return;
            }
            sendKey(remoteKey, 'down');
            const repeatTimer = setInterval(() => {
                if (!activeKeys.has(keyId)) {
                    stopKeyRepeat(keyId);
                    return;
                }
                sendKey(remoteKey, 'down');
            }, KEY_REPEAT_INTERVAL_MS);
            repeatTimers.set(keyId, { startTimer: null, repeatTimer: repeatTimer });
        }, KEY_REPEAT_DELAY_MS);
        repeatTimers.set(keyId, { startTimer: startTimer, repeatTimer: null });
    }

    function tapSystemKey(remoteKey) {
        // 缁勫悎閿浛浠ｆ椂锛岄伩鍏嶈 Ctrl 淇グ鎴?Ctrl+Esc / Ctrl+Win銆?
        const hadControl = hasHeldControlKey();
        if (hadControl) {
            sendKey('Control', 'up');
        }
        sendKey(remoteKey, 'down');
        setTimeout(() => {
            sendKey(remoteKey, 'up');
            if (hadControl && hasHeldControlKey()) {
                sendKey('Control', 'down');
            }
        }, 35);
    }

    function isCtrlShortcutTrigger(e, normalizedKey, digit) {
        if (e.altKey || e.metaKey) return false;
        const code = e.code || '';
        const byCode = code === `Digit${digit}`;
        const byKey = normalizedKey === `${digit}`;
        return (byCode || byKey) && (e.ctrlKey || hasHeldControlKey());
    }

    function releaseAllHardwareKeys() {
        if (!state.connected) {
            for (const keyId of repeatTimers.keys()) stopKeyRepeat(keyId);
            activeKeys.clear();
            comboConsumedKeyIds.clear();
            return;
        }
        for (const keyId of repeatTimers.keys()) stopKeyRepeat(keyId);
        for (const remoteKey of activeKeys.values()) {
            sendKey(remoteKey, 'up');
        }
        activeKeys.clear();
        comboConsumedKeyIds.clear();
    }

    document.addEventListener('keydown', (e) => {
        if (!state.connected) return;
        if (isEditableTarget(e.target)) return;

        const normalizedKey = normalizePhysicalKey(e);
        if (!normalizedKey) return;
        const keyId = keyIdForEvent(e, normalizedKey);

        // 鏇夸唬绯荤粺閿細
        // Ctrl + 1 => Esc
        // Ctrl + 2 => Win
        if (isCtrlShortcutTrigger(e, normalizedKey, 1)) {
            e.preventDefault();
            if (!comboConsumedKeyIds.has(keyId)) {
                comboConsumedKeyIds.add(keyId);
                tapSystemKey('Escape');
            }
            return;
        }

        if (isCtrlShortcutTrigger(e, normalizedKey, 2)) {
            e.preventDefault();
            if (!comboConsumedKeyIds.has(keyId)) {
                comboConsumedKeyIds.add(keyId);
                tapSystemKey('Meta');
            }
            return;
        }

        e.preventDefault();
        if (activeKeys.has(keyId)) {
            const remoteKey = activeKeys.get(keyId);
            if (e.repeat && isRepeatableKey(remoteKey)) {
                // 娴忚鍣ㄨ嚜韬凡鎻愪緵 repeat 鏃讹紝鍋滅敤鏈湴 repeat 浠ュ厤鍙屽€嶈Е鍙戙€?
                stopKeyRepeat(keyId);
                sendKey(remoteKey, 'down');
            }
            return;
        }

        activeKeys.set(keyId, normalizedKey);
        sendKey(normalizedKey, 'down');
        startKeyRepeat(keyId, normalizedKey);
    }, { passive: false });

    document.addEventListener('keyup', (e) => {
        if (!state.connected) return;
        if (isEditableTarget(e.target)) return;

        const normalizedKey = normalizePhysicalKey(e);
        if (!normalizedKey) return;
        const keyId = keyIdForEvent(e, normalizedKey);

        if (comboConsumedKeyIds.has(keyId)) {
            e.preventDefault();
            comboConsumedKeyIds.delete(keyId);
            return;
        }

        if (activeKeys.has(keyId)) {
            e.preventDefault();
            stopKeyRepeat(keyId);
            sendKey(activeKeys.get(keyId), 'up');
            activeKeys.delete(keyId);
        }
    }, { passive: false });

    window.addEventListener('blur', releaseAllHardwareKeys);
    window.addEventListener('pagehide', releaseAllHardwareKeys);
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            releaseAllHardwareKeys();
        }
    });
}

// ============ 模式切换 ============
function initModeSwitching() {
    const modeBtns = document.querySelectorAll('.mode-btn');
    const touchOverlay = document.getElementById('touch-overlay');
    const gamepadControls = document.getElementById('gamepad-controls');
    const modeIndicator = document.getElementById('mode-indicator');
    const modeDescription = document.getElementById('mode-description');
    const globalSettings = document.getElementById('global-settings');

    const modeNames = {
        'touch': '触控模式',
        'gamepad': '游戏模式',
        'controller': '手柄模式'
    };

    const modeDescs = {
        'touch': '单指移动光标，单指点击左键，双指点击右键，双指滑动滚轮（支持 Ctrl+1=Esc，Ctrl+2=Win）',
        'gamepad': '左侧摇杆移动，右侧滑动转视角，动作按钮放在右侧，Alt 可长按切换',
        'controller': '蓝牙手柄直通电脑端（虚拟 Xbox 手柄），游戏可自动切换原生手柄 UI'
    };

    modeBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const prevMode = state.currentMode;
            const mode = btn.dataset.mode;

            modeBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            state.currentMode = mode;

            // 鏇存柊鎸囩ず鍣?
            modeIndicator.textContent = modeNames[mode];
            if (modeDescription) {
                modeDescription.textContent = modeDescs[mode];
            }

            // 閫氱煡鏈嶅姟绔ā寮忓垏鎹?
            emit('set_mode', { mode: mode });

            if (prevMode === 'gamepad' && mode !== 'gamepad') {
                releaseGamepadToggles();
            }

            // 鍒囨崲娓告垙妯″紡璁剧疆鏄剧ず
            const gameModeSettings = document.getElementById('game-mode-settings');
            if (gameModeSettings) {
                if (mode === 'gamepad') {
                    gameModeSettings.classList.remove('hidden');
                } else {
                    gameModeSettings.classList.add('hidden');
                }
            }

            // 鏇存柊榧犳爣绾㈢偣鏄剧ず鐘舵€?
            updateCursorDotVisibility();

            if (state.physicalGamepad && typeof state.physicalGamepad.setEnabled === 'function') {
                state.physicalGamepad.setEnabled(mode === 'controller');
            }

            // 鍒囨崲鏄剧ず
            switch (mode) {
                case 'touch':
                    touchOverlay.style.display = 'block';
                    gamepadControls.classList.add('hidden');
                    if (globalSettings) globalSettings.classList.remove('hidden');
                    break;
                case 'gamepad':
                    touchOverlay.style.display = 'block';
                    gamepadControls.classList.remove('hidden');
                    if (globalSettings) globalSettings.classList.add('hidden');
                    break;
                case 'controller':
                    touchOverlay.style.display = 'block';
                    gamepadControls.classList.add('hidden');
                    if (globalSettings) globalSettings.classList.remove('hidden');
                    break;
            }
        });
    });
}

// ============ 设置面板 ============
function initSettings() {
    const settingsBtn = document.getElementById('settings-btn');
    const settingsPanel = document.getElementById('settings-panel');
    const closeSettings = document.getElementById('close-settings');
    const fullscreenBtn = document.getElementById('fullscreen-btn');
    const fullscreenText = document.getElementById('fullscreen-text');

    // 画质滑块
    const qualitySlider = document.getElementById('quality-slider');
    const qualityValue = document.getElementById('quality-value');
    qualityValue.textContent = qualitySlider.value;
    qualitySlider.addEventListener('input', () => {
        qualityValue.textContent = qualitySlider.value;
        emit('set_quality', { quality: parseInt(qualitySlider.value) });
    });
    qualitySlider.addEventListener('change', () => {
        if (state.webrtc.using) {
            // Bitrate tuning is negotiated in SDP; restart once on release.
            scheduleWebRTCRestart('quality_changed', 200);
        }
    });

    // 帧率滑块
    const fpsSlider = document.getElementById('fps-slider');
    const fpsValue = document.getElementById('fps-value');
    fpsValue.textContent = fpsSlider.value;
    lastSentFps = parseInt(fpsSlider.value, 10);
    fpsSlider.addEventListener('input', () => {
        fpsValue.textContent = fpsSlider.value;
        sendFpsSetting(fpsSlider.value, false);
    });
    fpsSlider.addEventListener('change', () => {
        sendFpsSetting(fpsSlider.value, true);
    });

    // 鼠标灵敏度滑块
    const sensitivitySlider = document.getElementById('sensitivity-slider');
    const sensitivityValue = document.getElementById('sensitivity-value');
    CONFIG.mouseSensitivity = parseFloat(sensitivitySlider.value);
    sensitivityValue.textContent = sensitivitySlider.value + 'x';
    sensitivitySlider.addEventListener('input', () => {
        const value = sensitivitySlider.value;
        sensitivityValue.textContent = value + 'x';
        CONFIG.mouseSensitivity = parseFloat(value);
    });

    const keyboardToggleBtn = document.getElementById('keyboard-toggle-btn');
    const keyboardToggleText = document.getElementById('keyboard-toggle-text');
    const keyboardControls = document.getElementById('keyboard-controls');
    if (keyboardToggleBtn && keyboardControls) {
        const applyKeyboardVisible = (visible) => {
            state.keyboardVisible = !!visible;
            if (state.keyboardVisible) {
                keyboardControls.classList.remove('hidden');
                if (keyboardToggleBtn.tagName === 'INPUT') {
                    keyboardToggleBtn.checked = true;
                } else {
                    keyboardToggleBtn.textContent = '收起';
                    keyboardToggleBtn.classList.add('active');
                }
                if (keyboardToggleText) keyboardToggleText.textContent = '开启';
            } else {
                keyboardControls.classList.add('hidden');
                if (keyboardToggleBtn.tagName === 'INPUT') {
                    keyboardToggleBtn.checked = false;
                } else {
                    keyboardToggleBtn.textContent = '唤出';
                    keyboardToggleBtn.classList.remove('active');
                }
                if (keyboardToggleText) keyboardToggleText.textContent = '关闭';
            }
        };
        applyKeyboardVisible(false);
        if (keyboardToggleBtn.tagName === 'INPUT') {
            keyboardToggleBtn.addEventListener('change', () => {
                applyKeyboardVisible(keyboardToggleBtn.checked);
            });
        } else {
            keyboardToggleBtn.addEventListener('click', () => {
                applyKeyboardVisible(!state.keyboardVisible);
            });
        }
    }

    // 低延迟模式
    const lowLatencyCheckbox = document.getElementById('low-latency-mode');
    if (lowLatencyCheckbox) {
        applyLowLatencyMode(lowLatencyCheckbox.checked);
        lowLatencyCheckbox.addEventListener('change', () => {
            applyLowLatencyMode(lowLatencyCheckbox.checked);
            debugLog('[Config] low latency mode:', CONFIG.lowLatencyMode);
        });
    }

    // 娓告垙妯″紡涓撶敤璁剧疆
    initGameModeSettings();

    // 鍏ㄥ睆
    if (fullscreenBtn) {
        const syncFullscreenUI = () => {
            const active = !!document.fullscreenElement;
            if (fullscreenBtn.tagName === 'INPUT') fullscreenBtn.checked = active;
            if (fullscreenText) fullscreenText.textContent = active ? '开启' : '关闭';
        };
        syncFullscreenUI();
        document.addEventListener('fullscreenchange', syncFullscreenUI);

        if (fullscreenBtn.tagName === 'INPUT') {
            fullscreenBtn.addEventListener('change', async () => {
                try {
                    if (fullscreenBtn.checked) {
                        await document.documentElement.requestFullscreen();
                    } else {
                        await document.exitFullscreen();
                    }
                } catch (e) {
                    syncFullscreenUI();
                }
            });
        } else {
            fullscreenBtn.addEventListener('click', async () => {
                try {
                    if (!document.fullscreenElement) {
                        await document.documentElement.requestFullscreen();
                    } else {
                        await document.exitFullscreen();
                    }
                } catch (e) {
                } finally {
                    syncFullscreenUI();
                }
            });
        }
    }

    // 鎵撳紑/鍏抽棴璁剧疆
    settingsBtn.addEventListener('click', () => {
        settingsPanel.classList.remove('hidden');
    });

    closeSettings.addEventListener('click', () => {
        settingsPanel.classList.add('hidden');
    });

    // 鐐瑰嚮闈㈡澘澶栭儴鍏抽棴
    settingsPanel.addEventListener('click', (e) => {
        if (e.target === settingsPanel) {
            settingsPanel.classList.add('hidden');
        }
    });
}

// ============ 杈呭姪鍑芥暟 ============
function emit(event, data) {
    if (state.connected && state.socket) {
        state.socket.emit(event, data);
    }
}

// FPS 璁＄畻
function updateFPS() {
    state.frameCount++;
    const now = Date.now();
    const elapsed = now - state.lastFpsUpdate;

    if (elapsed >= 1000) {
        state.fps = Math.round((state.frameCount * 1000) / elapsed);
        const fpsEl = document.getElementById('fps-counter');
        if (fpsEl) {
            const displayFps = state.webrtc.using ? state.videoFps : state.fps;
            if (state.webrtc.using) {
                const mbps = state.webrtcStats.bitrateMbps || 0;
                const akbps = state.webrtcStats.audioKbps || 0;
                fpsEl.textContent = displayFps + ' FPS ' + mbps.toFixed(1) + ' Mbps A:' + akbps.toFixed(0) + 'kbps';
            } else {
                fpsEl.textContent = displayFps + ' FPS';
            }
        }
        state.frameCount = 0;
        state.lastFpsUpdate = now;
    }

    requestAnimationFrame(updateFPS);
}

// ============ 娓告垙妯″紡璁剧疆 ============
function initGameModeSettings() {
    // 瑙嗚鐏垫晱搴︽粦鍧?
    const cameraSensitivitySlider = document.getElementById('camera-sensitivity-slider');
    const cameraSensitivityValue = document.getElementById('camera-sensitivity-value');
    if (cameraSensitivitySlider && cameraSensitivityValue) {
        cameraSensitivityValue.textContent = cameraSensitivitySlider.value;
        CONFIG.gameMode.cameraSensitivity = parseInt(cameraSensitivitySlider.value);
        cameraSensitivitySlider.addEventListener('input', () => {
            const value = parseInt(cameraSensitivitySlider.value);
            cameraSensitivityValue.textContent = value;
            CONFIG.gameMode.cameraSensitivity = value;
            debugLog('[Config] 视角灵敏度', value);
        });
    }

    const pinchSensitivitySlider = document.getElementById('pinch-sensitivity-slider');
    const pinchSensitivityValue = document.getElementById('pinch-sensitivity-value');
    if (pinchSensitivitySlider && pinchSensitivityValue) {
        pinchSensitivitySlider.addEventListener('input', () => {
            const value = parseFloat(pinchSensitivitySlider.value);
            pinchSensitivityValue.textContent = value.toFixed(2).replace(/\.00$/, '');
            CONFIG.gameMode.pinchSensitivity = value;
            debugLog('[Config] 双指缩放灵敏度', value);
        });
    }

    const webrtcScaleSlider = document.getElementById('webrtc-scale-slider');
    const webrtcScaleValue = document.getElementById('webrtc-scale-value');
    if (webrtcScaleSlider && webrtcScaleValue) {
        webrtcScaleValue.textContent = parseFloat(webrtcScaleSlider.value).toFixed(1) + 'x';
        CONFIG.gameMode.webrtcScale = parseFloat(webrtcScaleSlider.value);
        webrtcScaleSlider.addEventListener('input', () => {
            const value = parseFloat(webrtcScaleSlider.value);
            webrtcScaleValue.textContent = value.toFixed(1) + 'x';
            CONFIG.gameMode.webrtcScale = value;
            emit('set_webrtc_scale', { scale: value });
        });
    }

    // 鏄剧ず榧犳爣绾㈢偣寮€鍏?
    const showCursorDotCheckbox = document.getElementById('show-cursor-dot');
    const cursorDotStatus = document.getElementById('cursor-dot-status');
    if (showCursorDotCheckbox && cursorDotStatus) {
        showCursorDotCheckbox.addEventListener('change', () => {
            CONFIG.gameMode.showCursorDot = showCursorDotCheckbox.checked;
            cursorDotStatus.textContent = showCursorDotCheckbox.checked ? '显示' : '隐藏';
            updateCursorDotVisibility();
            debugLog('[Config] 显示鼠标红点:', CONFIG.gameMode.showCursorDot);
        });
    }
}

// 鏇存柊榧犳爣绾㈢偣鏄剧ず鐘舵€?
function updateCursorDotVisibility() {
    const virtualCursor = document.getElementById('virtual-cursor');
    if (!virtualCursor) return;

    if (state.currentMode === 'controller') {
        virtualCursor.classList.add('hidden');
        virtualCursor.classList.remove('game-mode-cursor');
        return;
    }

    // 娓告垙妯″紡涓嬫牴鎹缃喅瀹氭槸鍚︽樉绀虹孩鐐?
    if (state.currentMode === 'gamepad') {
        virtualCursor.classList.remove('game-mode-cursor');
        if (CONFIG.gameMode.showCursorDot) {
            // 鏄剧ず绾㈢偣浣嗕娇鐢ㄥ崐閫忔槑鏍峰紡锛屽噺灏戣瑙夊共鎵?
            virtualCursor.classList.add('game-mode-cursor');
            virtualCursor.classList.remove('hidden');
        } else {
            // 瀹屽叏闅愯棌绾㈢偣
            virtualCursor.classList.add('hidden');
        }
    } else {
        // 闈炴父鎴忔ā寮忥紝绉婚櫎娓告垙妯″紡鏍峰紡
        virtualCursor.classList.remove('game-mode-cursor');
        // 瑙︽帶妯″紡涓嬬敱 updateVirtualCursorDisplay 鎺у埗鏄剧ず
    }
}

// ============ 鍒濆鍖?============
// Override: stable physical gamepad forwarding implementation.
function initPhysicalGamepadForwarding() {
    if (typeof navigator === 'undefined' || typeof navigator.getGamepads !== 'function') return;

    const toI16 = (v) => {
        const x = Math.max(-1, Math.min(1, v || 0));
        return Math.max(-32768, Math.min(32767, Math.round(x * 32767)));
    };

    const applyDeadzone = (v, dz = 0.08) => {
        const x = v || 0;
        return Math.abs(x) < dz ? 0 : x;
    };

    const getPadActivityScore = (p) => {
        if (!p || !p.connected) return -1;
        let score = 0;
        const axes = p.axes || [];
        const buttons = p.buttons || [];
        for (const a of axes) {
            score += Math.abs(a || 0);
        }
        for (const b of buttons) {
            if (!b) continue;
            score += (b.value || 0);
            if (b.pressed) score += 1.0;
        }
        return score;
    };

    const getActivePad = () => {
        const pads = navigator.getGamepads();
        if (!pads) return null;
        const connected = [];
        for (const p of pads) {
            if (p && p.connected) connected.push(p);
        }
        if (connected.length === 0) return null;

        let selected = null;
        if (state.physicalGamepad.index !== null && pads[state.physicalGamepad.index]) {
            selected = pads[state.physicalGamepad.index];
            if (!(selected && selected.connected)) {
                selected = null;
                state.physicalGamepad.index = null;
            }
        }

        let best = connected[0];
        let bestScore = getPadActivityScore(best);
        for (const p of connected) {
            const s = getPadActivityScore(p);
            if (s > bestScore) {
                best = p;
                bestScore = s;
            }
        }

        if (!selected) return best;
        const selectedScore = getPadActivityScore(selected);
        if (selectedScore <= 0.01 && bestScore > 0.2) {
            state.physicalGamepad.index = best.index;
            return best;
        }
        return selected;
    };

    const sendNeutral = () => {
        if (!state.connected) return;
        emit('xinput_state', { lx: 0, ly: 0, rx: 0, ry: 0, lt: 0, rt: 0, buttons: 0 });
        state.physicalGamepad.lastPayloadKey = '0,0,0,0,0,0,0';
    };

    const connectIfPossible = (gp) => {
        if (!state.connected || !state.physicalGamepad.enabled) return;
        if (!gp) gp = getActivePad();
        if (!gp || !gp.connected) return;

        const needConnectEvent = !state.physicalGamepad.connected || !state.physicalGamepad.serverAttached;
        state.physicalGamepad.active = true;
        state.physicalGamepad.connected = true;
        state.physicalGamepad.index = gp.index;
        state.physicalGamepad.missCount = 0;
        state.physicalGamepad.lastSentAt = 0;
        state.physicalGamepad.lastPayloadKey = '';
        state.physicalGamepad.lastConnectAt = Date.now();

        if (needConnectEvent) {
            emit('xinput_connect', { connected: true, id: gp.id || '' });
            state.physicalGamepad.serverAttached = true;
        }
        sendNeutral();
    };

    const disconnectNow = (hard = false) => {
        if (state.physicalGamepad.connected) {
            sendNeutral();
            if (hard && state.physicalGamepad.serverAttached) {
                emit('xinput_disconnect', {});
                state.physicalGamepad.serverAttached = false;
            }
        }
        state.physicalGamepad.active = false;
        state.physicalGamepad.connected = false;
        state.physicalGamepad.index = null;
        state.physicalGamepad.missCount = 0;
        state.physicalGamepad.lastSentAt = 0;
        state.physicalGamepad.lastPayloadKey = '';
        state.physicalGamepad.lastConnectAt = 0;
    };

    const pauseForwarding = () => {
        if (state.physicalGamepad.connected) {
            sendNeutral();
        }
        state.physicalGamepad.enabled = false;
        state.physicalGamepad.missCount = 0;
        state.physicalGamepad.lastSentAt = 0;
        state.physicalGamepad.lastPayloadKey = '0,0,0,0,0,0,0';
    };

    const pollOnce = () => {
        if (!state.physicalGamepad.enabled) return;
        if (!state.connected || document.hidden) return;

        const gp = getActivePad();
        if (!gp || !gp.connected) {
            state.physicalGamepad.missCount = (state.physicalGamepad.missCount || 0) + 1;
            if (state.physicalGamepad.connected && state.physicalGamepad.missCount > 30) {
                disconnectNow(false);
            }
            return;
        }
        state.physicalGamepad.missCount = 0;

        if (!state.physicalGamepad.connected) {
            connectIfPossible(gp);
            if (!state.physicalGamepad.connected) return;
        } else {
            const nowConnect = Date.now();
            if (!state.physicalGamepad.lastConnectAt || (nowConnect - state.physicalGamepad.lastConnectAt) > 1500) {
                state.physicalGamepad.lastConnectAt = nowConnect;
                emit('xinput_connect', { connected: true, id: gp.id || '' });
                state.physicalGamepad.serverAttached = true;
            }
        }

        const axes = gp.axes || [];
        const buttons = gp.buttons || [];
        const lx = toI16(applyDeadzone(axes[0]));
        const ly = toI16(applyDeadzone(-(axes[1] || 0)));
        const rx = toI16(applyDeadzone(axes[2] || 0));
        const ry = toI16(applyDeadzone(-(axes[3] || 0)));
        const lt = Math.max(0, Math.min(255, Math.round(((buttons[6] && buttons[6].value) || 0) * 255)));
        const rt = Math.max(0, Math.min(255, Math.round(((buttons[7] && buttons[7].value) || 0) * 255)));

        const pressed = (idx) => !!(buttons[idx] && buttons[idx].pressed);
        let mask = 0;
        if (pressed(12)) mask |= 0x0001;
        if (pressed(13)) mask |= 0x0002;
        if (pressed(14)) mask |= 0x0004;
        if (pressed(15)) mask |= 0x0008;
        if (pressed(9)) mask |= 0x0010;
        if (pressed(8)) mask |= 0x0020;
        if (pressed(10)) mask |= 0x0040;
        if (pressed(11)) mask |= 0x0080;
        if (pressed(4)) mask |= 0x0100;
        if (pressed(5)) mask |= 0x0200;
        if (pressed(16)) mask |= 0x0400;
        if (pressed(0)) mask |= 0x1000;
        if (pressed(1)) mask |= 0x2000;
        if (pressed(2)) mask |= 0x4000;
        if (pressed(3)) mask |= 0x8000;

        const key = `${lx},${ly},${rx},${ry},${lt},${rt},${mask}`;
        if (key === state.physicalGamepad.lastPayloadKey) return;

        const now = Date.now();
        const lastAt = state.physicalGamepad.lastSentAt || 0;
        if (now - lastAt < 16) return;

        state.physicalGamepad.lastSentAt = now;
        state.physicalGamepad.lastPayloadKey = key;
        emit('xinput_state', { lx, ly, rx, ry, lt, rt, buttons: mask });
    };

    state.physicalGamepad.setEnabled = (enabled) => {
        const on = !!enabled;
        if (!on) {
            pauseForwarding();
            return;
        }

        state.physicalGamepad.enabled = true;
        state.physicalGamepad.missCount = 0;
        state.physicalGamepad.lastConnectAt = 0;
        connectIfPossible();
        if (state.physicalGamepad.connected) {
            emit('xinput_connect', { connected: true, id: '' });
            state.physicalGamepad.serverAttached = true;
            sendNeutral();
        }
    };

    window.addEventListener('gamepadconnected', (e) => {
        const gp = e.gamepad;
        state.physicalGamepad.index = gp ? gp.index : state.physicalGamepad.index;
        if (state.physicalGamepad.enabled) {
            connectIfPossible(gp);
        }
    });

    window.addEventListener('gamepaddisconnected', (e) => {
        if (state.physicalGamepad.index === (e.gamepad && e.gamepad.index)) {
            disconnectNow(false);
        }
    });

    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            sendNeutral();
            return;
        }
        if (state.physicalGamepad.enabled) {
            connectIfPossible();
        }
    });

    window.addEventListener('beforeunload', () => {
        if (state.physicalGamepad.pollTimer !== null) {
            clearInterval(state.physicalGamepad.pollTimer);
            state.physicalGamepad.pollTimer = null;
        }
        disconnectNow(true);
    });

    if (state.physicalGamepad.pollTimer === null) {
        state.physicalGamepad.pollTimer = setInterval(pollOnce, 16);
    }
}

function init() {
    initSocket();
    initAudioUnlockControls();
    initTouchMode();
    initGamepadMode();
    initPhysicalGamepadForwarding();
    initKeyboardMode();
    initHardwareKeyboardForwarding();
    initModeSwitching();
    initSettings();
    updateFPS();

    // 闃叉椤甸潰婊氬姩鍜岀缉鏀?
    document.addEventListener('touchmove', (e) => {
        if (e.target.closest('#touch-overlay') ||
            e.target.closest('.virtual-stick') ||
            e.target.closest('.action-btn') ||
            e.target.closest('.extra-btn') ||
            e.target.closest('.mouse-btn') ||
            e.target.closest('.kb-key')) {
            e.preventDefault();
        }
    }, { passive: false });

    document.addEventListener('gesturestart', (e) => e.preventDefault());
    document.addEventListener('gesturechange', (e) => e.preventDefault());
    document.addEventListener('gestureend', (e) => e.preventDefault());

    // 闃叉鍙屽嚮缂╂斁
    let lastTouchEnd = 0;
    document.addEventListener('touchend', (e) => {
        const now = Date.now();
        if (now - lastTouchEnd <= 300) {
            e.preventDefault();
        }
        lastTouchEnd = now;
    }, false);

    debugLog('[App] 初始化完成，低延迟模式:', CONFIG.lowLatencyMode);
}

// 椤甸潰鍔犺浇瀹屾垚鍚庡垵濮嬪寲
document.addEventListener('DOMContentLoaded', init);

