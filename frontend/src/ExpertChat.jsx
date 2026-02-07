import { useState, useRef, useEffect } from 'react';
import { FaTimes, FaPaperPlane, FaRobot, FaUser, FaSpinner, FaBrain, FaLink } from 'react-icons/fa';
import './ExpertChat.css';

function ExpertChat({ isOpen, onClose, caseId, analysisData }) {
    const [messages, setMessages] = useState([]);
    const [inputText, setInputText] = useState('');
    const [loading, setLoading] = useState(false);
    const [sidebarWidth, setSidebarWidth] = useState(450);
    const [isResizing, setIsResizing] = useState(false);
    const messagesEndRef = useRef(null);
    const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages]);

    useEffect(() => {
        if (isOpen && messages.length === 0) {
            setMessages([{
                role: 'assistant',
                content: 'Hi! I\'m the Expert on this analysis. Ask me anything about the claims, evidence, or sources.'
            }]);
        }
    }, [isOpen]);

    const handleSendMessage = async () => {
        if (!inputText.trim() || loading || !caseId) return;

        const userMessage = inputText.trim();
        setInputText('');

        setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
        setLoading(true);

        try {
            const response = await fetch(`${API_URL}/api/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    case_id: caseId,
                    question: userMessage
                })
            });

            if (!response.ok) {
                throw new Error(`API error: ${response.status}`);
            }

            const data = await response.json();

            // Map citations to sources format for display
            const sources = (data.citations || []).map(cite => ({
                number: cite.number,
                url: cite.url,
                trust_score: cite.trust_score || 'Medium'
            }));

            setMessages(prev => [...prev, {
                role: 'assistant',
                content: data.answer,
                thoughtProcess: data.thought_process,
                sources: sources,
                trustBreakdown: data.trust_breakdown || {}
            }]);
        } catch (err) {
            console.error('Chat error:', err);
            setMessages(prev => [...prev, {
                role: 'assistant',
                content: `Sorry, I encountered an error: ${err.message}. Please try again.`
            }]);
        } finally {
            setLoading(false);
        }
    };

    const handleMouseDown = (e) => {
        setIsResizing(true);
        e.preventDefault();
    };

    useEffect(() => {
        const handleMouseMove = (e) => {
            if (!isResizing) return;

            const newWidth = window.innerWidth - e.clientX;
            // Constrain width between 350px and 80% of screen width
            const minWidth = 350;
            const maxWidth = window.innerWidth * 0.8;

            if (newWidth >= minWidth && newWidth <= maxWidth) {
                setSidebarWidth(newWidth);
            }
        };

        const handleMouseUp = () => {
            setIsResizing(false);
        };

        if (isResizing) {
            document.addEventListener('mousemove', handleMouseMove);
            document.addEventListener('mouseup', handleMouseUp);
        }

        return () => {
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
        };
    }, [isResizing]);

    if (!isOpen) return null;

    return (
        <div className="expert-chat-overlay" onClick={onClose}>
            <div
                className="expert-chat-sidebar"
                style={{ width: `${sidebarWidth}px` }}
                onClick={(e) => e.stopPropagation()}
            >
                <div
                    className="resize-handle"
                    onMouseDown={handleMouseDown}
                />
                <div className="expert-chat-header">
                    <div className="expert-chat-title">
                        <FaRobot className="expert-icon" />
                        <span>Ask the Expert</span>
                    </div>
                    <button className="expert-chat-close" onClick={onClose}>
                        <FaTimes />
                    </button>
                </div>

                <div className="expert-chat-subtitle">
                    Ask questions from the analysis above
                </div>

                <div className="expert-chat-messages">
                    {messages.map((msg, idx) => (
                        <div key={idx} className={`expert-message ${msg.role}`}>
                            <div className="message-icon">
                                {msg.role === 'user' ? <FaUser /> : <FaRobot />}
                            </div>
                            <div className="message-bubble">
                                {/* Thought Process removed from display - still maintained for context */}

                                {/* Main Answer */}
                                <div className="answer-content">
                                    {msg.content}
                                </div>

                                {/* Sources (if available) */}
                                {msg.sources && msg.sources.length > 0 && (
                                    <div className="sources-section">
                                        <div className="sources-header">
                                            <FaLink className="link-icon" />
                                            <span>Sources ({msg.sources.length})</span>
                                        </div>
                                        <div className="sources-list">
                                            {msg.sources.map((source, sidx) => (
                                                <a
                                                    key={sidx}
                                                    href={source.url}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    className={`source-item trust-${source.trust_score.toLowerCase()}`}
                                                >
                                                    <span className="citation-number">[{sidx + 1}]</span>
                                                    <span className="trust-badge">{source.trust_score}</span>
                                                    <span className="source-text">
                                                        {new URL(source.url).hostname}
                                                    </span>
                                                </a>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    ))}
                    {loading && (
                        <div className="expert-message assistant">
                            <div className="message-icon">
                                <FaRobot />
                            </div>
                            <div className="message-bubble">
                                <FaSpinner className="typing-spinner" />
                                <span style={{ marginLeft: '10px' }}>Thinking...</span>
                            </div>
                        </div>
                    )}
                    <div ref={messagesEndRef} />
                </div>

                <div className="expert-chat-input-container">
                    <input
                        type="text"
                        className="expert-chat-input"
                        placeholder={caseId ? "Ask a question..." : "No analysis loaded"}
                        value={inputText}
                        onChange={(e) => setInputText(e.target.value)}
                        onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
                        disabled={loading || !caseId}
                    />
                    <button
                        className="expert-send-btn"
                        onClick={handleSendMessage}
                        disabled={loading || !inputText.trim() || !caseId}
                    >
                        <FaPaperPlane />
                    </button>
                </div>
            </div>
        </div>
    );
}

export default ExpertChat;
