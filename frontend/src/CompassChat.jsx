import { useState, useRef, useEffect } from 'react';
import { FaPaperPlane, FaRobot, FaUser, FaSpinner, FaLink, FaExclamationTriangle, FaShieldAlt, FaCheckCircle } from 'react-icons/fa';
import './CompassChat.css';

function CompassChat({ onFirstAnalysis, onAddHistory }) {
    const [messages, setMessages] = useState([]);
    const [inputText, setInputText] = useState('');
    const [loading, setLoading] = useState(false);
    const [sessionId, setSessionId] = useState(null);
    const [hasAnalyzed, setHasAnalyzed] = useState(false);
    const messagesEndRef = useRef(null);
    const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages]);

    const handleSend = async () => {
        if (!inputText.trim() || loading) return;

        const userMessage = inputText.trim();
        setInputText('');
        setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
        setLoading(true);

        try {
            if (!hasAnalyzed) {
                // First message — full analysis
                const response = await fetch(`${API_URL}/api/compass/analyze`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: userMessage }),
                });

                if (!response.ok) {
                    const errData = await response.json().catch(() => ({}));
                    throw new Error(errData.detail || `Analysis failed (${response.status})`);
                }

                const data = await response.json();
                setSessionId(data.session_id);
                setHasAnalyzed(true);

                const title = userMessage.substring(0, 35) + (userMessage.length > 35 ? '...' : '');
                if (onAddHistory) onAddHistory(title, data.session_id);

                setMessages(prev => [...prev, {
                    role: 'assistant',
                    type: 'analysis',
                    content: data.response,
                    overall_risk: data.overall_risk,
                    risk_parameters: data.risk_parameters,
                    citations: data.citations,
                    actionable_steps: data.actionable_steps,
                    demands: data.demands,
                }]);

                if (onFirstAnalysis) onFirstAnalysis();
            } else {
                // Follow-up message
                const response = await fetch(`${API_URL}/api/compass/chat`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        session_id: sessionId,
                        message: userMessage,
                    }),
                });

                if (!response.ok) {
                    const errData = await response.json().catch(() => ({}));
                    throw new Error(errData.detail || `Chat failed (${response.status})`);
                }

                const data = await response.json();

                setMessages(prev => [...prev, {
                    role: 'assistant',
                    type: 'followup',
                    content: data.response,
                    citations: data.citations || [],
                }]);
            }
        } catch (err) {
            console.error('Compass error:', err);
            setMessages(prev => [...prev, {
                role: 'assistant',
                type: 'error',
                content: `Sorry, I encountered an error: ${err.message}. Please try again.`,
            }]);
        } finally {
            setLoading(false);
        }
    };

    const getRiskIcon = (level) => {
        switch (level?.toUpperCase()) {
            case 'HIGH': return <FaExclamationTriangle />;
            case 'MEDIUM': return <FaShieldAlt />;
            case 'LOW': return <FaCheckCircle />;
            default: return <FaShieldAlt />;
        }
    };

    const getRiskClass = (level) => {
        switch (level?.toUpperCase()) {
            case 'HIGH': return 'risk-high';
            case 'MEDIUM': return 'risk-medium';
            case 'LOW': return 'risk-low';
            default: return 'risk-medium';
        }
    };

    const renderAnalysisMessage = (msg) => {
        return (
            <div className="compass-analysis-card">
                {/* Risk Header */}
                <div className={`risk-header ${getRiskClass(msg.overall_risk)}`}>
                    <div className="risk-badge">
                        {getRiskIcon(msg.overall_risk)}
                        <span>{msg.overall_risk} RISK</span>
                    </div>
                    <span className="risk-subtitle">Regulatory Compass Assessment</span>
                </div>

                {/* Risk Parameters */}
                {msg.risk_parameters && Object.keys(msg.risk_parameters).length > 0 && (
                    <div className="risk-parameters">
                        <h4 className="section-label">Risk Breakdown</h4>
                        <div className="param-grid">
                            {Object.entries(msg.risk_parameters).map(([name, data]) => (
                                <div key={name} className={`param-item ${getRiskClass(data.level)}`}>
                                    <div className="param-header">
                                        <span className="param-name">{name}</span>
                                        <span className={`param-level ${getRiskClass(data.level)}`}>
                                            {data.level}
                                        </span>
                                    </div>
                                    {data.reason && (
                                        <span className="param-reason">{data.reason}</span>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Demands Found */}
                {msg.demands && msg.demands.length > 0 && (
                    <div className="demands-section">
                        <h4 className="section-label">Demands Detected ({msg.demands.length})</h4>
                        {msg.demands.map((demand, idx) => (
                            <div key={idx} className={`demand-card ${demand.matched_rule ? 'matched' : 'unmatched'}`}>
                                <div className="demand-header">
                                    <span className="demand-number">#{idx + 1}</span>
                                    <span className="demand-ask">{demand.ask}</span>
                                </div>
                                <div className="demand-meta">
                                    {demand.entity_claimed && (
                                        <span className="demand-tag entity">{demand.entity_claimed}</span>
                                    )}
                                    {demand.urgency_level && (
                                        <span className={`demand-tag urgency-${demand.urgency_level}`}>
                                            {demand.urgency_level} urgency
                                        </span>
                                    )}
                                    {demand.amount_mentioned && (
                                        <span className="demand-tag amount">{demand.amount_mentioned}</span>
                                    )}
                                </div>
                                {demand.matched_rule && (
                                    <div className="rule-match">
                                        <FaShieldAlt className="rule-icon" />
                                        <span className="rule-text">
                                            <strong>Rule Violation:</strong> {demand.matched_rule.rule}
                                        </span>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}


                {/* Actionable Steps */}
                {msg.actionable_steps && msg.actionable_steps.length > 0 && (
                    <div className="steps-section">
                        <h4 className="section-label">What To Do Now</h4>
                        <ol className="steps-list">
                            {msg.actionable_steps.map((step, idx) => (
                                <li key={idx}>{step}</li>
                            ))}
                        </ol>
                    </div>
                )}

                {/* Citations */}
                {msg.citations && msg.citations.length > 0 && (
                    <div className="compass-citations">
                        <h4 className="section-label">
                            <FaLink className="link-icon" /> Sources ({msg.citations.length})
                        </h4>
                        <div className="citation-list">
                            {msg.citations.map((cite, idx) => (
                                <a
                                    key={idx}
                                    href={cite.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="citation-item"
                                >
                                    <span className="citation-number">[{idx + 1}]</span>
                                    <span className="citation-label">{cite.label}</span>
                                </a>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        );
    };

    const renderFollowupMessage = (msg) => {
        return (
            <div className="followup-content">
                <div className="response-text">{msg.content}</div>
                {msg.citations && msg.citations.length > 0 && (
                    <div className="compass-citations compact">
                        <div className="citation-list">
                            {msg.citations.map((cite, idx) => (
                                <a
                                    key={idx}
                                    href={cite.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="citation-item"
                                >
                                    <span className="citation-number">[{idx + 1}]</span>
                                    <span className="citation-label">{cite.label}</span>
                                </a>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        );
    };

    return (
        <div className="compass-chat-wrapper">
            {/* Messages Area */}
            <div className="compass-messages">
                {messages.length === 0 && (
                    <div className="compass-welcome">
                        <h2>Regulatory Compass</h2>
                        <p>Paste a suspicious email, WhatsApp message, or SMS to check if it violates known regulatory rules.</p>
                        <div className="compass-suggestions">
                            <button onClick={() => setInputText("I received an email from SEBI asking me to pay ₹25,000 as Securities Transaction Tax to release my blocked funds. The email has SEBI's letterhead and logo.")}
                                className="compass-suggestion-pill">
                                Check a SEBI notice
                            </button>
                            <button onClick={() => setInputText("My boss sent me a WhatsApp message asking me to urgently transfer ₹2,00,000 to a vendor account. He said it's confidential and not to tell anyone.")}
                                className="compass-suggestion-pill">
                                Verify a boss's request
                            </button>
                            <button onClick={() => setInputText("Someone added me to a WhatsApp group called 'SEBI Certified Stock Tips' promising 200% returns in 30 days.")}
                                className="compass-suggestion-pill">
                                Analyze a WhatsApp group invite
                            </button>
                        </div>
                    </div>
                )}

                {messages.map((msg, idx) => (
                    <div key={idx} className={`compass-message ${msg.role}`}>
                        <div className="compass-message-icon">
                            {msg.role === 'user' ? <FaUser /> : <FaRobot />}
                        </div>
                        <div className="compass-message-bubble">
                            {msg.type === 'analysis' ? renderAnalysisMessage(msg) :
                             msg.type === 'followup' ? renderFollowupMessage(msg) :
                             msg.type === 'error' ? (
                                <div className="error-content">{msg.content}</div>
                             ) : (
                                <div className="user-text">{msg.content}</div>
                             )}
                        </div>
                    </div>
                ))}

                {loading && (
                    <div className="compass-message assistant">
                        <div className="compass-message-icon"><FaRobot /></div>
                        <div className="compass-message-bubble">
                            <div className="compass-loading">
                                <FaSpinner className="compass-spinner" />
                                <span>{hasAnalyzed ? "Thinking..." : "Analyzing message against regulatory rules..."}</span>
                            </div>
                        </div>
                    </div>
                )}

                <div ref={messagesEndRef} />
            </div>

            {/* Input Bar */}
            <div className="compass-input-container">
                <div className="compass-input-bar">
                    <textarea
                        className="compass-text-input"
                        placeholder={hasAnalyzed
                            ? "Ask a follow-up question..."
                            : "Paste a suspicious email, WhatsApp message, or SMS here..."
                        }
                        value={inputText}
                        onChange={(e) => setInputText(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault();
                                handleSend();
                            }
                        }}
                        rows={1}
                    />
                    <button
                        className="send-btn"
                        onClick={handleSend}
                        disabled={loading || !inputText.trim()}
                    >
                        <FaPaperPlane />
                    </button>
                </div>
                <p className="compass-disclaimer">
                    Regulatory Compass checks messages against known SEBI, RBI, NSE, and BSE guidelines. Always verify independently.
                </p>
            </div>
        </div>
    );
}

export default CompassChat;
