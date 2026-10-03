import * as ort from 'onnxruntime-web/wasm';
import wasmUrl from 'onnxruntime-web/ort-wasm-simd-threaded.wasm?url';
import mjsUrl from 'onnxruntime-web/ort-wasm-simd-threaded.mjs?url';
import { encode, INPUT_SIZE, verifyManifest, type Evaluator } from './features';
import { search } from './search';
import type { ModelManifest, Observation } from './types';
ort.env.wasm.numThreads=1;
ort.env.wasm.wasmPaths={wasm:wasmUrl,mjs:mjsUrl};
let evaluate:Evaluator|undefined,manifest:ModelManifest|undefined;
self.onmessage=async(event:MessageEvent)=>{
  const {id,method,params:p}=event.data;
  try{
    if(method==='clearModel'){evaluate=undefined;manifest=undefined;self.postMessage({id,ok:true,data:null});return;}
    if(method==='model'){
      verifyManifest(p.manifest,p.observation);
      const bytes=p.bytes as ArrayBuffer;
      const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');
      if(digest!==p.manifest.sha256)throw new Error('模型文件 SHA256 不匹配');
      const session=await ort.InferenceSession.create(bytes,{executionProviders:['wasm']});manifest=p.manifest;
      evaluate=async(o:Observation)=>{verifyManifest(manifest!,o);const result=await session.run({observation:new ort.Tensor('float32',encode(o),[1,INPUT_SIZE])});return {policy:result.policy.data as Float32Array,value:Number(result.value.data[0])};};
      self.postMessage({id,ok:true,data:{name:manifest!.sha256.slice(0,12)}});return;
    }
    if(method==='evaluate'){if(!evaluate)throw new Error('没有模型');const data=await evaluate(p.observation);self.postMessage({id,ok:true,data});return;}
    if(manifest)verifyManifest(manifest,p.observation);
    const data=await search(p.observation,p.budget,evaluate);
    self.postMessage({id,ok:true,data});
  }catch(e){self.postMessage({id,ok:false,error:e instanceof Error?e.message:String(e)});}
};
