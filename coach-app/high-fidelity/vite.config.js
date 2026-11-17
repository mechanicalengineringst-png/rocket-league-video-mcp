import { defineConfig } from 'vite';
import wasm from 'vite-plugin-wasm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const directory = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  // FastAPI serves the built page and all lazy WASM/3D asset requests locally.
  base: '/static/hd-player/',
  plugins: [wasm()],
  // @rlrml/player 1.5.1 ships GLBs and Draco/skyboxes in its npm package.
  // They are copied at build time to the user's private local environment,
  // not committed to this repository. Reuse/distribution rights for bundled
  // Rocket League-derived art are NOT established by the MIT software license.
  publicDir: path.join(directory, 'node_modules/@rlrml/player/public'),
  build: {
    target: 'esnext',
    outDir: path.resolve(directory, '../coach_app/static/hd-player'),
    emptyOutDir: true,
    sourcemap: false,
  },
  optimizeDeps: { exclude: ['@rlrml/subtr-actor'] },
  worker: { plugins: () => [wasm()] },
  server: { host: '127.0.0.1', port: 5178 },
});
