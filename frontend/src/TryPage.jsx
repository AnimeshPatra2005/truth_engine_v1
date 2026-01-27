import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { FaPlus, FaHistory, FaFileUpload, FaPaperPlane, FaRobot, FaHome } from 'react-icons/fa';
import './TryPage.css';
import ResultsDisplay from './ResultsDisplay';

function TryPage() {
    // API URL from environment variable (or fallback to localhost)
    const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

    // State for managing the page
    const [history, setHistory] = useState([]);
    const [currentResult, setCurrentResult] = useState(null);
    const [loading, setLoading] = useState(false);
    const [progressMessage, setProgressMessage] = useState(""); // New: Dynamic progress
    const [inputText, setInputText] = useState("");
    const [fileName, setFileName] = useState("");
    const fileInputRef = useRef(null);
    const pollingRef = useRef(null); // To cleanup polling on unmount

    // Load saved history when page loads
    useEffect(() => {
        // Clear old history for fresh start (remove this line later if you want to keep history)
        // localStorage.removeItem('truth_history'); 
        const savedHistory = JSON.parse(localStorage.getItem('truth_history') || '[]');
        setHistory(savedHistory);

        return () => {
            // Cleanup polling on unmount
            if (pollingRef.current) clearTimeout(pollingRef.current);
        };
    }, []);

    // Clear everything and start fresh
    const startNewChat = () => {
        setCurrentResult(null);
        setInputText("");
        setFileName("");
        setProgressMessage("");
        if (pollingRef.current) clearTimeout(pollingRef.current);
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

                // Save to history
                const newHistoryItem = {
                    id: Date.now(),
                    title: titleForHistory,
                    data: resultData
                };

                const updatedHistory = [newHistoryItem, ...history];
                setHistory(updatedHistory);
                localStorage.setItem('truth_history', JSON.stringify(updatedHistory));

                setCurrentResult(resultData);

            } else if (statusData.status === 'error') {
                setLoading(false);
                alert(`Analysis failed: ${statusData.error}`);
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
        setLoading(true);
        setCurrentResult(null);
        setProgressMessage("Uploading video...");

        const formData = new FormData();
        formData.append("file", file);

        try {
            const response = await axios.post(
                `${API_URL}/api/upload-video`,
                formData,
                { headers: { "Content-Type": "multipart/form-data" } }
            );

            // Start polling with job_id
            const { job_id } = response.data;
            setProgressMessage("Queued for analysis...");
            pollJobStatus(job_id, file.name);

        } catch (err) {
            console.error(err);
            setLoading(false);
            alert("Upload failed. Check backend connection.");
        }
    };

    // Handle text-only analysis
    const processTextAnalysis = async (text) => {
        setLoading(true);
        setCurrentResult(null);
        setProgressMessage("Sending request...");

        try {
            const response = await axios.post(
                `${API_URL}/api/analyze-text`,
                { text: text }
            );

            // Start polling with job_id
            const { job_id } = response.data;
            setProgressMessage("Queued for analysis...");
            pollJobStatus(job_id, text.substring(0, 30) + "...");

        } catch (err) {
            console.error(err);
            setLoading(false);
            alert("Request failed. Check backend connection.");
        } finally {
            setInputText("");
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
                            <FaHistory /> {item.title}
                        </div>
                    ))}
                </div>
            </aside>

            {/* Main content area */}
            <main className="main-content">
                <div className="chat-scroll-area">
                    {/* Show welcome screen when idle */}
                    {!currentResult && !loading && (
                        <div className="welcome-screen">
                            <h1>Truth Engine</h1>
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

                    {currentResult && currentResult.verdict && <ResultsDisplay verdict={currentResult.verdict} />}
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
        </div>
    );
}

export default TryPage;