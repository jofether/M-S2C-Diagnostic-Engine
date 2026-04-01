import { useState, useEffect } from 'react'

function App() {
  const [currentState, setCurrentState] = useState('QUERY')
  const [repositoryUrl, setRepositoryUrl] = useState('')
  const [repositoryIndexed, setRepositoryIndexed] = useState(false)
  const [indexedRepoName, setIndexedRepoName] = useState('')
  const [bugDescription, setBugDescription] = useState('')
  const [targetFileHint, setTargetFileHint] = useState('')
  const [uploadedFile, setUploadedFile] = useState(null)
  const [imagePreview, setImagePreview] = useState(null)
  const [loadingMessage, setLoadingMessage] = useState('Parsing ASTs with Tree-sitter...')
  const [dragActive, setDragActive] = useState(false)
  const [darkMode, setDarkMode] = useState(true)
  const [diagnosticResults, setDiagnosticResults] = useState([])
  const [alphaWeights, setAlphaWeights] = useState({ text: 50, visual: 50 })
  const [indexedFiles, setIndexedFiles] = useState([]) // Files from indexed repo

  // Debug: Log whenever indexedFiles changes
  useEffect(() => {
    console.log('📂 indexedFiles state updated:', indexedFiles)
    console.log('   Length:', indexedFiles.length)
    console.log('   Content:', indexedFiles)
  }, [indexedFiles])

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

    return () => {
      clearInterval(messageInterval)
    }
  }, [currentState])

  const handleIndexRepository = async () => {
    if (!repositoryUrl.trim()) return

    setCurrentState('LOADING')

    try {
      const formData = new FormData()
      formData.append('repo_url', repositoryUrl.trim())

      console.log('🔗 Attempting to fetch from:', 'http://localhost:8000/api/index-repository')
      console.log('📦 Repository URL:', repositoryUrl.trim())

      // Create an AbortController for timeout
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 120000) // 2 minute timeout

      const response = await fetch('http://localhost:8000/api/index-repository', {
        method: 'POST',
        body: formData,
        signal: controller.signal,
      })

      clearTimeout(timeoutId)

      console.log('📡 Response status:', response.status)
      console.log('📡 Response ok:', response.ok)

      if (!response.ok) {
        const errorText = await response.text()
        console.error('❌ HTTP Error:', response.status, errorText)
        throw new Error(`HTTP ${response.status}: ${errorText}`)
      }

      const data = await response.json()
      console.log('✅ Index response:', data)
      console.log('📁 Files array:', data.files)
      console.log('📊 Files count:', data.files ? data.files.length : 'N/A')

      // Check for error status in response
      if (data.status === 'error' || data.status === 'warning') {
        throw new Error(data.message || 'Repository indexing failed')
      }

      // Extract repo name from URL
      const repoName = repositoryUrl.split('/').pop() || 'Repository'
      setIndexedRepoName(repoName)
      setRepositoryIndexed(true)
      
      // Set the files from the API response (not hardcoded)
      if (data.files && Array.isArray(data.files)) {
        console.log('✓ Setting indexedFiles with', data.files.length, 'files')
        setIndexedFiles(['', ...data.files])  // Add empty option for "Select file..."
      } else {
        console.warn('⚠️  No files in response, using fallback')
        setIndexedFiles([''])  // Fallback if no files
      }

      setCurrentState('QUERY')
    } catch (error) {
      console.error('❌ Indexing error full:', error)
      console.error('   Error type:', error.constructor.name)
      console.error('   Error message:', error.message)
      console.error('   Error stack:', error.stack)
      
      let errorMsg = error.message
      if (error.name === 'AbortError') {
        errorMsg = 'Indexing timed out after 2 minutes. Repository might be too large.'
      }
      
      alert(`Indexing failed: ${errorMsg}\n\nMake sure the backend is running on http://localhost:8000`)
      setCurrentState('QUERY')
    }
  }

  const handleDiagnoseBug = async () => {
    if (!bugDescription.trim() || !uploadedFile) return

    setCurrentState('LOADING_RESULTS')

    try {
      const formData = new FormData()
      
      // CRITICAL: Append target file hint to bug description if selected
      let finalDescription = bugDescription.trim()
      if (targetFileHint && targetFileHint.trim()) {
        finalDescription = `${finalDescription} [Context: ${targetFileHint}]`
      }
      
      formData.append('bug_description', finalDescription)
      formData.append('screenshot', uploadedFile)

      console.log('🔍 Attempting diagnosis fetch from:', 'http://localhost:8000/api/diagnose')

      const response = await fetch('http://localhost:8000/api/diagnose', {
        method: 'POST',
        body: formData,
      })

      console.log('📡 Diagnosis response status:', response.status)

      if (!response.ok) {
        const errorText = await response.text()
        console.error('❌ Diagnosis HTTP Error:', response.status, errorText)
        throw new Error(`HTTP ${response.status}: ${errorText}`)
      }

      const data = await response.json()
      console.log('Diagnosis response:', data)

      if (data.candidates && data.candidates.length > 0) {
        setDiagnosticResults(data.candidates)
        setAlphaWeights({
          text: Math.round((data.alpha_text || 0.5) * 100),
          visual: Math.round((data.alpha_visual || 0.5) * 100),
        })
      }

      setCurrentState('RESULTS')
    } catch (error) {
      console.error('❌ Diagnosis error full:', error)
      console.error('   Error type:', error.constructor.name)
      console.error('   Error message:', error.message)
      alert(`Diagnosis failed: ${error.message}\n\nMake sure the backend is running on http://localhost:8000`)
      setCurrentState('QUERY')
    }
  }

  const handleBackToQuery = () => {
    setCurrentState('QUERY')
    setBugDescription('')
    setTargetFileHint('')
    setUploadedFile(null)
    setImagePreview(null)
  }

  const handleChangeRepository = () => {
    setRepositoryIndexed(false)
    setIndexedRepoName('')
    setRepositoryUrl('')
    setIndexedFiles([])
    setBugDescription('')
    setTargetFileHint('')
    setUploadedFile(null)
    setImagePreview(null)
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
        const reader = new FileReader()
        reader.onload = (event) => {
          setImagePreview(event.target.result)
        }
        reader.readAsDataURL(files[0])
      }
    }
  }

  const handleFileSelect = (e) => {
    if (e.target.files && e.target.files[0]) {
      setUploadedFile(e.target.files[0])
      const reader = new FileReader()
      reader.onload = (event) => {
        setImagePreview(event.target.result)
      }
      reader.readAsDataURL(e.target.files[0])
    }
  }

  return (
    <div className={`min-h-screen transition-colors duration-300 ${
      darkMode 
        ? 'bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900' 
        : 'bg-gradient-to-br from-slate-50 via-blue-50 to-slate-50'
    }`}>
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
          repositoryUrl={repositoryUrl}
          setRepositoryUrl={setRepositoryUrl}
          repositoryIndexed={repositoryIndexed}
          indexedRepoName={indexedRepoName}
          bugDescription={bugDescription}
          setBugDescription={setBugDescription}
          targetFileHint={targetFileHint}
          setTargetFileHint={setTargetFileHint}
          indexedFiles={indexedFiles}
          uploadedFile={uploadedFile}
          imagePreview={imagePreview}
          onIndexRepository={handleIndexRepository}
          onDiagnoseBug={handleDiagnoseBug}
          onChangeRepository={handleChangeRepository}
          onDrag={handleDrag}
          dragActive={dragActive}
          onDrop={handleDrop}
          onFileSelect={handleFileSelect}
          darkMode={darkMode}
          setDarkMode={setDarkMode}
        />
      )}

      {currentState === 'RESULTS' && (
        <ResultsState 
          onBackToQuery={handleBackToQuery} 
          darkMode={darkMode}
          setDarkMode={setDarkMode}
          results={diagnosticResults}
          alphaWeights={alphaWeights}
        />
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
            className={`w-full py-2 rounded-lg font-medium transition-all ${
              !repositoryUrl.trim() 
                ? 'bg-indigo-600 text-white opacity-50 cursor-not-allowed' 
                : 'bg-indigo-600 text-white hover:bg-indigo-700'
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
        <div className="flex justify-center mb-6">
          <div className="relative w-20 h-20">
            <div className="absolute inset-0 bg-gradient-to-r from-indigo-500 via-purple-500 to-blue-500 rounded-full animate-spin" />
            <div className={`absolute inset-2 rounded-full ${
              darkMode ? 'bg-slate-800' : 'bg-slate-50'
            }`} />
            <div className="absolute inset-6 bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full animate-pulse opacity-40" />
          </div>
        </div>

        {/* Loading Message with transition */}
        <div className="min-h-12 flex items-center justify-center">
          <p className={`text-lg font-semibold transition-opacity duration-500 ${
            darkMode ? 'text-white' : 'text-slate-700'
          }`}>
            {message}
          </p>
        </div>

        {/* Enhanced Progress Bar */}
        <div className="mt-6 w-full">
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

        <p className={`mt-4 text-sm ${
          darkMode ? 'text-slate-500' : 'text-slate-500'
        }`}>
          Building your searchable index...
        </p>
      </div>
    </div>
  )
}

// ============================================================================
// STATE II: Unified ChatGPT-Style Interface (Repository + Bug Reporting)
// ============================================================================
function QueryState({
  repositoryUrl,
  setRepositoryUrl,
  repositoryIndexed,
  indexedRepoName,
  bugDescription,
  setBugDescription,
  targetFileHint,
  setTargetFileHint,
  indexedFiles,
  uploadedFile,
  imagePreview,
  onIndexRepository,
  onDiagnoseBug,
  onChangeRepository,
  onDrag,
  dragActive,
  onDrop,
  onFileSelect,
  darkMode,
  setDarkMode,
}) {
  return (
    <div className={`min-h-screen flex flex-col ${
      darkMode ? 'bg-slate-900' : 'bg-white'
    }`}>
      {/* Header */}
      <div className={`border-b ${darkMode ? 'border-slate-700 bg-slate-800' : 'border-slate-200 bg-slate-50'} px-4 py-2 flex items-center justify-between`}>
        <div className="min-w-0">
          <h1 className={`text-base font-semibold ${darkMode ? 'text-white' : 'text-slate-900'}`}>
            M-S2C Diagnostic Engine
          </h1>
          {repositoryIndexed && (
            <p className={`text-xs ${darkMode ? 'text-slate-400' : 'text-slate-600'} truncate`}>
              📦 Indexed: {indexedRepoName}
            </p>
          )}
        </div>
        
        {/* Buttons Wrapper */}
        <div className={`flex items-center gap-3 ${darkMode ? 'text-white' : 'text-slate-900'}`}>
          {/* Dark Mode Toggle */}
          <button
            onClick={() => setDarkMode(!darkMode)}
            className={`p-2 rounded-full transition-all duration-300 hover:scale-110 ${
              darkMode
                ? 'bg-slate-700 hover:bg-slate-600'
                : 'bg-white shadow-sm hover:shadow-md border border-slate-200'
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
          
          {/* Change Repo Button */}
          {repositoryIndexed && (
            <button
              onClick={onChangeRepository}
              className={`px-2 py-1 rounded text-xs font-medium transition-colors flex-shrink-0 whitespace-nowrap ${
                darkMode
                  ? 'bg-slate-700 hover:bg-slate-600 text-white'
                  : 'bg-slate-200 hover:bg-slate-300 text-slate-900'
              }`}
            >
              Change Repo
            </button>
          )}
        </div>
      </div>

      {/* Chat Area */}
      <div className="flex-1 overflow-y-auto p-3 pt-4">
        <div className="text-center max-w-sm mx-auto">
          {!repositoryIndexed ? (
            <>
              <div className="text-4xl mb-2">🔗</div>
              <h2 className={`text-xl font-semibold mb-1 ${
                darkMode ? 'text-white' : 'text-slate-900'
              }`}>
                Index a Repository
              </h2>
              <p className={`text-sm ${
                darkMode ? 'text-slate-400' : 'text-slate-600'
              }`}>
                Enter a GitHub URL to get started
              </p>
            </>
          ) : (
            <>
              <div className="text-4xl mb-2">🐛</div>
              <h2 className={`text-xl font-semibold mb-1 ${
                darkMode ? 'text-white' : 'text-slate-900'
              }`}>
                Report a Bug
              </h2>
              <p className={`text-sm ${
                darkMode ? 'text-slate-400' : 'text-slate-600'
              }`}>
                Describe the issue and upload a screenshot
              </p>
            </>
          )}
        </div>
      </div>

      {/* Input Area (Sticky at bottom) */}
      <div className={`border-t ${darkMode ? 'border-slate-700 bg-slate-800' : 'border-slate-200'} p-3`}>
        <div className="max-w-3xl mx-auto space-y-2">
          {!repositoryIndexed ? (
            // Repository Indexing Form
            <>
              <div>
                <div className={`flex items-center gap-2 text-xs font-semibold mb-1 ${
                  darkMode ? 'text-slate-300' : 'text-slate-700'
                }`}>
                  <span>GitHub Repository URL <span className="text-red-500">*</span></span>
                </div>
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
                  className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-transparent text-sm transition-colors ${
                    darkMode
                      ? 'bg-slate-700 border-slate-600 text-white placeholder-slate-500'
                      : 'bg-slate-50 border-slate-300 text-slate-900 placeholder-slate-400'
                  }`}
                />
              </div>

              <button
                onClick={onIndexRepository}
                disabled={!repositoryUrl.trim()}
                className={`w-full font-medium py-2 rounded-lg text-sm transition-all ${
                  !repositoryUrl.trim()
                    ? 'bg-indigo-600 text-white opacity-50 cursor-not-allowed'
                    : darkMode
                      ? 'bg-indigo-600 hover:bg-indigo-700 text-white'
                      : 'bg-indigo-600 hover:bg-indigo-700 text-white'
                }`}
              >
                Index Repository
              </button>
            </>
          ) : (
            // Bug Description Form
            <>
              <div>
                <div className={`flex items-center gap-2 text-xs font-semibold mb-1 ${
                  darkMode ? 'text-slate-300' : 'text-slate-700'
                }`}>
                  <span>Bug Description <span className="text-red-500">*</span></span>
                </div>
                <textarea
                  value={bugDescription}
                  onChange={(e) => setBugDescription(e.target.value)}
                  placeholder="What's the bug? (e.g., 'Button doesn't respond to clicks on mobile')"
                  rows="2"
                  className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-transparent resize-none text-sm transition-colors ${
                    darkMode
                      ? 'bg-slate-700 border-slate-600 text-white placeholder-slate-500'
                      : 'bg-slate-50 border-slate-300 text-slate-900 placeholder-slate-400'
                  }`}
                />
              </div>

              {/* File dropdown + Image Upload (side by side) */}
              <div className="grid grid-cols-2 gap-2">
                {/* File Hint Dropdown */}
                <div>
                  <div className={`text-xs font-semibold mb-1 ${
                    darkMode ? 'text-slate-400' : 'text-slate-600'
                  }`}>
                    Target File <span className="text-slate-500">(optional)</span>
                  </div>
                  <select
                    value={targetFileHint}
                    onChange={(e) => setTargetFileHint(e.target.value)}
                    className={`w-full px-2 py-1 border rounded text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-transparent transition-colors ${
                      darkMode
                        ? 'bg-slate-700 border-slate-600 text-white'
                        : 'bg-slate-50 border-slate-300 text-slate-900'
                    }`}
                  >
                    {indexedFiles.map((file) => (
                      <option key={file || 'empty'} value={file}>
                        {file || 'Select file...'}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Image Upload */}
                <div>
                  <div className={`text-xs font-semibold mb-1 ${
                    darkMode ? 'text-slate-400' : 'text-slate-600'
                  }`}>
                    Screenshot <span className="text-slate-500">(optional)</span>
                  </div>
                  <div
                    onDragEnter={onDrag}
                    onDragLeave={onDrag}
                    onDragOver={onDrag}
                    onDrop={onDrop}
                    className={`border rounded cursor-pointer p-1.5 text-center text-xs transition-all ${
                      dragActive
                        ? darkMode
                          ? 'border-indigo-400 bg-indigo-900/20'
                          : 'border-indigo-500 bg-indigo-50'
                        : darkMode
                          ? 'border-slate-600 bg-slate-700/30'
                          : 'border-slate-300 bg-slate-50'
                    }`}
                  >
                    {uploadedFile && imagePreview ? (
                      <div>
                        <img 
                          src={imagePreview} 
                          alt="Screenshot" 
                          className="w-full h-10 object-cover rounded mb-0.5"
                        />
                        <input
                          type="file"
                          accept="image/*"
                          onChange={onFileSelect}
                          className="hidden"
                          id="fileInput"
                        />
                        <label
                          htmlFor="fileInput"
                          className="text-xs block text-indigo-600 hover:text-indigo-700 cursor-pointer"
                        >
                          Change
                        </label>
                      </div>
                    ) : (
                      <div>
                        <input
                          type="file"
                          accept="image/*"
                          onChange={onFileSelect}
                          className="hidden"
                          id="fileInput"
                        />
                        <label
                          htmlFor="fileInput"
                          className="text-xs block cursor-pointer text-slate-500 hover:text-slate-700"
                        >
                          📷 Upload
                        </label>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Analyze Button */}
              <button
                onClick={onDiagnoseBug}
                disabled={!bugDescription.trim() || !uploadedFile}
                className={`w-full font-medium py-2 rounded-lg text-sm transition-all ${
                  !bugDescription.trim() || !uploadedFile
                    ? 'bg-indigo-600 text-white opacity-50 cursor-not-allowed'
                    : darkMode
                      ? 'bg-indigo-600 hover:bg-indigo-700 text-white'
                      : 'bg-indigo-600 hover:bg-indigo-700 text-white'
                }`}
              >
                Analyze Bug
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// STATE IV: ChatGPT-Style Results as Chat Thread
// ============================================================================
function ResultsState({ onBackToQuery, darkMode, setDarkMode, results = [], alphaWeights = { text: 50, visual: 50 } }) {
  const displayResults = results && results.length > 0 ? results : []
  const [copiedIndex, setCopiedIndex] = useState(-1)

  const handleCopyResult = (index) => {
    const result = displayResults[index]
    const filepath = Array.isArray(result) ? result[0] : result.filePathAndLines || result.file
    navigator.clipboard.writeText(`${index + 1}. ${filepath}`)
    setCopiedIndex(index)
    setTimeout(() => setCopiedIndex(-1), 2000)
  }

  return (
    <div className={`min-h-screen flex flex-col ${
      darkMode ? 'bg-slate-900' : 'bg-white'
    }`}>
      {/* Header */}
      <div className={`border-b ${darkMode ? 'border-slate-700 bg-slate-800' : 'border-slate-200 bg-slate-50'} px-4 py-2 flex items-center justify-between`}>
        <h1 className={`text-base font-semibold ${darkMode ? 'text-white' : 'text-slate-900'}`}>
          Analysis Results
        </h1>
        
        {/* Buttons Wrapper */}
        <div className={`flex items-center gap-3 ${darkMode ? 'text-white' : 'text-slate-900'}`}>
          {/* Dark Mode Toggle */}
          <button
            onClick={() => setDarkMode(!darkMode)}
            className={`p-2 rounded-full transition-all duration-300 hover:scale-110 ${
              darkMode
                ? 'bg-slate-700 hover:bg-slate-600'
                : 'bg-white shadow-sm hover:shadow-md border border-slate-200'
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
          
          {/* New Query Button */}
          <button
            onClick={onBackToQuery}
            className={`px-2 py-1 rounded text-xs font-medium transition-colors flex-shrink-0 whitespace-nowrap ${
              darkMode
                ? 'bg-slate-700 hover:bg-slate-600 text-white'
                : 'bg-slate-200 hover:bg-slate-300 text-slate-900'
            }`}
          >
            ← New Query
          </button>
        </div>
      </div>

      {/* Chat Messages Area */}
      <div className="flex-1 overflow-y-auto p-3">
        <div className="max-w-3xl mx-auto space-y-3">
          {displayResults.length > 0 ? (
            displayResults.map((result, index) => {
              let filePathAndLines = ''
              let codeSnippet = ''
              let textContribution = alphaWeights.text
              let visualContribution = alphaWeights.visual

              if (Array.isArray(result)) {
                filePathAndLines = result[0] || 'Unknown File'
                codeSnippet = result[1] || ''
              } else {
                filePathAndLines = result.filePathAndLines || `${result.file} (${result.lines})` || 'Unknown File'
                codeSnippet = result.codeSnippet || result.code || ''
                textContribution = result.textContribution || textContribution
                visualContribution = result.visualContribution || visualContribution
              }

              return (
                <div key={index} className="flex justify-start">
                  <div className={`max-w-2xl rounded-lg p-3 ${
                    darkMode
                      ? 'bg-slate-800 border border-slate-700'
                      : 'bg-slate-100 border border-slate-200'
                  }`}>
                    {/* Result Header with rank and copy button */}
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-start gap-2">
                        <div className={`flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold flex-shrink-0 ${
                          darkMode
                            ? 'bg-indigo-600 text-white'
                            : 'bg-indigo-100 text-indigo-700'
                        }`}>
                          {index + 1}
                        </div>
                        <div>
                          <p className={`font-semibold text-sm ${
                            darkMode ? 'text-white' : 'text-slate-900'
                          }`}>
                            {filePathAndLines}
                          </p>
                          <div className="flex gap-2 text-xs mt-0.5">
                            <span className={`flex items-center gap-1 ${
                              darkMode ? 'text-slate-400' : 'text-slate-600'
                            }`}>
                              <span className="w-2 h-2 bg-blue-400 rounded-full" /> Text {textContribution}%
                            </span>
                            <span className={`flex items-center gap-1 ${
                              darkMode ? 'text-slate-400' : 'text-slate-600'
                            }`}>
                              <span className="w-2 h-2 bg-purple-500 rounded-full" /> Visual {visualContribution}%
                            </span>
                          </div>
                        </div>
                      </div>
                      <button
                        onClick={() => handleCopyResult(index)}
                        className={`px-2 py-1 rounded text-xs font-medium whitespace-nowrap transition-all ${
                          copiedIndex === index
                            ? 'bg-green-100 text-green-700'
                            : darkMode
                              ? 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                              : 'bg-white text-slate-600 hover:bg-slate-200 border border-slate-300'
                        }`}
                      >
                        {copiedIndex === index ? '✓ Copied' : '📋 Copy'}
                      </button>
                    </div>

                    {/* Code snippet */}
                    <pre className={`text-xs font-mono p-2 rounded overflow-x-auto max-h-32 ${
                      darkMode
                        ? 'bg-slate-900 text-slate-100 border border-slate-700'
                        : 'bg-slate-900 text-slate-100'
                    }`}>
                      <code>{codeSnippet}</code>
                    </pre>
                  </div>
                </div>
              )
            })
          ) : (
            <div className={`p-8 rounded-lg text-center ${
              darkMode ? 'bg-slate-800 text-slate-400' : 'bg-slate-100 text-slate-600'
            }`}>
              <p>No results available</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default App
