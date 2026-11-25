import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Builds plain static files into ui/dist (served by nginx locally and by the
// Storage static website on Azure). The services' URLs are not baked in here:
// they come from public/config.js at runtime.
export default defineConfig({
  plugins: [react()],
})
