/**
 * Titik masuk aplikasi.
 *
 * `styles.css` diimpor di sini, bukan di setiap komponen: sistem desainnya satu
 * berkas, dan Vite akan menggabungkannya menjadi satu bundel CSS.
 */

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'
import './styles.css'

const container = document.getElementById('root')
if (!container) throw new Error('Elemen #root tidak ditemukan di index.html.')

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
