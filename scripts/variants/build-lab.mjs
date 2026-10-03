import { build } from 'esbuild';
await build({entryPoints:['src/variants/node-cli.ts'],outfile:'build/variants/cli.mjs',bundle:true,platform:'node',format:'esm',target:'node22',external:['onnxruntime-node'],sourcemap:true});
console.log('Variant referee and experiment runner: build/variants/cli.mjs');
