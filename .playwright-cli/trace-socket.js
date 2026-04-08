async (page) => {
  await page.addInitScript(() => {
    window.__socketTrace = [];
    const wrapFactory = (factory) => {
      if (typeof factory !== 'function' || factory.__traceWrapped) return factory;
      const wrapped = function (...args) {
        const socket = factory.apply(this, args);
        try {
          window.__socketTrace.push({ dir: 'construct', t: Date.now() });
          if (socket && typeof socket.onAny === 'function') {
            socket.onAny((event, ...payload) => {
              try {
                window.__socketTrace.push({ dir: 'in', event, payload, t: Date.now() });
              } catch (e) {}
            });
          } else if (socket && typeof socket.onevent === 'function') {
            const origOnevent = socket.onevent;
            socket.onevent = function (packet) {
              try {
                const data = Array.isArray(packet && packet.data) ? packet.data : [];
                window.__socketTrace.push({ dir: 'in', event: data[0], payload: data.slice(1), t: Date.now() });
              } catch (e) {}
              return origOnevent.apply(this, arguments);
            };
          }
          if (socket && typeof socket.emit === 'function') {
            const origEmit = socket.emit;
            socket.emit = function (...emitArgs) {
              try {
                window.__socketTrace.push({ dir: 'out', event: emitArgs[0], payload: emitArgs.slice(1), t: Date.now() });
              } catch (e) {}
              return origEmit.apply(this, emitArgs);
            };
          }
        } catch (e) {}
        return socket;
      };
      Object.assign(wrapped, factory);
      wrapped.__traceWrapped = true;
      return wrapped;
    };

    let currentIo;
    Object.defineProperty(window, 'io', {
      configurable: true,
      enumerable: true,
      get() {
        return currentIo;
      },
      set(value) {
        currentIo = wrapFactory(value);
      },
    });
  });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(4000);
}
