import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { FaPlus, FaHistory, FaFileUpload, FaPaperPlane, FaRobot, FaHome, FaTrash, FaComments, FaSpinner } from 'react-icons/fa';
import './TryPage.css';
import ResultsDisplay from './ResultsDisplay';
import ExpertChat from './ExpertChat';

function TryPage() {
    const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
    const [history, setHistory] = useState([]);
    const [currentResult, setCurrentResult] = useState(null);
    const [loading, setLoading] = useState(false);
    const [progressMessage, setProgressMessage] = useState("");
    const [inputText, setInputText] = useState("");
    const [fileName, setFileName] = useState("");
    const [userQuery, setUserQuery] = useState(null);
    const [expertChatOpen, setExpertChatOpen] = useState(false);
    const [visualExpanded, setVisualExpanded] = useState(false);
    const [enableVisualAnalysis, setEnableVisualAnalysis] = useState(false);
    const [errorMessage, setErrorMessage] = useState(null);
    const [viewingHistoryItem, setViewingHistoryItem] = useState(null);  // For viewing history while loading
    const [processingJob, setProcessingJob] = useState(null); // Track active job info {id, title, status}
    const fileInputRef = useRef(null);
    const pollingRef = useRef(null);

    // Load saved history when page loads
    useEffect(() => {
        const savedHistory = JSON.parse(localStorage.getItem('truth_history') || '[]');
        setHistory(savedHistory);

        return () => {
            if (pollingRef.current) clearTimeout(pollingRef.current);
        };
    }, []);

    const startNewChat = () => {
        setCurrentResult(null);
        setInputText("");
        setFileName("");
        setUserQuery(null);
        setProgressMessage("");
        setEnableVisualAnalysis(false);
        setErrorMessage(null);
        setViewingHistoryItem(null);
        // Don't clear processingJob here as user might want to start new while one runs (though rare)
        // But for now, let's assume one job at a time for simplicity in UI
        if (!loading) setProcessingJob(null);

        if (pollingRef.current) clearTimeout(pollingRef.current);
        if (fileInputRef.current) {
            fileInputRef.current.value = ""; // Clear file input
        }
    };

    // Store the selected file name
    const handleFileSelect = (e) => {
        const file = e.target.files[0];
        if (file) {
            setFileName(file.name);
        }
    };

    // Load a previous analysis from history (can be done while loading)
    const loadHistoryItem = (item) => {
        console.log("DEBUG loadHistoryItem: item.data =", item.data);
        console.log("DEBUG loadHistoryItem: visual_analysis =", item.data?.visual_analysis);
        setViewingHistoryItem(item);  // Track we're viewing a history item
        setCurrentResult(item.data);
        setErrorMessage(null);  // Clear any errors
        setUserQuery({ type: 'history', content: item.title });  // Show the title
    };

    // Delete a specific history item
    const deleteHistoryItem = (e, itemId) => {
        e.stopPropagation(); // Prevent triggering loadHistoryItem
        const updatedHistory = history.filter(item => item.id !== itemId);
        setHistory(updatedHistory);
        localStorage.setItem('truth_history', JSON.stringify(updatedHistory));
    };

    // Main handler - decides whether to upload video or analyze text
    const handleSearch = async () => {
        if (fileInputRef.current.files[0]) {
            // User selected a video file
            await processFileUpload(fileInputRef.current.files[0]);
        } else if (inputText.trim()) {
            // User typed text
            await processTextAnalysis(inputText.trim());
        } else {
            alert("Please upload a video or type your query.");
        }
    };

    // Polling function
    const pollJobStatus = async (jobId, titleForHistory) => {
        try {
            const statusResponse = await axios.get(`${API_URL}/api/status/${jobId}`);
            const statusData = statusResponse.data;

            console.log("Job Status:", statusData); // Debug log

            if (statusData.status === 'complete') {
                setLoading(false);
                setProcessingJob(null); // Job done, remove from processing list
                setProgressMessage("Complete!");

                // Final result
                const resultData = statusData.result;

                // Save to history - FIXED: Use functional update to get latest history
                const newHistoryItem = {
                    id: Date.now(),
                    title: titleForHistory,
                    data: resultData
                };

                setHistory(prevHistory => {
                    const updatedHistory = [newHistoryItem, ...prevHistory];
                    localStorage.setItem('truth_history', JSON.stringify(updatedHistory));
                    return updatedHistory;
                });

                setCurrentResult(resultData);
                console.log("DEBUG: Full resultData:", resultData);
                console.log("DEBUG: visual_analysis key exists?", 'visual_analysis' in resultData);
                console.log("DEBUG: visual_analysis value:", resultData.visual_analysis);

            } else if (statusData.status === 'error') {
                setLoading(false);
                setProcessingJob(null); // Job failed, remove from processing list
                setProgressMessage("");
                setViewingHistoryItem(null);  // Clear history view

                // Set error message for inline display
                const errorMsg = statusData.error || 'Analysis failed due to an unknown error';
                setErrorMessage(errorMsg);

                // NEW: Check if we have partial results (like visual analysis) even on error
                if (statusData.result && statusData.result.visual_analysis) {
                    console.log("Showing partial result despite error");
                    setCurrentResult(statusData.result);
                }
            } else {
                // Still processing
                setProgressMessage(statusData.progress || "Processing...");
                // Poll again in 3 seconds
                pollingRef.current = setTimeout(() => pollJobStatus(jobId, titleForHistory), 3000);
            }
        } catch (err) {
            console.error("Polling error:", err);
            // Don't stop polling on transient network errors, just retry
            pollingRef.current = setTimeout(() => pollJobStatus(jobId, titleForHistory), 5000);
        }
    };

    // Handle video file upload
    const processFileUpload = async (file) => {
        // Display the video file in chat area
        setUserQuery({ type: 'video', content: file.name });

        setLoading(true);
        setCurrentResult(null);
        setProgressMessage("Uploading video...");

        const formData = new FormData();
        formData.append("file", file);
        formData.append("enable_visual_analysis", enableVisualAnalysis.toString());

        try {
            const response = await axios.post(
                `${API_URL}/api/upload-video`,
                formData,
                {
                    headers: { "Content-Type": "multipart/form-data" },
                    timeout: 60000 // 60 second timeout for upload
                }
            );

            // Start polling with job_id
            const { job_id } = response.data;
            setProgressMessage("Queued for analysis...");
            setProcessingJob({ id: job_id, title: file.name, status: 'processing' });
            pollJobStatus(job_id, file.name);

            // Clear file input after successful upload
            if (fileInputRef.current) {
                fileInputRef.current.value = "";
            }
            setFileName("");

        } catch (err) {
            console.error("Upload error:", err);
            setLoading(false);
            setProcessingJob(null);
            setProgressMessage("");

            if (err.response) {
                alert(`Upload failed: ${err.response.data.detail || err.response.statusText}`);
            } else if (err.request) {
                alert("Upload failed: No response from server. Check backend connection.");
            } else {
                alert(`Upload failed: ${err.message}`);
            }
        }
    };

    // Handle text-only analysis
    const processTextAnalysis = async (text) => {
        // Display the text query in chat area
        setUserQuery({ type: 'text', content: text });

        setLoading(true);
        setCurrentResult(null);
        setProgressMessage("Sending request...");

        try {
            const response = await axios.post(
                `${API_URL}/api/analyze-text`,
                { text: text },
                { timeout: 30000 } // 30 second timeout
            );

            // Start polling with job_id
            const { job_id } = response.data;
            setProgressMessage("Queued for analysis...");
            const title = text.substring(0, 30) + "...";
            setProcessingJob({ id: job_id, title: title, status: 'processing' });
            pollJobStatus(job_id, title);
        } catch (err) {
            console.error("Analysis error:", err);
            setLoading(false);
            setProcessingJob(null);
            setProgressMessage("");

            if (err.response) {
                alert(`Request failed: ${err.response.data.detail || err.response.statusText}`);
            } else if (err.request) {
                alert("Request failed: No response from server. Check backend connection.");
            } else {
                alert(`Request failed: ${err.message}`);
            }
        }
    };

    return (
        <div className="app-container">
            {/* Sidebar with navigation */}
            <aside className="sidebar">
                <Link to="/" className="home-btn">
                    <FaHome /> Home
                </Link>

                <button className="new-chat-btn" onClick={startNewChat}>
                    <FaPlus /> New Analysis
                </button>

                <div className="history-list">
                    <p className="history-label">Recent</p>

                    {/* Active Processing Job */}
                    {processingJob && (
                        <div
                            className={`history-item ${!viewingHistoryItem ? 'active' : ''}`}
                            onClick={() => {
                                setViewingHistoryItem(null); // Return to live view
                                setErrorMessage(null);
                            }}
                            style={{ borderLeft: '3px solid #667eea', background: 'rgba(102, 126, 234, 0.1)' }}
                        >
                            <FaSpinner className="history-icon fa-spin" style={{ animation: 'spin 1s linear infinite' }} />
                            <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                                <span className="history-title" style={{ color: '#fff' }}>{processingJob.title}</span>
                                <span style={{ fontSize: '0.75rem', color: '#a0a0a0' }}>Processing...</span>
                            </div>
                        </div>
                    )}

                    {history.map((item) => (
                        <div
                            key={item.id}
                            className={`history-item ${viewingHistoryItem?.id === item.id ? 'active' : ''}`}
                            onClick={() => loadHistoryItem(item)}
                        >
                            <FaHistory className="history-icon" />
                            <span className="history-title">{item.title}</span>
                            <button
                                className="delete-history-btn"
                                onClick={(e) => deleteHistoryItem(e, item.id)}
                                title="Delete"
                            >
                                <FaTrash />
                            </button>
                        </div>
                    ))}
                </div>
            </aside>

            {/* Main content area */}
            <main className="main-content">
                <div className="chat-scroll-area">
                    {/* Show welcome screen when idle */}
                    {!currentResult && !loading && !userQuery && (
                        <div className="welcome-screen">
                            <h1>SATYA</h1>
                            <p className="welcome-text">
                                Upload a video or type your query to verify facts against reality.
                            </p>
                            <div className="suggestion-pills">
                                <span className="suggestion-pill">Verify political speeches</span>
                                <span className="suggestion-pill">Check news reports</span>
                                <span className="suggestion-pill">Analyze documentary claims</span>
                            </div>
                        </div>
                    )}

                    {/* ALWAYS show user's query at top when present */}
                    {userQuery && (
                        <div className="user-message-container">
                            <div className="user-message">
                                {userQuery.type === 'video' ? (
                                    <>
                                        <FaFileUpload style={{ marginRight: '8px' }} />
                                        {userQuery.content}
                                    </>
                                ) : (
                                    userQuery.content
                                )}
                            </div>
                        </div>
                    )}

                    {/* Show loading spinner during analysis - ONLY when not viewing history */}
                    {loading && !viewingHistoryItem && (
                        <div className="loading-container">
                            <div className="loading-spinner"></div>
                            <p className="loading-text">
                                {progressMessage || "Processing..."}
                                <br />
                                <span className="loading-subtext">(This may take a few minutes)</span>
                            </p>
                        </div>
                    )}

                    {/* Error display */}
                    {errorMessage && !currentResult && (
                        <div style={{
                            background: 'rgba(220, 53, 69, 0.15)',
                            border: '1px solid rgba(220, 53, 69, 0.5)',
                            borderRadius: '12px',
                            padding: '1.5rem',
                            marginBottom: '1rem',
                            textAlign: 'center'
                        }}>
                            <h3 style={{ color: '#dc3545', marginBottom: '0.5rem' }}>
                                ❌ Analysis Failed
                            </h3>
                            <p style={{ color: '#e0e0e0', marginBottom: '1rem', fontSize: '0.95rem' }}>
                                {errorMessage}
                            </p>
                            <button
                                onClick={startNewChat}
                                style={{
                                    background: 'rgba(102, 126, 234, 0.8)',
                                    border: 'none',
                                    padding: '10px 24px',
                                    borderRadius: '8px',
                                    color: 'white',
                                    cursor: 'pointer',
                                    fontWeight: '500'
                                }}
                            >
                                Try Again
                            </button>
                        </div>
                    )}

                    {/* Results with Visual Analysis and Ask Expert button */}
                    {currentResult && currentResult.verdict && (
                        <>
                            <ResultsDisplay
                                verdict={currentResult.verdict}
                                visualAnalysis={currentResult.visual_analysis}
                            />



                            {/* Ask Expert Button */}
                            <div className="ask-expert-container">
                                <button className="ask-expert-btn" onClick={() => setExpertChatOpen(true)}>
                                    <FaComments />
                                    <span>Still have doubts? Ask the Expert</span>
                                </button>
                            </div>
                        </>
                    )}
                </div>

                {/* Input bar at the bottom */}
                <div className="input-container">
                    {/* Visual Analysis Toggle - Only shown when video file is selected */}
                    {fileName && (
                        <div style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '10px',
                            marginBottom: '10px',
                            padding: '10px 15px',
                            background: 'rgba(102, 126, 234, 0.15)',
                            borderRadius: '8px',
                            border: '1px solid rgba(102, 126, 234, 0.3)'
                        }}>
                            <input
                                type="checkbox"
                                id="visual-analysis-toggle"
                                checked={enableVisualAnalysis}
                                onChange={(e) => setEnableVisualAnalysis(e.target.checked)}
                                style={{ width: '18px', height: '18px', cursor: 'pointer' }}
                            />
                            <label htmlFor="visual-analysis-toggle" style={{ color: '#e0e0e0', cursor: 'pointer' }}>
                                Enable Visual Analysis
                                <span style={{ color: '#888', fontSize: '0.85rem', marginLeft: '5px' }}>
                                    (compares video frames with transcript)
                                </span>
                            </label>
                        </div>
                    )}

                    <div className="input-bar">
                        {/* Hidden file input */}
                        <input
                            type="file"
                            ref={fileInputRef}
                            style={{ display: 'none' }}
                            onChange={handleFileSelect}
                            accept="video/*,audio/*"
                        />

                        {/* Upload Button */}
                        <div
                            className="upload-btn"
                            onClick={() => fileInputRef.current.click()}
                            title="Upload Video"
                        >
                            <FaFileUpload />
                        </div>

                        <input
                            type="text"
                            className="text-input"
                            placeholder={fileName ? `Ready to analyze: ${fileName}` : "Upload a video or type your query to begin..."}
                            value={inputText}
                            onChange={(e) => setInputText(e.target.value)}
                            onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
                        />

                        <button className="send-btn" onClick={handleSearch}>
                            <FaPaperPlane />
                        </button>
                    </div>
                    <p className="disclaimer-text">
                        Truth Engine may display inaccurate info, including about people, so double-check its responses.
                    </p>
                </div>
            </main>

            {/* Expert Chat Sidebar */}
            <ExpertChat
                isOpen={expertChatOpen}
                onClose={() => setExpertChatOpen(false)}
                caseId={currentResult?.case_id}
                analysisData={currentResult}
            />
        </div>
    );
}

export default TryPage;