import { useState, useEffect } from 'react'

function App() {
  const [currentState, setCurrentState] = useState('INITIAL')
  const [repositoryUrl, setRepositoryUrl] = useState('')
  const [bugDescription, setBugDescription] = useState('')
  const [uploadedFile, setUploadedFile] = useState(null)
  const [loadingMessage, setLoadingMessage] = useState('Parsing ASTs with Tree-sitter...')
  const [dragActive, setDragActive] = useState(false)
  const [darkMode, setDarkMode] = useState(false)

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
    <div className={`min-h-screen transition-colors duration-300 ${
      darkMode 
        ? 'bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900' 
        : 'bg-gradient-to-br from-slate-50 via-blue-50 to-slate-50'
    }`}>
      {/* Dark Mode Toggle */}
      <div className={`fixed top-6 right-6 z-50 ${darkMode ? 'text-white' : 'text-slate-900'}`}>
        <button
          onClick={() => setDarkMode(!darkMode)}
          className={`p-3 rounded-full transition-all duration-300 ${
            darkMode
              ? 'bg-slate-700 hover:bg-slate-600'
              : 'bg-white shadow-lg hover:shadow-xl border border-slate-200'
          }`}
          title={darkMode ? 'Light Mode' : 'Dark Mode'}
        >
          {darkMode ? (
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zM4.22 4.22a1 1 0 011.414 0l.707.707a1 1 0 11-1.414 1.414l-.707-.707a1 1 0 010-1.414zm11.314 0a1 1 0 010 1.414l-.707.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM4 10a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zm12 0a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zm-8 6a1 1 0 01.707-.293h.586a1 1 0 110 2h-.586a1 1 0 01-.707-1.707zM9 16a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1z" clipRule="evenodd" />
            </svg>
          ) : (
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
              <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
            </svg>
          )}
        </button>
      </div>

      {currentState === 'INITIAL' && (
        <InitialState
          repositoryUrl={repositoryUrl}
          setRepositoryUrl={setRepositoryUrl}
          onIndexRepository={handleIndexRepository}
          darkMode={darkMode}
        />
      )}

      {(currentState === 'LOADING' || currentState === 'LOADING_RESULTS') && (
        <LoadingState
          message={
            currentState === 'LOADING_RESULTS'
              ? 'Running Multimodal Fusion...'
              : loadingMessage
          }
          darkMode={darkMode}
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
          darkMode={darkMode}
        />
      )}

      {currentState === 'RESULTS' && (
        <ResultsState onBackToQuery={handleBackToQuery} darkMode={darkMode} />
      )}
    </div>
  )
}

