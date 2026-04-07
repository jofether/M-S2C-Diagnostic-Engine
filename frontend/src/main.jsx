/**
 * React Application Entry Point
 * 
 * This is the main entry point for the React application. It renders the root App component
 * into the DOM with React's StrictMode enabled for development safety checks.
 * 
 * The actual application logic and state management is handled in App.jsx.
 */

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
