import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';
import { installPreviewBridge } from './mock-bridge';
import './styles.css';

installPreviewBridge();
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