// ============================================================================
// STATE I: Initial Repository Ingestion
// ============================================================================
function InitialState({ repositoryUrl, setRepositoryUrl, onIndexRepository, darkMode }) {
  return (
    <div className="flex items-center justify-center min-h-screen px-4">
      <div className="w-full max-w-md">
        {/* Hero Section with Improved M-S2C Branding */}
        <div className="text-center mb-12">
          {/* M-S2C Logo/Title with gradient */}
          <div className="mb-6">
            <div className={`text-7xl font-bold mb-2 bg-clip-text text-transparent bg-gradient-to-r from-blue-600 via-indigo-600 to-purple-600`}>
              M-S2C
            </div>
            <div className={`text-sm font-semibold tracking-widest uppercase letter-spacing-2 ${
              darkMode ? 'text-slate-400' : 'text-slate-600'
            }`}>
              Multimodal Semantic-to-Code
            </div>
          </div>
          
          {/* Subtitle */}
          <h1 className={`text-4xl font-bold mb-3 ${
            darkMode ? 'text-white' : 'text-slate-900'
          }`}>
            Diagnostic Engine
          </h1>
          <p className={`text-lg ${
            darkMode ? 'text-slate-400' : 'text-slate-600'
          }`}>
            Find bugs with multimodal intelligence
          </p>
        </div>

        {/* Input Form Card */}
        <div className={`rounded-2xl shadow-2xl p-8 backdrop-blur-sm ${
          darkMode
            ? 'bg-slate-800/50 border border-slate-700'
            : 'bg-white/80 border border-slate-200'
        }`}>
          <label className={`block text-sm font-semibold mb-3 ${
            darkMode ? 'text-slate-300' : 'text-slate-700'
          }`}>
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
            className={`w-full px-4 py-3 border rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent mb-6 transition-colors duration-200 ${
              darkMode
                ? 'bg-slate-700 border-slate-600 text-white placeholder-slate-500'
                : 'bg-slate-50 border-slate-300 text-slate-900 placeholder-slate-400'
            }`}
          />

          <button
            onClick={onIndexRepository}
            disabled={!repositoryUrl.trim()}
            className={`w-full font-semibold py-3 px-4 rounded-lg transition-all duration-300 transform hover:scale-105 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100 ${
              darkMode
                ? 'bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 text-white'
                : 'bg-gradient-to-r from-indigo-600 to-blue-600 hover:from-indigo-700 hover:to-blue-700 text-white'
            }`}
          >
            Index Repository
          </button>
        </div>

        {/* Info Footer */}
        <div className={`mt-8 text-center text-sm ${
          darkMode ? 'text-slate-500' : 'text-slate-500'
        }`}>
          <p>Your repository will be parsed to build a searchable AST index.</p>
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// STATE II: Loading State with Cycling Messages
// ============================================================================
function LoadingState({ message, darkMode }) {
  return (
    <div className="flex items-center justify-center min-h-screen px-4">
      <div className="w-full max-w-md text-center">
        {/* Enhanced Spinner */}
        <div className="flex justify-center mb-8">
          <div className="relative w-24 h-24">
            <div className="absolute inset-0 bg-gradient-to-r from-indigo-500 via-purple-500 to-blue-500 rounded-full animate-spin" />
            <div className={`absolute inset-2 rounded-full ${
              darkMode ? 'bg-slate-800' : 'bg-slate-50'
            }`} />
            <div className="absolute inset-6 bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full animate-pulse opacity-40" />
          </div>
        </div>

        {/* Loading Message with transition */}
        <div className="min-h-16 flex items-center justify-center">
          <p className={`text-lg font-semibold transition-opacity duration-500 ${
            darkMode ? 'text-white' : 'text-slate-700'
          }`}>
            {message}
          </p>
        </div>

        {/* Enhanced Progress Bar */}
        <div className="mt-8 w-full">
          <div className={`h-2 rounded-full overflow-hidden ${
            darkMode ? 'bg-slate-700' : 'bg-slate-200'
          }`}>
            <div
              className="h-full bg-gradient-to-r from-indigo-500 via-purple-500 to-blue-500 animate-pulse"
              style={{
                width: '66%',
              }}
            />
          </div>
        </div>

        <p className={`mt-6 text-sm ${
          darkMode ? 'text-slate-500' : 'text-slate-500'
        }`}>
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
  darkMode,
}) {
  return (
    <div className={`min-h-screen py-12 px-4 sm:px-6 lg:px-8 ${
      darkMode ? 'bg-gradient-to-br from-slate-800 to-slate-900' : ''
    }`}>
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="mb-12">
          <h1 className={`text-4xl font-bold mb-2 ${
            darkMode ? 'text-white' : 'text-slate-900'
          }`}>
            Report a Bug
          </h1>
          <p className={`text-lg ${
            darkMode ? 'text-slate-400' : 'text-slate-600'
          }`}>
            Provide a text description and visual evidence for diagnosis
          </p>
        </div>

        {/* Form Container */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Natural Language Input */}
          <div className={`rounded-2xl shadow-lg p-8 backdrop-blur-sm ${
            darkMode
              ? 'bg-slate-800/50 border border-slate-700'
              : 'bg-white/80 border border-slate-200'
          }`}>
            <h2 className={`text-2xl font-semibold mb-4 ${
              darkMode ? 'text-white' : 'text-slate-900'
            }`}>
              Bug Description
            </h2>
            <label className={`block text-sm font-semibold mb-3 ${
              darkMode ? 'text-slate-300' : 'text-slate-700'
            }`}>
              Describe the symptoms you're experiencing
            </label>
            <textarea
              value={bugDescription}
              onChange={(e) => setBugDescription(e.target.value)}
              placeholder="e.g., The login button is overlapping the container and extending beyond the viewport..."
              className={`w-full h-48 px-4 py-3 border rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none transition-colors duration-200 ${
                darkMode
                  ? 'bg-slate-700 border-slate-600 text-white placeholder-slate-500'
                  : 'bg-slate-50 border-slate-300 text-slate-900 placeholder-slate-400'
              }`}
            />
            <p className={`mt-2 text-xs ${
              darkMode ? 'text-slate-500' : 'text-slate-500'
            }`}>
              {bugDescription.length} characters
            </p>
          </div>

          {/* Visual Evidence Upload */}
          <div className={`rounded-2xl shadow-lg p-8 backdrop-blur-sm ${
            darkMode
              ? 'bg-slate-800/50 border border-slate-700'
              : 'bg-white/80 border border-slate-200'
          }`}>
            <h2 className={`text-2xl font-semibold mb-4 ${
              darkMode ? 'text-white' : 'text-slate-900'
            }`}>
              Visual Evidence
            </h2>
            <label className={`block text-sm font-semibold mb-3 ${
              darkMode ? 'text-slate-300' : 'text-slate-700'
            }`}>
              Upload a UI screenshot
            </label>

            <div
              onDragEnter={onDrag}
              onDragLeave={onDrag}
              onDragOver={onDrag}
              onDrop={onDrop}
              className={`border-2 border-dashed rounded-xl p-8 text-center transition-all duration-200 ${
                dragActive
                  ? darkMode
                    ? 'border-indigo-400 bg-indigo-900/20'
                    : 'border-indigo-500 bg-indigo-50'
                  : darkMode
                    ? 'border-slate-600 bg-slate-700/30'
                    : 'border-slate-300 bg-slate-50'
              }`}
            >
              {uploadedFile ? (
                <div className="space-y-3">
                  <div className="text-4xl text-indigo-600">✓</div>
                  <p className={`font-semibold ${
                    darkMode ? 'text-white' : 'text-slate-900'
                  }`}>
                    {uploadedFile.name}
                  </p>
                  <p className={`text-sm ${
                    darkMode ? 'text-slate-500' : 'text-slate-500'
                  }`}>
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
                    className="inline-block mt-2 px-4 py-2 bg-indigo-100 text-indigo-700 rounded-lg hover:bg-indigo-200 cursor-pointer text-sm font-medium transition-colors duration-200"
                  >
                    Change File
                  </label>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="text-4xl">📸</div>
                  <p className={`font-medium ${
                    darkMode ? 'text-white' : 'text-slate-900'
                  }`}>
                    Drag and drop your screenshot here
                  </p>
                  <p className={`text-sm ${
                    darkMode ? 'text-slate-500' : 'text-slate-500'
                  }`}>or</p>
                  <input
                    type="file"
                    accept="image/*"
                    onChange={onFileSelect}
                    className="hidden"
                    id="fileInput"
                  />
                  <label
                    htmlFor="fileInput"
                    className="inline-block px-4 py-2 bg-gradient-to-r from-indigo-600 to-blue-600 text-white rounded-lg hover:from-indigo-700 hover:to-blue-700 cursor-pointer font-medium transition-all duration-200"
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
            className={`w-full font-semibold py-4 px-6 rounded-lg text-lg transition-all duration-300 transform hover:scale-105 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100 ${
              darkMode
                ? 'bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 text-white'
                : 'bg-gradient-to-r from-indigo-600 to-blue-600 hover:from-indigo-700 hover:to-blue-700 text-white'
            }`}
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
function ResultsState({ onBackToQuery, darkMode }) {
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
    <div className={`min-h-screen py-12 px-4 sm:px-6 lg:px-8 ${
      darkMode ? 'bg-gradient-to-br from-slate-800 to-slate-900' : ''
    }`}>
      <div className="max-w-5xl mx-auto">
        {/* Header Section */}
        <div className="mb-12 flex items-center justify-between flex-wrap gap-4">
          <div>
            <h1 className={`text-4xl font-bold mb-2 ${
              darkMode ? 'text-white' : 'text-slate-900'
            }`}>
              Diagnostic Results
            </h1>
            <p className={`text-lg ${
              darkMode ? 'text-slate-400' : 'text-slate-600'
            }`}>
              Top AST node candidates for your reported bug
            </p>
          </div>
          <button
            onClick={onBackToQuery}
            className={`px-6 py-2 rounded-lg font-semibold transition-all duration-200 ${
              darkMode
                ? 'bg-slate-700 hover:bg-slate-600 text-white border border-slate-600'
                : 'bg-white hover:bg-slate-50 text-slate-700 border border-slate-300'
            }`}
          >
            ← Back to Query
          </button>
        </div>

        {/* Results Cards */}
        <div className="space-y-6">
          {mockResults.map((result, index) => (
            <ResultCard key={index} result={result} rank={index + 1} darkMode={darkMode} />
          ))}
        </div>

        {/* Footer */}
        <div className="mt-12 text-center">
          <p className={`text-sm ${
            darkMode ? 'text-slate-500' : 'text-slate-600'
          }`}>
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
function ResultCard({ result, rank, darkMode }) {
  return (
    <div className={`rounded-xl shadow-lg overflow-hidden hover:shadow-2xl transition-all duration-300 backdrop-blur-sm ${
      darkMode
        ? 'bg-slate-800/50 border border-slate-700 hover:border-indigo-500/50'
        : 'bg-white/80 border border-slate-200 hover:border-indigo-500/50'
    }`}>
      {/* Header */}
      <div className="bg-gradient-to-r from-indigo-600 via-purple-600 to-blue-600 px-6 py-4">
        <div className="flex items-center gap-4">
          <div className="flex items-center justify-center w-10 h-10 bg-white/20 rounded-full border border-white/30 backdrop-blur-sm">
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
          <h4 className={`text-sm font-semibold mb-3 ${
            darkMode ? 'text-slate-300' : 'text-slate-700'
          }`}>
            Code Preview
          </h4>
          <pre className={`p-4 rounded-lg overflow-x-auto text-sm font-mono leading-relaxed ${
            darkMode
              ? 'bg-slate-900/80 text-slate-100 border border-slate-700'
              : 'bg-slate-900 text-slate-100 border border-slate-700'
          }`}>
            <code>{result.codeSnippet}</code>
          </pre>
        </div>

        {/* Modality Contribution Meter */}
        <div>
          <h4 className={`text-sm font-semibold mb-3 ${
            darkMode ? 'text-slate-300' : 'text-slate-700'
          }`}>
            Modality Contribution (Gating Weight Alpha)
          </h4>
          <div className="flex items-center gap-4">
            {/* Visual Bar */}
            <div className="flex-1">
              <div className={`flex h-10 rounded-lg overflow-hidden ${
                darkMode ? 'bg-slate-700' : 'bg-slate-200'
              }`}>
                {/* Text Contribution */}
                <div
                  className="bg-gradient-to-r from-blue-400 to-blue-500 flex items-center justify-center text-white text-xs font-bold transition-all duration-300"
                  style={{ width: `${result.textContribution}%` }}
                >
                  {result.textContribution > 10 && `${result.textContribution}%`}
                </div>
                {/* Visual Contribution */}
                <div
                  className="bg-gradient-to-r from-purple-400 to-purple-500 flex items-center justify-center text-white text-xs font-bold transition-all duration-300"
                  style={{ width: `${result.visualContribution}%` }}
                >
                  {result.visualContribution > 10 && `${result.visualContribution}%`}
                </div>
              </div>
            </div>
          </div>

          {/* Legend */}
          <div className="mt-4 flex gap-6 text-sm">
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 bg-gradient-to-r from-blue-400 to-blue-500 rounded" />
              <span className={darkMode ? 'text-slate-400' : 'text-slate-600'}>
                Text: <span className="font-semibold">{result.textContribution}%</span>
              </span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 bg-gradient-to-r from-purple-400 to-purple-500 rounded" />
              <span className={darkMode ? 'text-slate-400' : 'text-slate-600'}>
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
