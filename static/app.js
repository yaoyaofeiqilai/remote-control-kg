/**
 * 远程控制客户端 - 平板端控制界面
 * 优化版本：低延迟、无遮挡UI
 */

// ============ 全局配置 ============
const CONFIG = {
    mouseSensitivity: 1.5,
    deadzone: 0.2,
    maxStickDistance: 90,
    lowLatencyMode: true,  // 低延迟模式
    touchThrottleMs: 8,    // 触摸节流(约120Hz)
    // 游戏模式专用配置
    gameMode: {
        cameraSensitivity: 30,   // 视角灵敏度 (降低后的默认值)
        pinchSensitivity: 0.25,  // 双指缩放灵敏度（deltaDist -> 滚轮 dy）
        showCursorDot: true,      // 是否显示鼠标红点
    }
};

// ============ 状态管理 ============
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
    fps: 0,
    frameCount: 0,
    lastFpsUpdate: Date.now(),
};

function isGamepadPointerActive() {
    return state.gamepadAltLocked || state.gamepadTabWheelActive;
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
        console.log('[Socket] 已连接');
        state.connected = true;
        statusEl.textContent = '已连接';
        statusEl.className = 'connected';
    });

    state.socket.on('disconnect', () => {
        console.log('[Socket] 已断开');
        state.connected = false;
        statusEl.textContent = '已断开';
        statusEl.className = 'disconnected';
    });

    state.socket.on('connect_error', (err) => {
        console.error('[Socket] 连接错误:', err);
        statusEl.textContent = '连接失败';
        statusEl.className = 'disconnected';
    });

    state.socket.on('connected', (data) => {
        state.screenWidth = data.screen_width;
        state.screenHeight = data.screen_height;
        console.log('[Socket] 屏幕尺寸:', state.screenWidth, 'x', state.screenHeight);

        // 初始化虚拟鼠标位置为屏幕中心
        if (!state.virtualMouse) {
            state.virtualMouse = { x: state.screenWidth / 2, y: state.screenHeight / 2 };
        }

        // 开始同步鼠标位置
        startMouseSync();
    });

    // 监听服务端返回的鼠标位置
    state.socket.on('mouse_pos', (data) => {
        if (!state.virtualMouse) return;

        // 如果在触摸状态，检查偏差是否过大，需要时校准
        if (state.isTouching) {
            // 在触摸模式下，只有偏差过大才校准（某些窗口会捕获鼠标）
            const dx = Math.abs(state.virtualMouse.x - data.x);
            const dy = Math.abs(state.virtualMouse.y - data.y);
            if (dx > 200 || dy > 200) {
                console.log(`[警告] 触摸时位置偏差过大 (${dx.toFixed(0)}, ${dy.toFixed(0)})`);
                // 不立即校准，避免跳跃，但记录问题
            }
        } else {
            // 非触摸状态，直接同步服务端位置
            state.virtualMouse.x = data.x;
            state.virtualMouse.y = data.y;
            updateVirtualCursorDisplay();
        }
    });

    // 更新视频流连接 - 添加时间戳防止缓存
    const screenImg = document.getElementById('screen');
    screenImg.src = '/video?' + Date.now();
}

// 定期同步鼠标位置（每50ms）
let mouseSyncInterval = null;

function startMouseSync() {
    if (mouseSyncInterval) return;
    mouseSyncInterval = setInterval(() => {
        if (state.connected && !state.isTouching) {
            emit('get_mouse_pos');
        }
    }, 50);
}

function stopMouseSync() {
    if (mouseSyncInterval) {
        clearInterval(mouseSyncInterval);
        mouseSyncInterval = null;
    }
}

// 更新虚拟指针显示位置
function updateVirtualCursorDisplay() {
    const virtualCursor = document.getElementById('virtual-cursor');
    if (!virtualCursor || !state.virtualMouse) return;

    // 游戏模式下根据设置决定是否显示红点
    if (state.currentMode === 'gamepad' && !isGamepadPointerActive() && !CONFIG.gameMode.showCursorDot) {
        virtualCursor.classList.add('hidden');
        return;
    }

    const screenEl = document.getElementById('screen');
    const rect = screenEl.getBoundingClientRect();

    // 计算缩放比例
    const scaleX = rect.width / state.screenWidth;
    const scaleY = rect.height / state.screenHeight;

    // 计算显示位置
    const displayX = rect.left + state.virtualMouse.x * scaleX;
    const displayY = rect.top + state.virtualMouse.y * scaleY;

    virtualCursor.style.left = displayX + 'px';
    virtualCursor.style.top = displayY + 'px';
    virtualCursor.classList.remove('hidden');
}

