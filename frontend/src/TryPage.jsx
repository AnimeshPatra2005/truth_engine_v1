import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { FaPlus, FaHistory, FaFileUpload, FaPaperPlane, FaRobot, FaHome, FaTrash, FaComments } from 'react-icons/fa';
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

    // Load a previous analysis from history
    const loadHistoryItem = (item) => {
        setCurrentResult(item.data);
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

            } else if (statusData.status === 'error') {
                setLoading(false);
                setProgressMessage("");
                alert(`Analysis failed: ${statusData.error || 'Unknown error occurred'}`);
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
            pollJobStatus(job_id, file.name);

            // Clear file input after successful upload
            if (fileInputRef.current) {
                fileInputRef.current.value = "";
            }
            setFileName("");

        } catch (err) {
            console.error("Upload error:", err);
            setLoading(false);
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
            pollJobStatus(job_id, text.substring(0, 30) + "...");

            // Clear input after successful submission
            setInputText("");

        } catch (err) {
            console.error("Analysis error:", err);
            setLoading(false);
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
                    {history.map((item) => (
                        <div
                            key={item.id}
                            className="history-item"
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

                    {/* Show loading spinner during analysis */}
                    {loading && (
                        <div className="loading-container">
                            <div className="loading-spinner"></div>
                            <p className="loading-text">
                                {progressMessage || "Processing..."}
                                <br />
                                <span className="loading-subtext">(This may take a few minutes)</span>
                            </p>
                        </div>
                    )}

                    {/* Results with Ask Expert button */}
                    {currentResult && currentResult.verdict && (
                        <>
                            <ResultsDisplay verdict={currentResult.verdict} />

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