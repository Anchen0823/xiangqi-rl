import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';
import { installPreviewBridge } from './mock-bridge';
import { LabApp } from './LabApp';
import './styles.css';
import './lab-navigation.css';

const desktop=Boolean(window.xiangqi);
installPreviewBridge();
function Entry(){
  const [route,setRoute]=React.useState(location.hash||(!desktop?'#lab':'#standard'));
  React.useEffect(()=>{if(route==='#standard')document.title='弈境 · 普通象棋';},[route]);
  React.useEffect(()=>{const update=()=>setRoute(location.hash||(!desktop?'#lab':'#standard'));addEventListener('hashchange',update);return()=>removeEventListener('hashchange',update);},[]);
  const mode=route==='#jieqi'?'jieqi':route==='#banqi'?'banqi':'custom';
  return route!=='#standard'?<LabApp key={mode} initialMode={mode}/>:<div className="standard-app-root"><nav className="standard-lab-link"><a aria-current="page" href="#standard">普通象棋</a><a href="#lab">变体实验室</a><a href="#jieqi">揭棋</a><a href="#banqi">翻棋</a></nav><App/></div>;
}
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><Entry /></React.StrictMode>);