// ============ 触摸坐标转换 ============
function getRelativeCoordinates(touch, element) {
    const rect = element.getBoundingClientRect();
    const img = document.getElementById('screen');
    // 使用实际显示尺寸计算比例
    const scaleX = state.screenWidth / rect.width;
    const scaleY = state.screenHeight / rect.height;

    return {
        x: Math.round((touch.clientX - rect.left) * scaleX),
        y: Math.round((touch.clientY - rect.top) * scaleY),
    };
}

// 节流函数
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

// ============ 触摸板模式控制 ============
// 对标笔记本触控板逻辑：
// - 单指移动 = 鼠标移动（不触发点击）
// - 单指点击 = 左键单击（延迟确认，避免与双击冲突）
// - 双击并按住（第二次点击不释放）+ 移动 = 拖拽（可拖动窗口）
// - 双指点击 = 右键
// - 双指滑动 = 滚轮（上下左右四向）
function initTouchMode() {
    const overlay = document.getElementById('touch-overlay');
    const virtualCursor = document.getElementById('virtual-cursor');

    // 触摸板状态
    let touchState = {
        touchCount: 0,
        startX: 0,
        startY: 0,
        lastX: 0,
        lastY: 0,
        startTime: 0,
        isMoving: false,
        hasMoved: false,
        isDragging: false,      // 是否正在拖拽（双击并按住）
        leftButtonDown: false,  // 左键是否按下
        isSecondTap: false,     // 是否是双击中的第二次点击
        pendingClick: false,    // 是否有待确认的单击
    };

    // 双击检测
    let lastTapTime = 0;
    let lastTapX = 0;
    let lastTapY = 0;
    let clickTimer = null;    // 用于延迟执行单击

    // 常量
    const DOUBLE_TAP_TIME = 800;      // 双击时间窗口（毫秒）
    const DOUBLE_TAP_DISTANCE = 100;  // 双击最大距离（像素）
    const CLICK_DELAY = 200;          // 单击延迟时间（等待确认不是双击）

    // 获取灵敏度配置
    function getSensitivity() {
        return CONFIG.mouseSensitivity || 1.5;
    }

    // 确保虚拟鼠标已初始化
    if (!state.virtualMouse) {
        state.virtualMouse = {
            x: state.screenWidth / 2,
            y: state.screenHeight / 2,
        };
    }

    // 偏差阈值 - 超过此值时进行校准
    const POS_SYNC_THRESHOLD = 100;

    // 游戏模式下：全屏滑动 = 视角；Alt 锁定时滑动 = 光标
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
                if (Math.abs(dx) > 0.2 || Math.abs(dy) > 0.2) {
                    state.virtualMouse.x += dx;
                    state.virtualMouse.y += dy;
                    state.virtualMouse.x = Math.max(0, Math.min(state.virtualMouse.x, state.screenWidth));
                    state.virtualMouse.y = Math.max(0, Math.min(state.virtualMouse.y, state.screenHeight));
                    updateVirtualCursorDisplay();
                    emit('mouse_move_relative', { dx: dx, dy: dy, raw: false });
                }
            } else {
                const scale = CONFIG.gameMode.cameraSensitivity / 30;
                const dx = deltaX * scale;
                const dy = deltaY * scale;
                if (Math.abs(dx) > 0.2 || Math.abs(dy) > 0.2) {
                    emit('mouse_move_relative', { dx: dx, dy: dy, raw: true });
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

    // 发送相对移动命令到服务端
    function sendRelativeMove(dx, dy) {
        if (!state.virtualMouse) {
            state.virtualMouse = {
                x: state.screenWidth / 2,
                y: state.screenHeight / 2,
            };
        }

        // 更新本地虚拟鼠标位置
        state.virtualMouse.x += dx;
        state.virtualMouse.y += dy;

        // 限制在屏幕范围内
        state.virtualMouse.x = Math.max(0, Math.min(state.virtualMouse.x, state.screenWidth));
        state.virtualMouse.y = Math.max(0, Math.min(state.virtualMouse.y, state.screenHeight));

        // 更新显示
        updateVirtualCursorDisplay();

        // 发送到服务端
        emit('mouse_move_relative', { dx: dx, dy: dy });
    }

    // 发送绝对位置（用于校准）
    function sendAbsoluteMove(x, y) {
        state.virtualMouse.x = Math.max(0, Math.min(x, state.screenWidth));
        state.virtualMouse.y = Math.max(0, Math.min(y, state.screenHeight));
        updateVirtualCursorDisplay();
        emit('mouse_move', {
            x: Math.round(state.virtualMouse.x),
            y: Math.round(state.virtualMouse.y)
        });
    }

    // 检查并校准位置（如果偏差过大）
    function checkAndCalibratePosition(serverX, serverY) {
        const dx = Math.abs(state.virtualMouse.x - serverX);
        const dy = Math.abs(state.virtualMouse.y - serverY);

        // 如果偏差超过阈值，进行校准（但只在非拖拽模式下）
        if ((dx > POS_SYNC_THRESHOLD || dy > POS_SYNC_THRESHOLD) && !touchState.isDragging) {
            console.log(`[校准] 位置偏差过大 (${dx.toFixed(0)}, ${dy.toFixed(0)})，进行校准`);
            state.virtualMouse.x = serverX;
            state.virtualMouse.y = serverY;
            updateVirtualCursorDisplay();
        }
    }

    // 执行单击
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

    // 点击动画
    function playClickAnimation() {
        virtualCursor.classList.add('clicking');
        setTimeout(() => {
            virtualCursor.classList.remove('clicking');
        }, 150);
    }

    // 取消待处理的单击
    function cancelPendingClick() {
        if (clickTimer) {
            clearTimeout(clickTimer);
            clickTimer = null;
        }
        touchState.pendingClick = false;
    }

    // 触摸开始
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

        // 检测双击（第二次点击）
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

            // 触摸开始时，发送绝对位置进行校准（确保客户端和服务端位置一致）
            // 这很重要，因为某些窗口会捕获/重置鼠标位置
            sendAbsoluteMove(state.virtualMouse.x, state.virtualMouse.y);

            // 如果是双击，进入拖拽模式
            if (isDoubleTap) {
                // 取消待处理的单击
                cancelPendingClick();
                touchState.isSecondTap = true;
                touchState.isDragging = true;
                touchState.leftButtonDown = true;
                // 发送 left down（开始拖拽）
                emit('mouse_click', { button: 'left', action: 'down' });
                playClickAnimation();
                console.log('[触控] 进入拖拽模式');
            } else {
                // 第一次点击，不立即执行，延迟等待确认是否是双击
                touchState.isSecondTap = false;
                touchState.pendingClick = true;
                clickTimer = setTimeout(() => {
                    // 延迟后执行单击
                    if (touchState.pendingClick) {
                        touchState.pendingClick = false;
                        doClick();
                    }
                }, CLICK_DELAY);
            }

        } else if (e.touches.length === 2) {
            // 双指按下 - 取消单击，准备右键或滚轮
            cancelPendingClick();

            const touch1 = e.touches[0];
            const touch2 = e.touches[1];
            touchState.startX = (touch1.clientX + touch2.clientX) / 2;
            touchState.startY = (touch1.clientY + touch2.clientY) / 2;
            touchState.lastX = touchState.startX;
            touchState.lastY = touchState.startY;

            // 如果之前有左键按住，抬起它
            if (touchState.leftButtonDown) {
                emit('mouse_click', { button: 'left', action: 'up' });
                touchState.leftButtonDown = false;
                touchState.isDragging = false;
            }
        }
    }, { passive: false });

    // 触摸移动
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
            // 单指移动 - 控制鼠标或拖拽
            const touch = e.touches[0];

            // 计算移动差值
            const sens = getSensitivity();
            const dx = (touch.clientX - touchState.lastX) * sens;
            const dy = (touch.clientY - touchState.lastY) * sens;

            // 判断是否开始移动
            const totalMoveX = Math.abs(touch.clientX - touchState.startX);
            const totalMoveY = Math.abs(touch.clientY - touchState.startY);

            if (totalMoveX > 3 || totalMoveY > 3) {
                touchState.isMoving = true;
                touchState.hasMoved = true;
                // 注意：单指滑动只是移动鼠标，不会自动进入拖拽模式
                // 拖拽需要通过双击并按住来实现
            }

            // 发送鼠标移动（无论是否拖拽，都要移动鼠标）
            sendRelativeMove(Math.round(dx), Math.round(dy));

            // 更新最后位置
            touchState.lastX = touch.clientX;
            touchState.lastY = touch.clientY;

        } else if (e.touches.length === 2) {
            // 双指移动 - 滚轮（支持上下左右）
            const touch1 = e.touches[0];
            const touch2 = e.touches[1];
            const centerX = (touch1.clientX + touch2.clientX) / 2;
            const centerY = (touch1.clientY + touch2.clientY) / 2;

            if (touchState.lastX !== 0 && touchState.lastY !== 0) {
                const deltaX = centerX - touchState.lastX;
                const deltaY = centerY - touchState.lastY;

                // 双指滑动映射为滚轮
                // 垂直滑动 = 上下滚动，水平滑动 = 左右滚动
                const scrollSensitivity = 3;
                emit('mouse_scroll', {
                    dx: Math.round(deltaX * scrollSensitivity),
                    dy: Math.round(-deltaY * scrollSensitivity)
                });
            }

            touchState.lastX = centerX;
            touchState.lastY = centerY;
            touchState.hasMoved = true;
        }
    }, { passive: false });

    // 触摸结束
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

        // 双指检测：如果开始时是双指
        if (touchState.touchCount === 2) {
            // 双指点击（没有移动）= 右键
            if (touchDuration < 300 && !touchState.hasMoved) {
                playClickAnimation();
                emit('mouse_click', { button: 'right', action: 'down' });
                setTimeout(() => {
                    emit('mouse_click', { button: 'right', action: 'up' });
                }, 50);
            }

            if (remainingTouches === 0) {
                // 所有手指都抬起
                state.isTouching = false;
                touchState.touchCount = 0;
                touchState.isMoving = false;
                touchState.hasMoved = false;
                touchState.isDragging = false;
            } else {
                // 还剩一根手指，转为单指状态
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

        // 单指处理
        if (remainingTouches === 0) {
            const touch = e.changedTouches[0];
            const now = Date.now();

            if (touchState.isDragging) {
                // 拖拽模式结束（双击后按住），抬起左键
                emit('mouse_click', { button: 'left', action: 'up' });
                touchState.leftButtonDown = false;
                touchState.isDragging = false;
                touchState.isSecondTap = false;

                // 记录本次点击，但不作为双击的第一次点击（避免三击误判）
                lastTapTime = 0;
                lastTapX = 0;
                lastTapY = 0;
            } else if (touchState.leftButtonDown) {
                // 确保左键抬起
                emit('mouse_click', { button: 'left', action: 'up' });
                touchState.leftButtonDown = false;
            } else if (!touchState.hasMoved && touchDuration < 300 && touchState.pendingClick) {
                // 短按且没有移动，且有待确认的单击
                // 让 timer 去处理单击（延迟执行）
                // 记录本次点击用于双击检测
                lastTapTime = now;
                lastTapX = touch.clientX;
                lastTapY = touch.clientY;
            } else if (!touchState.hasMoved && touchDuration >= 300) {
                // 长按没有移动，执行单击（取消待处理状态直接执行）
                cancelPendingClick();
                doClick();
            } else {
                // 移动了，取消单击
                cancelPendingClick();
            }

            // 重置状态
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

// ============ 游戏手柄模式 ============
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

// ============ 键盘模式 ============
function initKeyboardMode() {
    const keys = document.querySelectorAll('.kb-key');
    const pressedKeys = new Set();

    keys.forEach(key => {
        const keyName = key.dataset.key;

        key.addEventListener('touchstart', (e) => {
            e.preventDefault();
            key.classList.add('pressed');

            // 特殊处理锁定键
            if (keyName === 'CapsLock') {
                key.classList.toggle('locked');
            }

            emit('key_event', { key: keyName, action: 'down' });
            pressedKeys.add(keyName);
        }, { passive: false });

        key.addEventListener('touchend', (e) => {
            e.preventDefault();
            key.classList.remove('pressed');

            // CapsLock 和其他锁定键不需要发送 up 事件（它会保持状态）
            if (keyName !== 'CapsLock') {
                emit('key_event', { key: keyName, action: 'up' });
            }
            pressedKeys.delete(keyName);
        });

        // 防止触摸时触发默认行为
        key.addEventListener('touchmove', (e) => {
            e.preventDefault();
        }, { passive: false });
    });

    // 防止键盘区域的默认触摸行为
    const keyboardControls = document.getElementById('keyboard-controls');
    if (keyboardControls) {
        keyboardControls.addEventListener('touchstart', (e) => {
            if (e.target.closest('.kb-key')) {
                e.preventDefault();
            }
        }, { passive: false });
    }
}

// ============ 模式切换 ============
function initModeSwitching() {
    const modeBtns = document.querySelectorAll('.mode-btn');
    const touchOverlay = document.getElementById('touch-overlay');
    const gamepadControls = document.getElementById('gamepad-controls');
    const keyboardControls = document.getElementById('keyboard-controls');
    const modeIndicator = document.getElementById('mode-indicator');
    const modeDescription = document.getElementById('mode-description');

    const modeNames = {
        'touch': '触控模式',
        'gamepad': '游戏模式',
        'keyboard': '键盘模式'
    };

    const modeDescs = {
        'touch': '触控板模式：单指移动=光标，单指点击=左键，双击并按住=拖拽，双指点击=右键，双指滑动=滚轮',
        'gamepad': '左摇杆=WASD，右侧滑动=视角，右侧按钮=技能/普攻，Alt=长按切换',
        'keyboard': '虚拟键盘输入，支持组合键'
    };

    modeBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const prevMode = state.currentMode;
            const mode = btn.dataset.mode;

            modeBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            state.currentMode = mode;

            // 更新指示器
            modeIndicator.textContent = modeNames[mode];
            if (modeDescription) {
                modeDescription.textContent = modeDescs[mode];
            }

            // 通知服务端模式切换
            emit('set_mode', { mode: mode });

            if (prevMode === 'gamepad' && mode !== 'gamepad') {
                releaseGamepadToggles();
            }

            // 切换游戏模式设置显示
            const gameModeSettings = document.getElementById('game-mode-settings');
            if (gameModeSettings) {
                if (mode === 'gamepad') {
                    gameModeSettings.classList.remove('hidden');
                } else {
                    gameModeSettings.classList.add('hidden');
                }
            }

            // 更新鼠标红点显示状态
            updateCursorDotVisibility();

            // 切换显示
            switch (mode) {
                case 'touch':
                    touchOverlay.style.display = 'block';
                    gamepadControls.classList.add('hidden');
                    keyboardControls.classList.add('hidden');
                    break;
                case 'gamepad':
                    touchOverlay.style.display = 'block';
                    gamepadControls.classList.remove('hidden');
                    keyboardControls.classList.add('hidden');
                    break;
                case 'keyboard':
                    touchOverlay.style.display = 'none';
                    gamepadControls.classList.add('hidden');
                    keyboardControls.classList.remove('hidden');
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

    // 画质滑块
    const qualitySlider = document.getElementById('quality-slider');
    const qualityValue = document.getElementById('quality-value');
    qualitySlider.addEventListener('input', () => {
        qualityValue.textContent = qualitySlider.value;
        emit('set_quality', { quality: parseInt(qualitySlider.value) });
    });

    // 帧率滑块
    const fpsSlider = document.getElementById('fps-slider');
    const fpsValue = document.getElementById('fps-value');
    fpsSlider.addEventListener('input', () => {
        fpsValue.textContent = fpsSlider.value;
        emit('set_fps', { fps: parseInt(fpsSlider.value) });
    });

    // 灵敏度滑块
    const sensitivitySlider = document.getElementById('sensitivity-slider');
    const sensitivityValue = document.getElementById('sensitivity-value');
    sensitivitySlider.addEventListener('input', () => {
        const value = sensitivitySlider.value;
        sensitivityValue.textContent = value + 'x';
        CONFIG.mouseSensitivity = parseFloat(value);
    });

    // 低延迟模式
    const lowLatencyCheckbox = document.getElementById('low-latency-mode');
    if (lowLatencyCheckbox) {
        lowLatencyCheckbox.addEventListener('change', () => {
            CONFIG.lowLatencyMode = lowLatencyCheckbox.checked;
            console.log('[Config] 低延迟模式:', CONFIG.lowLatencyMode);
        });
    }

    // 游戏模式专用设置
    initGameModeSettings();

    // 全屏按钮
    fullscreenBtn.addEventListener('click', () => {
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen();
        } else {
            document.exitFullscreen();
        }
    });

    // 打开/关闭设置
    settingsBtn.addEventListener('click', () => {
        settingsPanel.classList.remove('hidden');
    });

    closeSettings.addEventListener('click', () => {
        settingsPanel.classList.add('hidden');
    });

    // 点击面板外部关闭
    settingsPanel.addEventListener('click', (e) => {
        if (e.target === settingsPanel) {
            settingsPanel.classList.add('hidden');
        }
    });
}

// ============ 辅助函数 ============
function emit(event, data) {
    if (state.connected && state.socket) {
        state.socket.emit(event, data);
    }
}

// FPS 计算
function updateFPS() {
    state.frameCount++;
    const now = Date.now();
    const elapsed = now - state.lastFpsUpdate;

    if (elapsed >= 1000) {
        state.fps = Math.round((state.frameCount * 1000) / elapsed);
        document.getElementById('fps-counter').textContent = state.fps + ' FPS';
        state.frameCount = 0;
        state.lastFpsUpdate = now;
    }

    requestAnimationFrame(updateFPS);
}

// ============ 游戏模式设置 ============
function initGameModeSettings() {
    // 视角灵敏度滑块
    const cameraSensitivitySlider = document.getElementById('camera-sensitivity-slider');
    const cameraSensitivityValue = document.getElementById('camera-sensitivity-value');
    if (cameraSensitivitySlider && cameraSensitivityValue) {
        cameraSensitivitySlider.addEventListener('input', () => {
            const value = parseInt(cameraSensitivitySlider.value);
            cameraSensitivityValue.textContent = value;
            CONFIG.gameMode.cameraSensitivity = value;
            console.log('[Config] 视角灵敏度:', value);
        });
    }

    const pinchSensitivitySlider = document.getElementById('pinch-sensitivity-slider');
    const pinchSensitivityValue = document.getElementById('pinch-sensitivity-value');
    if (pinchSensitivitySlider && pinchSensitivityValue) {
        pinchSensitivitySlider.addEventListener('input', () => {
            const value = parseFloat(pinchSensitivitySlider.value);
            pinchSensitivityValue.textContent = value.toFixed(2).replace(/\.00$/, '');
            CONFIG.gameMode.pinchSensitivity = value;
            console.log('[Config] 双指缩放灵敏度:', value);
        });
    }

    // 显示鼠标红点开关
    const showCursorDotCheckbox = document.getElementById('show-cursor-dot');
    const cursorDotStatus = document.getElementById('cursor-dot-status');
    if (showCursorDotCheckbox && cursorDotStatus) {
        showCursorDotCheckbox.addEventListener('change', () => {
            CONFIG.gameMode.showCursorDot = showCursorDotCheckbox.checked;
            cursorDotStatus.textContent = showCursorDotCheckbox.checked ? '显示' : '隐藏';
            updateCursorDotVisibility();
            console.log('[Config] 显示鼠标红点:', CONFIG.gameMode.showCursorDot);
        });
    }
}

// 更新鼠标红点显示状态
function updateCursorDotVisibility() {
    const virtualCursor = document.getElementById('virtual-cursor');
    if (!virtualCursor) return;

    // 游戏模式下根据设置决定是否显示红点
    if (state.currentMode === 'gamepad') {
        virtualCursor.classList.remove('game-mode-cursor');
        if (CONFIG.gameMode.showCursorDot) {
            // 显示红点但使用半透明样式，减少视觉干扰
            virtualCursor.classList.add('game-mode-cursor');
            virtualCursor.classList.remove('hidden');
        } else {
            // 完全隐藏红点
            virtualCursor.classList.add('hidden');
        }
    } else {
        // 非游戏模式，移除游戏模式样式
        virtualCursor.classList.remove('game-mode-cursor');
        // 触控模式下由 updateVirtualCursorDisplay 控制显示
        // 键盘模式下保持隐藏
        if (state.currentMode === 'keyboard') {
            virtualCursor.classList.add('hidden');
        }
    }
}

// ============ 初始化 ============
function init() {
    initSocket();
    initTouchMode();
    initGamepadMode();
    initKeyboardMode();
    initModeSwitching();
    initSettings();
    updateFPS();

    // 防止页面滚动和缩放
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

    // 防止双击缩放
    let lastTouchEnd = 0;
    document.addEventListener('touchend', (e) => {
        const now = Date.now();
        if (now - lastTouchEnd <= 300) {
            e.preventDefault();
        }
        lastTouchEnd = now;
    }, false);

    console.log('[App] 初始化完成，低延迟模式:', CONFIG.lowLatencyMode);
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', init);
