import { uiStore } from '@/stores/uiStore'
import './sidebar.css'

// PagePilot's compact sidebar layout closes chat history without changing the
// selected session, route, draft input, or in-flight model request.
const compactSidebar = () => uiStore.getState().setShowSidebar(false)
window.addEventListener('slidepilot:sidebar', compactSidebar)
if (document.documentElement.dataset.spMode === 'sidebar') compactSidebar()
