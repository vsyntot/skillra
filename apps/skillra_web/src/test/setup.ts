import '@testing-library/jest-dom'

// Mock ResizeObserver — not available in jsdom
if (typeof ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}
