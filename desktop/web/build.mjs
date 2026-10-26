import { mkdir, copyFile, cp } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
await build({entryPoints: ['app', 'markdown', 'monitor'].map(name => fileURLToPath(new URL(`./src/${name}.ts`, import.meta.url))), bundle:true, splitting:true, format:'esm', target:'es2022', outdir:fileURLToPath(new URL('./dist/', import.meta.url))});
await mkdir(new URL('./dist/', import.meta.url), { recursive: true });
await cp(new URL('../../docs/licenses/', import.meta.url), new URL('./dist/licenses/', import.meta.url), {recursive:true});
for (const name of ['index.html', 'style.css', 'markdown.css', 'reader.css', 'monitor.css']) {
  await copyFile(new URL(name, import.meta.url), new URL(`dist/${name}`, import.meta.url));
}
