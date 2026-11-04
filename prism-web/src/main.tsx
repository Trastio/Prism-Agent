import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import '@fontsource/inter/400.css';
import '@fontsource/inter/600.css';
import '@fontsource/noto-sans-sc/400.css';
import '@fontsource/noto-sans-sc/600.css';
import '@fontsource/bodoni-moda/400.css';
import '@fontsource/bodoni-moda/600.css';
import App from './App';
import './styles.css';

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById('root')!).render(
  React.createElement(React.StrictMode, null,
    React.createElement(QueryClientProvider, { client: queryClient },
      React.createElement(App)
    )
  )
);
