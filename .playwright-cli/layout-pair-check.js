async (page) => {
  await page.waitForLoadState('domcontentloaded');
  await page.evaluate(() => {
    const sections = document.getElementById('config-sections');
    if (sections) {
      sections.innerHTML = Array.from({ length: 5 }).map((_, groupIndex) => `
        <section class="config-group">
          <div class="config-group-head"><h3>分组 ${groupIndex + 1}</h3><span class="field-meta">共 4 项</span></div>
          <div class="config-group-grid">
            ${Array.from({ length: 4 }).map((__, fieldIndex) => `
              <article class="field-card">
                <div class="field-head"><div><h4 class="field-title">配置 ${groupIndex + 1}-${fieldIndex + 1}</h4><p class="field-description">测试左右面板等高，右侧日志不再悬空。</p></div></div>
                <input class="config-input" type="text" value="示例值" />
              </article>
            `).join('')}
          </div>
        </section>
      `).join('');
    }
    const stream = document.getElementById('logs-stream');
    if (stream) {
      stream.textContent = Array.from({ length: 260 }).map((_, i) => `[14:${String(i % 60).padStart(2, '0')}:38] 输出 第 ${i + 1} 行日志内容，用于验证日志面板与左侧同高且仅内部滚动。`).join('\n');
      stream.scrollTop = stream.scrollHeight;
    }
    const status = document.getElementById('logs-status-text');
    if (status) status.textContent = '当前视图 260 行，日志仅在右侧内部滚动';
    window.dispatchEvent(new Event('resize'));
  });
  await page.waitForTimeout(200);
}
