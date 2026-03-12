import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { PageLayout } from './components/layout/PageLayout'
import { BatchSimPage } from './pages/BatchSimPage'
import { CollectionPage } from './pages/CollectionPage'
import { DecksPage } from './pages/DecksPage'
import { AutoGenPage } from './pages/AutoGenPage'
import { SimulatorPage } from './pages/SimulatorPage'
import { CoachPage } from './pages/CoachPage'
import { TrainingPage } from './pages/TrainingPage'

export default function App() {
  return (
    <BrowserRouter>
      <PageLayout>
        <Routes>
          <Route path="/" element={<BatchSimPage />} />
          <Route path="/collection" element={<CollectionPage />} />
          <Route path="/decks" element={<DecksPage />} />
          <Route path="/autogen" element={<AutoGenPage />} />
          <Route path="/simulator" element={<SimulatorPage />} />
          <Route path="/coach" element={<CoachPage />} />
          <Route path="/training" element={<TrainingPage />} />
        </Routes>
      </PageLayout>
    </BrowserRouter>
  )
}
