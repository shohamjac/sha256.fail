import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  // Relative asset paths, so the built site works at any URL (a domain root or a
  // GitHub Pages project path) without rebuilding.
  base: './',
  plugins: [react()],
  test: { environment: 'node' },
});
