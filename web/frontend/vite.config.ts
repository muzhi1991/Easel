import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), {
    name: 'easel-offline-shell',
    apply: 'build',
    generateBundle(_, bundle) {
      const files = ['./', 'manifest.webmanifest', 'app-icon.png', ...Object.keys(bundle).filter(name => name.startsWith('assets/'))];
      const hash = createHash('sha256');
      for (const name of Object.keys(bundle).sort()) {
        const output = bundle[name];
        hash.update(name).update(output.type === 'chunk' ? output.code : output.source);
      }
      for (const name of ['public/manifest.webmanifest', 'public/app-icon.png', 'sw-template.js']) hash.update(readFileSync(new URL(name, import.meta.url)));
      const worker = readFileSync(new URL('sw-template.js', import.meta.url), 'utf8')
        .replace('__PRECACHE_FILES__', JSON.stringify(files))
        .replace('__BUILD_VERSION__', hash.digest('hex').slice(0, 16));
      this.emitFile({ type: 'asset', fileName: 'sw.js', source: worker });
    },
  }],
  base: './',  // 相对路径，适配 proxy
})
