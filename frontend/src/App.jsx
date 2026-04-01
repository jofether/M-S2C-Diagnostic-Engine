import { useState, useEffect } from 'react'

function App() {
  const [currentState, setCurrentState] = useState('INITIAL')
  const [repositoryUrl, setRepositoryUrl] = useState('')
  const [bugDescription, setBugDescription] = useState('')
  const [uploadedFile, setUploadedFile] = useState(null)
  const [loadingMessage, setLoadingMessage] = useState('Parsing ASTs with Tree-sitter...')
  const [dragActive, setDragActive] = useState(false)

  // Simulate repository indexing with cycling messages
  useEffect(() => {
    if (currentState !== 'LOADING') return

    const messages = [
      'Parsing ASTs with Tree-sitter...',
      'Generating CodeBERT Embeddings...',
      'Populating FAISS Vector Database...',
    ]

    let messageIndex = 0
    const messageInterval = setInterval(() => {
      messageIndex = (messageIndex + 1) % messages.length
      setLoadingMessage(messages[messageIndex])
    }, 1500)

    // After 6 seconds (4 message cycles), transition to query state
    const transitionTimer = setTimeout(() => {
      clearInterval(messageInterval)
      setCurrentState('QUERY')
      setLoadingMessage('Parsing ASTs with Tree-sitter...')
    }, 6000)

    return () => {
      clearInterval(messageInterval)
      clearTimeout(transitionTimer)
    }
  }, [currentState])

  const handleIndexRepository = () => {
    if (repositoryUrl.trim()) {
      setCurrentState('LOADING')
    }
  }

  const handleDiagnoseBug = () => {
    if (bugDescription.trim() && uploadedFile) {
      setCurrentState('LOADING_RESULTS')
      // Simulate multimodal fusion processing
      setTimeout(() => {
        setCurrentState('RESULTS')
      }, 2500)
    }
  }

  const handleBackToQuery = () => {
    setCurrentState('QUERY')
    setBugDescription('')
    setUploadedFile(null)
  }

  const handleDrag = (e) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true)
    } else if (e.type === 'dragleave') {
      setDragActive(false)
    }
  }

  const handleDrop = (e) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)

    const files = e.dataTransfer.files
    if (files && files[0]) {
      if (files[0].type.startsWith('image/')) {
        setUploadedFile(files[0])
      }
    }
  }

  const handleFileSelect = (e) => {
    if (e.target.files && e.target.files[0]) {
      setUploadedFile(e.target.files[0])
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100">
      {currentState === 'INITIAL' && (
        <InitialState
          repositoryUrl={repositoryUrl}
          setRepositoryUrl={setRepositoryUrl}
          onIndexRepository={handleIndexRepository}
        />
      )}

      {(currentState === 'LOADING' || currentState === 'LOADING_RESULTS') && (
        <LoadingState
          message={
            currentState === 'LOADING_RESULTS'
              ? 'Running Multimodal Fusion...'
              : loadingMessage
          }
        />
      )}

      {currentState === 'QUERY' && (
        <QueryState
          bugDescription={bugDescription}
          setBugDescription={setBugDescription}
          uploadedFile={uploadedFile}
          onDiagnoseBug={handleDiagnoseBug}
          onDrag={handleDrag}
          dragActive={dragActive}
          onDrop={handleDrop}
          onFileSelect={handleFileSelect}
        />
      )}

      {currentState === 'RESULTS' && (
        <ResultsState onBackToQuery={handleBackToQuery} />
      )}
    </div>
  )
}

