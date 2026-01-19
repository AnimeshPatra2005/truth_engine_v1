import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { FaPlus, FaHistory, FaFileUpload, FaPaperPlane, FaRobot, FaHome } from 'react-icons/fa';
import './TryPage.css';

function TryPage() {
    // State for managing the page
    const [history, setHistory] = useState([]);
    const [currentResult, setCurrentResult] = useState(null);
    const [loading, setLoading] = useState(false);
    const [inputText, setInputText] = useState("");
    const [fileName, setFileName] = useState("");
    const fileInputRef = useRef(null);

    // Load saved history when page loads
    useEffect(() => {
        // Clear old history for fresh start (remove this line later if you want to keep history)
        localStorage.removeItem('truth_history');
        const savedHistory = JSON.parse(localStorage.getItem('truth_history') || '[]');
        setHistory(savedHistory);
    }, []);

    // Clear everything and start fresh
    const startNewChat = () => {
        setCurrentResult(null);
        setInputText("");
        setFileName("");
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

    // Handle video file upload
    const processFileUpload = async (file) => {
        setLoading(true);
        setCurrentResult(null);

        const formData = new FormData();
        formData.append("file", file);

        try {
            const response = await axios.post(
                "http://localhost:8000/api/upload-video",
                formData,
                { headers: { "Content-Type": "multipart/form-data" } }
            );

            const resultData = response.data;

            // Save to history
            const newHistoryItem = {
                id: Date.now(),
                title: file.name,
                data: resultData
            };

            const updatedHistory = [newHistoryItem, ...history];
            setHistory(updatedHistory);
            localStorage.setItem('truth_history', JSON.stringify(updatedHistory));

            setCurrentResult(resultData);
        } catch (err) {
            console.error(err);
            alert("Analysis failed. Check backend connection.");
        } finally {
            setLoading(false);
            setFileName("");
            fileInputRef.current.value = "";
        }
    };

    // Handle text-only analysis
    const processTextAnalysis = async (text) => {
        setLoading(true);
        setCurrentResult(null);

        try {
            const response = await axios.post(
                "http://localhost:8000/api/analyze-text",
                { text: text }
            );

            const resultData = response.data;

            // Save to history
            const newHistoryItem = {
                id: Date.now(),
                title: text.substring(0, 50) + (text.length > 50 ? "..." : ""),
                data: resultData
            };

            const updatedHistory = [newHistoryItem, ...history];
            setHistory(updatedHistory);
            localStorage.setItem('truth_history', JSON.stringify(updatedHistory));

            setCurrentResult(resultData);
        } catch (err) {
            console.error(err);
            alert("Analysis failed. Check backend connection.");
        } finally {
            setLoading(false);
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
                                {fileName ? 'Transcribing video & ' : ''}Verification in progress...
                                <br />
                                <span className="loading-subtext">(This may take 1-2 minutes)</span>
                            </p>
                        </div>
                    )}

                    {/* Results will go here */}
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