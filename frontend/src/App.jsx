import { useState, useEffect, useRef } from 'react'

function App() {
  const [currentState, setCurrentState] = useState('QUERY')
  const [repositoryUrl, setRepositoryUrl] = useState('')
  const [repositoryIndexed, setRepositoryIndexed] = useState(false)
  const [indexedRepoName, setIndexedRepoName] = useState('')
  const [indexedBranchName, setIndexedBranchName] = useState('')
  const [bugDescription, setBugDescription] = useState('')
  const [targetFileHint, setTargetFileHint] = useState('')
  const [uploadedFile, setUploadedFile] = useState(null)
  const [imagePreview, setImagePreview] = useState(null)
  const [loadingMessage, setLoadingMessage] = useState('Parsing ASTs with Tree-sitter...')
  const [dragActive, setDragActive] = useState(false)
  const [darkMode, setDarkMode] = useState(true)
  const [indexedFiles, setIndexedFiles] = useState([]) // Files from indexed repo
  const [conversationHistory, setConversationHistory] = useState([]) // Chat-like conversation
  const [isAnalyzing, setIsAnalyzing] = useState(false) // Track if analyzing bug in conversation
  const [carouselIndex, setCarouselIndex] = useState({}) // Track carousel index for each result
  const [menuOpen, setMenuOpen] = useState(false) // Burger menu toggle
  const [queryHistory, setQueryHistory] = useState([]) // Query history for sidebar
  const chatEndRef = useRef(null) // Files from indexed repo

  // Load query history from localStorage on mount and save repo context
  useEffect(() => {
    const saved = localStorage.getItem(`ms2c_history_${indexedRepoName}`)
    if (saved && repositoryIndexed) {
      try {
        setQueryHistory(JSON.parse(saved))
      } catch (e) {
        console.error('Failed to load query history:', e)
      }
    }
  }, [repositoryIndexed, indexedRepoName])

  // Save query history to localStorage whenever it changes
  useEffect(() => {
    if (repositoryIndexed && indexedRepoName && queryHistory.length > 0) {
      localStorage.setItem(`ms2c_history_${indexedRepoName}`, JSON.stringify(queryHistory))
    }
  }, [queryHistory, repositoryIndexed, indexedRepoName])

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

      // Extract repo name and branch from URL
      const url = repositoryUrl.trim()
      let repoName = 'Repository'
      let branchName = 'main'
      
      // Parse GitHub URL format: https://github.com/org/repo or https://github.com/org/repo/tree/branch
      const parts = url.split('/')
      if (parts.length >= 4) {
        // Check if URL contains /tree/ for branch specification
        const treeIndex = parts.indexOf('tree')
        if (treeIndex > 0 && parts.length > treeIndex + 1) {
          // Format: https://github.com/org/repo/tree/branch
          repoName = parts[treeIndex - 1] // repo name is right before /tree/
          branchName = parts.slice(treeIndex + 1).join('/') // branch can contain slashes
        } else {
          // Format: https://github.com/org/repo (no branch specified)
          repoName = parts[parts.length - 1] || 'Repository'
          branchName = 'main' // default branch
        }
      }
      
      setIndexedRepoName(repoName)
      setIndexedBranchName(branchName)
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
    if (!bugDescription.trim()) return

    // Add bug to conversation
    const bugMessage = {
      id: Date.now(),
      type: 'bug',
      description: bugDescription,
      targetFile: targetFileHint,
      image: imagePreview,
    }
    setConversationHistory([bugMessage])

    // Start analyzing - show loading in conversation
    setIsAnalyzing(true)

    try {
      const formData = new FormData()
      
      // CRITICAL: Append target file hint to bug description if selected
      let finalDescription = bugDescription.trim()
      if (targetFileHint && targetFileHint.trim()) {
        finalDescription = `${finalDescription} [Context: ${targetFileHint}]`
      }
      
      formData.append('bug_description', finalDescription)
      
      // Only append screenshot if one was uploaded
      if (uploadedFile) {
        formData.append('screenshot', uploadedFile)
      }

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

      // Add result to conversation
      const resultMessage = {
        id: Date.now() + 1,
        type: 'result',
        candidates: data.candidates || [],
        alphaWeights: {
          text: Math.round((data.alpha_text || 0.5) * 100),
          visual: Math.round((data.alpha_visual || 0.5) * 100),
        },
      }
      setConversationHistory(prev => [...prev, resultMessage])

      // Save to query history for sidebar
      const historyItem = {
        id: Date.now(),
        description: bugDescription.trim(),
        targetFile: targetFileHint,
        timestamp: new Date().toLocaleString(),
        conversationId: bugMessage.id,
        resultCount: data.candidates ? data.candidates.length : 0,
        candidates: data.candidates || [],
        alphaWeights: {
          text: Math.round((data.alpha_text || 0.5) * 100),
          visual: Math.round((data.alpha_visual || 0.5) * 100),
        },
        image: imagePreview,
      }
      console.log('💾 Saving to query history:', {
        id: historyItem.id,
        description: historyItem.description.substring(0, 50),
        candidatesCount: historyItem.candidates.length,
        candidates: historyItem.candidates
      })
      setQueryHistory(prev => [historyItem, ...prev])

      // Clear form
      setBugDescription('')
      setTargetFileHint('')
      setUploadedFile(null)
      setImagePreview(null)

      // Scroll to bottom
      setTimeout(() => {
        chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
      }, 100)
    } catch (error) {
      console.error('❌ Diagnosis error full:', error)
      console.error('   Error type:', error.constructor.name)
      console.error('   Error message:', error.message)
      alert(`Diagnosis failed: ${error.message}\n\nMake sure the backend is running on http://localhost:8000`)
      
      // Remove the bug message from history on error
      setConversationHistory(prev => prev.slice(0, -1))
    } finally {
      // Stop analyzing
      setIsAnalyzing(false)
    }
  }

  const _handleBackToQuery = () => {
    setCurrentState('QUERY')
    setBugDescription('')
    setTargetFileHint('')
    setUploadedFile(null)
    setImagePreview(null)
    setConversationHistory([])
    setIsAnalyzing(false)
  }

  const handleChangeRepository = () => {
    setRepositoryIndexed(false)
    setIndexedRepoName('')
    setIndexedBranchName('')
    setRepositoryUrl('')
    setIndexedFiles([])
    setBugDescription('')
    setTargetFileHint('')
    setUploadedFile(null)
    setImagePreview(null)
    setConversationHistory([])
    setQueryHistory([])
    setMenuOpen(false)
  }

  const handleLoadHistoryItem = (historyItem) => {
    console.log('🔄 Loading history item:', {
      id: historyItem.id,
      description: historyItem.description,
      hasCandidates: !!historyItem.candidates,
      candidatesLength: historyItem.candidates?.length || 0,
      candidates: historyItem.candidates
    })

    // Save current query to history if it exists
    if (conversationHistory.length > 0) {
      const currentBug = conversationHistory.find(item => item.type === 'bug')
      const currentResult = conversationHistory.find(item => item.type === 'result')
      if (currentBug) {
        setQueryHistory(prev => [{
          id: currentBug.id,
          description: currentBug.description,
          targetFile: currentBug.targetFile,
          timestamp: new Date().toLocaleString(),
          conversationId: currentBug.id,
          resultCount: currentResult && currentResult.candidates ? currentResult.candidates.length : 0,
          candidates: currentResult ? currentResult.candidates : [],
          alphaWeights: currentResult ? currentResult.alphaWeights : { text: 50, visual: 50 },
          image: currentBug.image,
        }, ...prev.filter(item => item.id !== historyItem.id)])
      }
    }

    // Load clicked history item as current
    const newConversation = [
      {
        id: historyItem.conversationId || Date.now(),
        type: 'bug',
        description: historyItem.description,
        targetFile: historyItem.targetFile,
        image: historyItem.image,
      },
    ]

    if (historyItem.candidates && historyItem.candidates.length > 0) {
      console.log('✅ Adding result item to conversation')
      newConversation.push({
        id: historyItem.id || Date.now() + 1,
        type: 'result',
        candidates: historyItem.candidates || [],
        alphaWeights: historyItem.alphaWeights || { text: 50, visual: 50 },
      })
    } else {
      console.warn('⚠️ No candidates found in history item')
    }

    console.log('📋 New conversation:', newConversation)
    setConversationHistory(newConversation)
    setCarouselIndex({})
    setMenuOpen(false)
  }

  const handleDeleteHistoryItem = (id) => {
    setQueryHistory(prev => prev.filter(item => item.id !== id))
  }

  const handleClearAllHistory = () => {
    setQueryHistory([])
    localStorage.removeItem(`ms2c_history_${indexedRepoName}`)
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
      {currentState === 'LOADING' && (
        <LoadingState
          message={loadingMessage}
          darkMode={darkMode}
        />
      )}

      {currentState === 'QUERY' && (
        <QueryState
          repositoryUrl={repositoryUrl}
          setRepositoryUrl={setRepositoryUrl}
          repositoryIndexed={repositoryIndexed}
          indexedRepoName={indexedRepoName}
          indexedBranchName={indexedBranchName}
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
          conversationHistory={conversationHistory}
          chatEndRef={chatEndRef}
          isAnalyzing={isAnalyzing}
          carouselIndex={carouselIndex}
          setCarouselIndex={setCarouselIndex}
          menuOpen={menuOpen}
          setMenuOpen={setMenuOpen}
          queryHistory={queryHistory}
          onLoadHistoryItem={handleLoadHistoryItem}
          onDeleteHistoryItem={handleDeleteHistoryItem}
          onClearAllHistory={handleClearAllHistory}
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
  indexedBranchName,
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
  conversationHistory = [],
  chatEndRef,
  isAnalyzing = false,
  carouselIndex = {},
  setCarouselIndex = () => {},
  menuOpen = false,
  setMenuOpen = () => {},
  queryHistory = [],
  onLoadHistoryItem = () => {},
  onDeleteHistoryItem = () => {},
  onClearAllHistory = () => {},
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
              📦 {indexedRepoName} {indexedBranchName && `- ${indexedBranchName} branch`}
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

      {/* Query History Sidebar */}
      {repositoryIndexed && (
        <div className={`fixed left-0 top-16 h-[calc(100vh-4rem)] w-64 z-50 transform transition-transform duration-300 flex flex-col ${
          menuOpen ? 'translate-x-0' : '-translate-x-full'
        } ${
          darkMode
            ? 'bg-slate-800 border-r border-slate-700'
            : 'bg-white border-r border-slate-200'
        }`}>
          {/* Sidebar Header */}
          <div className={`p-4 border-b flex-shrink-0 ${darkMode ? 'border-slate-700' : 'border-slate-200'} flex items-center justify-between`}>
            <h2 className={`font-semibold flex items-center gap-2 ${darkMode ? 'text-white' : 'text-slate-900'}`}>
              <span>📋</span> Query History
            </h2>
            <button
              onClick={() => setMenuOpen(false)}
              className={`p-1 rounded hover:bg-slate-700 flex-shrink-0 ${darkMode ? 'text-slate-400' : 'text-slate-600'}`}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Sidebar Content */}
          <div className="flex-1 overflow-y-auto p-3 space-y-2 min-h-0">
            {queryHistory.length === 0 ? (
              <p className={`text-xs text-center py-4 ${darkMode ? 'text-slate-500' : 'text-slate-400'}`}>
                No queries yet
              </p>
            ) : (
              queryHistory.map((item) => {
                console.log('🧩 Rendering history item:', {
                  id: item.id,
                  description: item.description?.substring(0, 30),
                  hasCandidates: !!item.candidates,
                  candidatesLength: item.candidates?.length || 0,
                  resultCount: item.resultCount
                })
                return (
                <div
                  key={item.id}
                  onClick={() => onLoadHistoryItem(item)}
                  className={`p-3 rounded-lg border cursor-pointer transition-all hover:shadow-md ${
                    darkMode
                      ? 'bg-slate-700/50 border-slate-600 hover:bg-slate-700'
                      : 'bg-slate-50 border-slate-200 hover:bg-slate-100'
                  }`}
                >
                  <p className={`text-xs font-semibold mb-1 line-clamp-2 ${
                    darkMode ? 'text-slate-200' : 'text-slate-900'
                  }`}>
                    {item.description}
                  </p>
                  {item.targetFile && (
                    <p className={`text-xs mb-1 ${darkMode ? 'text-slate-400' : 'text-slate-600'}`}>
                      📄 {item.targetFile}
                    </p>
                  )}
                  <div className={`text-xs mb-2 flex items-center justify-between gap-1 ${
                    darkMode ? 'text-slate-500' : 'text-slate-500'
                  }`}>
                    <span>{item.timestamp}</span>
                    <span className={`px-2 py-0.5 rounded text-xs font-semibold ${
                      darkMode ? 'bg-indigo-900/50 text-indigo-300' : 'bg-indigo-100 text-indigo-700'
                    }`}>
                      {item.resultCount} results
                    </span>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      onDeleteHistoryItem(item.id)
                    }}
                    className={`w-full text-xs py-1 rounded transition-colors ${
                      darkMode
                        ? 'text-slate-400 hover:bg-red-900/20 hover:text-red-400'
                        : 'text-slate-600 hover:bg-red-100 hover:text-red-600'
                    }`}
                  >
                    🗑️ Delete
                  </button>
                </div>
                )
              })
            )}
          </div>

          {/* Sidebar Footer - Clear All Button */}
          {queryHistory.length > 0 && (
            <div className={`p-3 border-t flex-shrink-0 ${darkMode ? 'border-slate-700' : 'border-slate-200'}`}>
              <button
                onClick={onClearAllHistory}
                className={`w-full text-xs py-2 rounded font-medium transition-colors ${
                  darkMode
                    ? 'bg-red-900/30 text-red-300 hover:bg-red-900/50'
                    : 'bg-red-100 text-red-700 hover:bg-red-200'
                }`}
              >
                Clear All History
              </button>
            </div>
          )}
        </div>
      )}

      {/* Floating Burger Button - Left side at top */}
      {repositoryIndexed && (
        <button
          onClick={() => setMenuOpen(!menuOpen)}
          className={`fixed left-4 top-20 p-3 rounded-full shadow-lg z-30 transition-all duration-300 hover:scale-110 ${
            menuOpen ? 'invisible' : 'visible'
          } ${
            darkMode
              ? 'bg-indigo-600 hover:bg-indigo-700 text-white'
              : 'bg-indigo-600 hover:bg-indigo-700 text-white'
          }`}
          title="Query History"
        >
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
      )}

      {/* Overlay - Close menu when clicking outside */}
      {menuOpen && (
        <div
          className="fixed inset-0 bg-black/30 z-20"
          onClick={() => setMenuOpen(false)}
        />
      )}

      {/* Chat Area - Conversation History */}
      {!repositoryIndexed ? (
        // Repository indexing form
        <div className="flex-1 overflow-y-auto p-3 pt-4 flex items-center justify-center">
          <div className="text-center max-w-sm mx-auto w-full">
            <div className="text-4xl mb-2">🔗</div>
            <h2 className={`text-xl font-semibold mb-1 ${
              darkMode ? 'text-white' : 'text-slate-900'
            }`}>
              Index a Repository
            </h2>
            <p className={`text-sm mb-6 ${
              darkMode ? 'text-slate-400' : 'text-slate-600'
            }`}>
              Enter a GitHub URL to get started
            </p>
            
            {/* Form moved here */}
            <div className="space-y-2">
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
            </div>
          </div>
        </div>
      ) : (
        // Conversation history display
        <>
          {conversationHistory.length === 0 ? (
            // "Report a Bug" prompt - centered in middle of screen when no conversation
            <div className={`flex-1 flex items-center justify-center p-4 transition-all duration-300 ${menuOpen ? 'pl-64' : 'pl-0'}`}>
              <div className="text-center">
                <div className="text-6xl mb-4">🐛</div>
                <h2 className={`text-2xl font-semibold mb-2 ${
                  darkMode ? 'text-white' : 'text-slate-900'
                }`}>
                  Report a Bug
                </h2>
                <p className={`text-sm ${
                  darkMode ? 'text-slate-400' : 'text-slate-600'
                }`}>
                  Describe the issue and upload a screenshot below
                </p>
              </div>
            </div>
          ) : (
            // Display conversation items
            <div className={`flex-1 overflow-y-auto p-4 flex items-center justify-center transition-all duration-300 ${menuOpen ? 'pl-64' : 'pl-0'}`}>
              <div className="max-w-7xl w-full space-y-4">
              {(() => {
                // Find the last bug and check if result follows it
                let bugIndex = -1
                for (let i = conversationHistory.length - 1; i >= 0; i--) {
                  if (conversationHistory[i].type === 'bug') {
                    bugIndex = i
                    break
                  }
                }
                
                if (bugIndex === -1) return null // No bug found
                
                const bugItem = conversationHistory[bugIndex]
                const resultItem = conversationHistory[bugIndex + 1]
                const hasResult = resultItem && resultItem.type === 'result'
                
                console.log('📊 Display logic check:', {
                  conversationHistoryLength: conversationHistory.length,
                  bugIndex,
                  resultItemExists: !!resultItem,
                  resultItemType: resultItem?.type,
                  hasResult,
                  conversationHistory: conversationHistory.map(item => ({ type: item.type, id: item.id }))
                })
                
                return (
                  <div key={bugItem.id} className={`grid gap-4 ${hasResult ? 'grid-cols-2' : 'grid-cols-1'}`}>
                      {/* Left side: Bug details */}
                      <div className={`p-4 rounded-lg flex flex-col max-h-96 overflow-y-auto ${
                        darkMode
                          ? 'bg-slate-800/50 border border-slate-700'
                          : 'bg-slate-100 border border-slate-200'
                      }`}>
                        <h3 className={`text-sm font-semibold mb-2 flex items-center gap-2 ${
                          darkMode ? 'text-slate-200' : 'text-slate-900'
                        }`}>
                          <span>📝 Your Bug Report</span>
                        </h3>
                        <p className={`text-sm break-words whitespace-pre-wrap ${
                          darkMode ? 'text-slate-300' : 'text-slate-700'
                        }`}>
                          {bugItem.description}
                        </p>
                        {bugItem.targetFile && (
                          <p className={`text-xs mt-2 ${
                            darkMode ? 'text-slate-400' : 'text-slate-600'
                          }`}>
                            📄 File: <span className="font-mono">{bugItem.targetFile}</span>
                          </p>
                        )}
                        {bugItem.image && (
                          <div className="mt-3 max-h-40 overflow-hidden rounded">
                            <img 
                              src={bugItem.image} 
                              alt="Bug screenshot" 
                              className="w-full h-full object-cover rounded border border-slate-600"
                            />
                          </div>
                        )}
                      </div>

                      {/* Right side: Analysis Results Carousel */}
                      {hasResult && resultItem && (
                        <div className={`p-4 rounded-lg flex flex-col ${
                          darkMode
                            ? 'bg-indigo-900/20 border border-indigo-700/50'
                            : 'bg-indigo-50 border border-indigo-200'
                        }`}>
                          <h3 className={`text-sm font-semibold mb-3 flex items-center gap-2 ${
                            darkMode ? 'text-indigo-200' : 'text-indigo-900'
                          }`}>
                            <span>✨ Analysis Result</span>
                          </h3>
                          
                          {resultItem.candidates && resultItem.candidates.length > 0 ? (
                            <div className="flex-1 flex flex-col">
                              {/* Carousel */}
                              <div className="flex-1">
                                {(() => {
                                  const currentIdx = carouselIndex[bugItem.id] || 0
                                  const candidate = resultItem.candidates[currentIdx]
                                  return (
                                    <div className={`p-4 rounded text-sm h-full flex flex-col justify-between ${
                                      darkMode
                                        ? 'bg-slate-800/50 border border-slate-700/50'
                                        : 'bg-white border border-slate-200'
                                    }`}>
                                      <div>
                                        <p className={`font-semibold mb-2 flex items-center gap-2 ${
                                          darkMode ? 'text-slate-200' : 'text-slate-900'
                                        }`}>
                                          <span>📄</span> {candidate.name || candidate.file || 'Unknown'}
                                        </p>
                                        {(candidate.file || candidate.lines) && (
                                          <p className={`text-xs mb-2 ${
                                            darkMode ? 'text-slate-500' : 'text-slate-600'
                                          }`}>
                                            {candidate.file && <span>{candidate.file}</span>}
                                            {candidate.lines && <span> (Lines {candidate.lines})</span>}
                                          </p>
                                        )}
                                        {candidate.code && (
                                          <pre className={`text-xs mb-2 p-2 rounded overflow-auto max-h-24 break-words ${
                                            darkMode
                                              ? 'bg-slate-700/50 border border-slate-600 text-slate-300'
                                              : 'bg-slate-100 border border-slate-300 text-slate-700'
                                          }`}>
                                            {candidate.code}
                                          </pre>
                                        )}
                                        {candidate.explanation && (
                                          <p className={`text-xs break-words ${
                                            darkMode ? 'text-slate-400' : 'text-slate-600'
                                          }`}>
                                            {candidate.explanation}
                                          </p>
                                        )}
                                        {candidate.confidence && (
                                          <p className={`text-xs mt-2 font-semibold ${
                                            darkMode ? 'text-indigo-300' : 'text-indigo-600'
                                          }`}>
                                            Confidence: {Math.round(candidate.confidence * 100)}%
                                          </p>
                                        )}
                                      </div>
                                      <p className={`text-xs mt-3 text-center ${
                                        darkMode ? 'text-slate-500' : 'text-slate-600'
                                      }`}>
                                        {currentIdx + 1} / {resultItem.candidates.length}
                                      </p>
                                    </div>
                                  )
                                })()}
                              </div>

                              {/* Navigation buttons */}
                              {resultItem.candidates.length > 1 && (
                                <div className="flex gap-2 mt-3">
                                  <button
                                    onClick={() => setCarouselIndex({
                                      ...carouselIndex,
                                      [bugItem.id]: Math.max(0, (carouselIndex[bugItem.id] || 0) - 1)
                                    })}
                                    disabled={(carouselIndex[bugItem.id] || 0) === 0}
                                    className={`flex-1 py-2 px-3 rounded text-sm font-semibold transition-all ${
                                      (carouselIndex[bugItem.id] || 0) === 0
                                        ? darkMode
                                          ? 'bg-slate-700/30 text-slate-600 cursor-not-allowed'
                                          : 'bg-slate-200 text-slate-400 cursor-not-allowed'
                                        : darkMode
                                          ? 'bg-indigo-600 hover:bg-indigo-700 text-white'
                                          : 'bg-indigo-600 hover:bg-indigo-700 text-white'
                                    }`}
                                  >
                                    ← Previous
                                  </button>
                                  <button
                                    onClick={() => setCarouselIndex({
                                      ...carouselIndex,
                                      [bugItem.id]: Math.min(resultItem.candidates.length - 1, (carouselIndex[bugItem.id] || 0) + 1)
                                    })}
                                    disabled={(carouselIndex[bugItem.id] || 0) === resultItem.candidates.length - 1}
                                    className={`flex-1 py-2 px-3 rounded text-sm font-semibold transition-all ${
                                      (carouselIndex[bugItem.id] || 0) === resultItem.candidates.length - 1
                                        ? darkMode
                                          ? 'bg-slate-700/30 text-slate-600 cursor-not-allowed'
                                          : 'bg-slate-200 text-slate-400 cursor-not-allowed'
                                        : darkMode
                                          ? 'bg-indigo-600 hover:bg-indigo-700 text-white'
                                          : 'bg-indigo-600 hover:bg-indigo-700 text-white'
                                    }`}
                                  >
                                    Next →
                                  </button>
                                </div>
                              )}
                            </div>
                          ) : (
                            <p className={`text-xs ${
                              darkMode ? 'text-slate-400' : 'text-slate-600'
                            }`}>
                              No candidates found for this bug.
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })()}
              
              {/* Loading indicator while analyzing */}
              {isAnalyzing && (
                <div className={`p-4 rounded-lg ml-8 animate-pulse ${
                  darkMode
                    ? 'bg-indigo-900/20 border border-indigo-700/50'
                    : 'bg-indigo-50 border border-indigo-200'
                }`}>
                  <h3 className={`text-sm font-semibold flex items-center gap-2 ${
                    darkMode ? 'text-indigo-200' : 'text-indigo-900'
                  }`}>
                    <span className="inline-block animate-spin">⚙️</span> Analyzing your bug...
                  </h3>
                </div>
              )}
              
              <div ref={chatEndRef} />
              </div>
            </div>
            )}
        </>
      )}

      {/* Input Area - Compact Bug Report Form */}
      {repositoryIndexed && (
      <div className={`border-t transition-all duration-300 ${darkMode ? 'border-slate-700 bg-slate-900/50' : 'border-slate-200 bg-slate-50/50'} px-4 py-3 ${menuOpen ? 'pl-64' : 'pl-4'}`}>
        <div className="max-w-2xl mx-auto">
          {/* Form Card Container - Compact */}
          <div className={`rounded-lg p-4 transition-colors ${
            darkMode 
              ? 'bg-slate-800/60 border border-slate-700/50' 
              : 'bg-white border border-slate-200/50 shadow-sm'
          }`}>
            <div className="space-y-3">
              {/* Bug Description */}
              <div>
                <label className={`text-xs font-semibold block mb-1.5 ${
                  darkMode ? 'text-slate-300' : 'text-slate-700'
                }`}>
                  📝 Describe the bug <span className="text-red-500">*</span>
                </label>
                <textarea
                  value={bugDescription}
                  onChange={(e) => setBugDescription(e.target.value)}
                  placeholder="What's the bug?"
                  rows="2"
                  className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-transparent resize-none text-xs transition-all ${
                    darkMode
                      ? 'bg-slate-700/50 border-slate-600 text-white placeholder-slate-500'
                      : 'bg-slate-50 border-slate-300 text-slate-900 placeholder-slate-400'
                  }`}
                />
              </div>

              {/* File dropdown + Image Upload (side by side) */}
              <div className="grid grid-cols-2 gap-3">
                {/* File Hint Dropdown */}
                <div>
                  <label className={`text-xs font-semibold block mb-1 ${
                    darkMode ? 'text-slate-400' : 'text-slate-600'
                  }`}>
                    🗂️ File (optional)
                  </label>
                  <select
                    value={targetFileHint}
                    onChange={(e) => setTargetFileHint(e.target.value)}
                    className={`w-full px-2 py-1.5 border rounded text-xs focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-transparent transition-all ${
                      darkMode
                        ? 'bg-slate-700/50 border-slate-600 text-white [&_option]:bg-slate-800 [&_option]:text-white'
                        : 'bg-slate-50 border-slate-300 text-slate-900 [&_option]:bg-white [&_option]:text-slate-900'
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
                  <label className={`text-xs font-semibold block mb-1 ${
                    darkMode ? 'text-slate-400' : 'text-slate-600'
                  }`}>
                    📸 Screenshot (optional)
                  </label>
                  <div
                    onDragEnter={onDrag}
                    onDragLeave={onDrag}
                    onDragOver={onDrag}
                    onDrop={onDrop}
                    className={`border border-dashed rounded cursor-pointer p-1.5 text-center text-xs transition-all ${
                      dragActive
                        ? darkMode
                          ? 'border-indigo-400 bg-indigo-900/20'
                          : 'border-indigo-500 bg-indigo-50'
                        : darkMode
                          ? 'border-slate-600 bg-slate-700/10'
                          : 'border-slate-300 bg-slate-50'
                    }`}
                  >
                    {uploadedFile && imagePreview ? (
                      <div>
                        <img 
                          src={imagePreview} 
                          alt="Screenshot" 
                          className="w-full h-12 object-cover rounded mb-1"
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
                          className="text-xs text-indigo-500 hover:text-indigo-600 cursor-pointer block"
                        >
                          Replace
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
                          className={`block cursor-pointer ${
                            dragActive
                              ? darkMode
                                ? 'text-indigo-300'
                                : 'text-indigo-600'
                              : darkMode
                                ? 'text-slate-400 hover:text-slate-300'
                                : 'text-slate-500 hover:text-slate-700'
                          }`}
                        >
                          {dragActive ? '✓ Drop' : 'Upload'}
                        </label>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Analyze Button */}
              <button
                onClick={onDiagnoseBug}
                disabled={!bugDescription.trim() || isAnalyzing}
                className={`w-full font-semibold py-2 px-3 rounded-lg text-sm transition-all ${
                  !bugDescription.trim() || isAnalyzing
                    ? `${darkMode ? 'bg-indigo-600/40' : 'bg-indigo-500/40'} text-slate-400 cursor-not-allowed opacity-60`
                    : darkMode
                      ? 'bg-indigo-600 hover:bg-indigo-700 text-white'
                      : 'bg-indigo-600 hover:bg-indigo-700 text-white'
                }`}
              >
                {isAnalyzing ? '⏳ Analyzing...' : '🔍 Analyze Bug'}
              </button>
            </div>
          </div>
        </div>
      </div>
      )}
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