// ============================================================================
// STATE I: Initial Repository Ingestion
// ============================================================================
function InitialState({ repositoryUrl, setRepositoryUrl, onIndexRepository }) {
  return (
    <div className="flex items-center justify-center min-h-screen px-4">
      <div className="w-full max-w-md">
        {/* Hero Section */}
        <div className="text-center mb-12">
          <h1 className="text-5xl font-bold text-slate-900 mb-4">
            M-S2C Diagnostic Engine
          </h1>
          <p className="text-lg text-slate-600">
            Multimodal Semantic-to-Code Framework
          </p>
        </div>

        {/* Input Form */}
        <div className="bg-white rounded-lg shadow-lg p-8">
          <label className="block text-sm font-semibold text-slate-700 mb-3">
            Target GitHub Repository URL
          </label>
          <input
            type="text"
            value={repositoryUrl}
            onChange={(e) => setRepositoryUrl(e.target.value)}
            onKeyPress={(e) => {
              if (e.key === 'Enter') {
                onIndexRepository()
              }
            }}
            placeholder="e.g., https://github.com/user/repo"
            className="w-full px-4 py-3 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent mb-6"
          />

          <button
            onClick={onIndexRepository}
            disabled={!repositoryUrl.trim()}
            className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 text-white font-semibold py-3 px-4 rounded-lg transition-colors duration-200"
          >
            Index Repository
          </button>
        </div>

        {/* Info Footer */}
        <div className="mt-8 text-center text-sm text-slate-500">
          <p>Your repository will be parsed to build a searchable AST index.</p>
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// STATE II: Loading State with Cycling Messages
// ============================================================================
function LoadingState({ message }) {
  return (
    <div className="flex items-center justify-center min-h-screen px-4">
      <div className="w-full max-w-md text-center">
        {/* Spinner */}
        <div className="flex justify-center mb-8">
          <div className="relative w-16 h-16">
            <div className="absolute inset-0 bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full animate-spin" />
            <div className="absolute inset-1 bg-slate-50 rounded-full" />
          </div>
        </div>

        {/* Loading Message with transition */}
        <div className="min-h-16 flex items-center justify-center">
          <p className="text-lg font-semibold text-slate-700 transition-opacity duration-500">
            {message}
          </p>
        </div>

        {/* Progress Bar */}
        <div className="mt-8 w-full">
          <div className="h-1 bg-slate-200 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 animate-pulse"
              style={{
                width: '66%',
              }}
            />
          </div>
        </div>

        <p className="mt-6 text-sm text-slate-500">
          Building your searchable index...
        </p>
      </div>
    </div>
  )
}

// ============================================================================
// STATE III: Multimodal Query Form
// ============================================================================
function QueryState({
  bugDescription,
  setBugDescription,
  uploadedFile,
  onDiagnoseBug,
  onDrag,
  dragActive,
  onDrop,
  onFileSelect,
}) {
  return (
    <div className="min-h-screen py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="mb-12">
          <h1 className="text-4xl font-bold text-slate-900 mb-2">
            Report a Bug
          </h1>
          <p className="text-lg text-slate-600">
            Provide a text description and visual evidence for diagnosis
          </p>
        </div>

        {/* Form Container */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Natural Language Input */}
          <div className="bg-white rounded-lg shadow-lg p-8">
            <h2 className="text-2xl font-semibold text-slate-900 mb-4">
              Bug Description
            </h2>
            <label className="block text-sm font-semibold text-slate-700 mb-3">
              Describe the symptoms you're experiencing
            </label>
            <textarea
              value={bugDescription}
              onChange={(e) => setBugDescription(e.target.value)}
              placeholder="e.g., The login button is overlapping the container and extending beyond the viewport..."
              className="w-full h-48 px-4 py-3 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none"
            />
            <p className="mt-2 text-xs text-slate-500">
              {bugDescription.length} characters
            </p>
          </div>

          {/* Visual Evidence Upload */}
          <div className="bg-white rounded-lg shadow-lg p-8">
            <h2 className="text-2xl font-semibold text-slate-900 mb-4">
              Visual Evidence
            </h2>
            <label className="block text-sm font-semibold text-slate-700 mb-3">
              Upload a UI screenshot
            </label>

            <div
              onDragEnter={onDrag}
              onDragLeave={onDrag}
              onDragOver={onDrag}
              onDrop={onDrop}
              className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors duration-200 ${
                dragActive
                  ? 'border-indigo-500 bg-indigo-50'
                  : 'border-slate-300 bg-slate-50'
              }`}
            >
              {uploadedFile ? (
                <div className="space-y-3">
                  <div className="text-4xl text-indigo-600">✓</div>
                  <p className="font-semibold text-slate-900">
                    {uploadedFile.name}
                  </p>
                  <p className="text-sm text-slate-500">
                    {(uploadedFile.size / 1024 / 1024).toFixed(2)} MB
                  </p>
                  <input
                    type="file"
                    accept="image/*"
                    onChange={onFileSelect}
                    className="hidden"
                    id="fileInput"
                  />
                  <label
                    htmlFor="fileInput"
                    className="inline-block mt-2 px-4 py-2 bg-indigo-100 text-indigo-700 rounded hover:bg-indigo-200 cursor-pointer text-sm font-medium"
                  >
                    Change File
                  </label>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="text-4xl text-slate-400">📸</div>
                  <p className="text-slate-900 font-medium">
                    Drag and drop your screenshot here
                  </p>
                  <p className="text-sm text-slate-500">or</p>
                  <input
                    type="file"
                    accept="image/*"
                    onChange={onFileSelect}
                    className="hidden"
                    id="fileInput"
                  />
                  <label
                    htmlFor="fileInput"
                    className="inline-block px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700 cursor-pointer font-medium"
                  >
                    Browse Files
                  </label>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Submit Button */}
        <div className="mt-12">
          <button
            onClick={onDiagnoseBug}
            disabled={!bugDescription.trim() || !uploadedFile}
            className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 text-white font-semibold py-4 px-6 rounded-lg text-lg transition-colors duration-200"
          >
            Diagnose Bug
          </button>
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// STATE IV: Results Dashboard
// ============================================================================
function ResultsState({ onBackToQuery }) {
  const mockResults = [
    {
      filePathAndLines: 'src/components/Login.jsx (Lines 42-55)',
      codeSnippet: `export function LoginButton() {
  return (
    <button className="px-4 py-2
      bg-blue-500 hover:bg-blue-600">
      Login
    </button>
  )
}`,
      textContribution: 30,
      visualContribution: 70,
    },
    {
      filePathAndLines: 'src/styles/forms.css (Lines 128-145)',
      codeSnippet: `.login-btn {
  position: absolute;
  right: -20px;
  width: 140px;
  overflow: visible;
  z-index: 999;
}`,
      textContribution: 25,
      visualContribution: 75,
    },
    {
      filePathAndLines: 'src/layouts/Container.jsx (Lines 89-102)',
      codeSnippet: `function Container({ children }) {
  return (
    <div className="w-full
      overflow-hidden px-4">
      {children}
    </div>
  )
}`,
      textContribution: 45,
      visualContribution: 55,
    },
  ]

  return (
    <div className="min-h-screen py-12 px-4 sm:px-6 lg:px-8 bg-gradient-to-br from-slate-50 to-slate-100">
      <div className="max-w-5xl mx-auto">
        {/* Header Section */}
        <div className="mb-12 flex items-center justify-between">
          <div>
            <h1 className="text-4xl font-bold text-slate-900 mb-2">
              Diagnostic Results
            </h1>
            <p className="text-lg text-slate-600">
              Top AST node candidates for your reported bug
            </p>
          </div>
          <button
            onClick={onBackToQuery}
            className="px-6 py-2 bg-white border border-slate-300 text-slate-700 font-semibold rounded-lg hover:bg-slate-50 transition-colors duration-200"
          >
            ← Back to Query
          </button>
        </div>

        {/* Results Cards */}
        <div className="space-y-6">
          {mockResults.map((result, index) => (
            <ResultCard key={index} result={result} rank={index + 1} />
          ))}
        </div>

        {/* Footer */}
        <div className="mt-12 text-center">
          <p className="text-slate-600 text-sm">
            These results are ranked by multimodal fusion confidence scores
          </p>
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// Result Card Component
// ============================================================================
function ResultCard({ result, rank }) {
  return (
    <div className="bg-white rounded-lg shadow-lg overflow-hidden hover:shadow-xl transition-shadow duration-200">
      {/* Header */}
      <div className="bg-gradient-to-r from-indigo-500 to-purple-500 px-6 py-4">
        <div className="flex items-center gap-4">
          <div className="flex items-center justify-center w-10 h-10 bg-white bg-opacity-20 rounded-full">
            <span className="text-white font-bold text-lg">{rank}</span>
          </div>
          <div>
            <h3 className="text-white font-semibold text-lg">
              {result.filePathAndLines}
            </h3>
            <p className="text-indigo-100 text-sm">Candidate AST Node</p>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="p-6 space-y-6">
        {/* Code Preview */}
        <div>
          <h4 className="text-sm font-semibold text-slate-700 mb-3">
            Code Preview
          </h4>
          <pre className="bg-slate-900 text-slate-100 p-4 rounded-lg overflow-x-auto text-sm font-mono leading-relaxed">
            <code>{result.codeSnippet}</code>
          </pre>
        </div>

        {/* Modality Contribution Meter */}
        <div>
          <h4 className="text-sm font-semibold text-slate-700 mb-3">
            Modality Contribution (Gating Weight Alpha)
          </h4>
          <div className="flex items-center gap-4">
            {/* Visual Bar */}
            <div className="flex-1">
              <div className="flex h-8 rounded-lg overflow-hidden bg-slate-100">
                {/* Text Contribution */}
                <div
                  className="bg-gradient-to-r from-blue-400 to-blue-500 flex items-center justify-center text-white text-xs font-bold"
                  style={{ width: `${result.textContribution}%` }}
                >
                  {result.textContribution > 10 && `${result.textContribution}%`}
                </div>
                {/* Visual Contribution */}
                <div
                  className="bg-gradient-to-r from-purple-400 to-purple-500 flex items-center justify-center text-white text-xs font-bold"
                  style={{ width: `${result.visualContribution}%` }}
                >
                  {result.visualContribution > 10 && `${result.visualContribution}%`}
                </div>
              </div>
            </div>
          </div>

          {/* Legend */}
          <div className="mt-3 flex gap-6 text-sm">
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 bg-blue-500 rounded" />
              <span className="text-slate-600">
                Text: <span className="font-semibold">{result.textContribution}%</span>
              </span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 bg-purple-500 rounded" />
              <span className="text-slate-600">
                Visual: <span className="font-semibold">{result.visualContribution}%</span>
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default App
