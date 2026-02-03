import { useState, useRef, useEffect } from 'react';
import { FaTimes, FaPaperPlane, FaRobot, FaUser, FaSpinner } from 'react-icons/fa';
import './ExpertChat.css';

function ExpertChat({ isOpen, onClose, caseId, analysisData }) {
    const [messages, setMessages] = useState([]);
    const [inputText, setInputText] = useState('');
    const [loading, setLoading] = useState(false);
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
        if (!inputText.trim() || loading) return;

        const userMessage = inputText.trim();
        setInputText('');

        setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
        setLoading(true);

        try {
            setTimeout(() => {
                setMessages(prev => [...prev, {
                    role: 'assistant',
                    content: 'The Expert Chat backend is still being built. This is a placeholder response.'
                }]);
                setLoading(false);
            }, 1000);
        } catch (err) {
            console.error('Chat error:', err);
            setMessages(prev => [...prev, {
                role: 'assistant',
                content: 'Sorry, I encountered an error. Please try again.'
            }]);
            setLoading(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="expert-chat-overlay" onClick={onClose}>
            <div className="expert-chat-sidebar" onClick={(e) => e.stopPropagation()}>
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
                                {msg.content}
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
                            </div>
                        </div>
                    )}
                    <div ref={messagesEndRef} />
                </div>

                <div className="expert-chat-input-container">
                    <input
                        type="text"
                        className="expert-chat-input"
                        placeholder="Ask a question..."
                        value={inputText}
                        onChange={(e) => setInputText(e.target.value)}
                        onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
                        disabled={loading}
                    />
                    <button
                        className="expert-send-btn"
                        onClick={handleSendMessage}
                        disabled={loading || !inputText.trim()}
                    >
                        <FaPaperPlane />
                    </button>
                </div>
            </div>
        </div>
    );
}

export default ExpertChat;
