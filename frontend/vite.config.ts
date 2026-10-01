import { defineConfig } from 'vite';

// No @vitejs/plugin-react on purpose: JSX is handled by esbuild's automatic
// runtime directly, which keeps the dependency set to react + react-dom +
// vite + typescript only. No React Fast Refresh in dev, but HMR still works
// at the module level.
export default defineConfig({
  esbuild: {
    jsx: 'automatic',
  },
  server: {
    port: 5173,
    strictPort: true,
    host: '127.0.0.1',
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
