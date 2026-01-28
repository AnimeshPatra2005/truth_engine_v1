import React, { useState } from 'react';
import { FaCheckCircle, FaTimesCircle, FaExclamationCircle, FaInfoCircle, FaChevronDown, FaChevronUp, FaQuestionCircle } from 'react-icons/fa';
import './ResultsDisplay.css';

function ResultsDisplay({ verdict }) {
    const [showClaimAnalysis, setShowClaimAnalysis] = useState(false);

    // Function to get verdict color and icon
    const getVerdictStyle = (status) => {
        const statusLower = status?.toLowerCase() || '';

        // Check for True/Verified (green checkmark)
        if ((statusLower.includes('true') && !statusLower.includes('partially')) || (statusLower.includes('verified') && !statusLower.includes('unverified'))) {
            return { color: '#10b981', icon: <FaCheckCircle />, label: 'VERIFIED' };
        }
        // Check for False/Debunked (red cross)
        else if (statusLower.includes('false') || statusLower.includes('debunked')) {
            return { color: '#ef4444', icon: <FaTimesCircle />, label: 'FALSE' };
        }
        // Check for Unverified (yellow question mark)
        else if (statusLower.includes('unverified')) {
            return { color: '#eab308', icon: <FaQuestionCircle />, label: 'UNVERIFIED' };
        }
        // Check for Partially True (orange exclamation)
        else if (statusLower.includes('partially')) {
            return { color: '#f97316', icon: <FaExclamationCircle />, label: 'PARTIALLY TRUE' };
        }
        // Check for Unclear (orange exclamation)
        else if (statusLower.includes('unclear')) {
            return { color: '#f97316', icon: <FaExclamationCircle />, label: 'UNCLEAR' };
        }
        // Default fallback
        return { color: '#6b7280', icon: <FaInfoCircle />, label: 'UNKNOWN' };
    };

    const overallStyle = getVerdictStyle(verdict.overall_verdict);

    return (
        <div className="chatbot-results">
            {/* Overall Verdict Message */}
            <div className="result-message">
                <div className="verdict-card" style={{ borderLeftColor: overallStyle.color }}>
                    <div className="verdict-icon" style={{ color: overallStyle.color }}>
                        {overallStyle.icon}
                    </div>
                    <div className="verdict-content">
                        <div className="verdict-label">OVERALL VERDICT</div>
                        <div className="verdict-text" style={{ color: overallStyle.color }}>
                            {verdict.overall_verdict}
                        </div>
                    </div>
                </div>

                {/* Implication Analysis */}
                {verdict.implication_connection && (
                    <div className="implication-card">
                        <div className="implication-header">Analysis</div>
                        <p className="implication-text">{verdict.implication_connection}</p>
                    </div>
                )}

                {/* Claim-wise Verification Button */}
                <div className="claim-wise-toggle">
                    <button
                        className="toggle-button"
                        onClick={() => setShowClaimAnalysis(!showClaimAnalysis)}
                    >
                        <span>Claim wise verification</span>
                        {showClaimAnalysis ? <FaChevronUp /> : <FaChevronDown />}
                    </button>
                </div>
            </div>

            {/* Claim-wise Analysis (Expandable) */}
            {showClaimAnalysis && verdict.claim_analyses && (
                <div className="claims-container">
                    {verdict.claim_analyses.map((claim, index) => {
                        const claimStyle = getVerdictStyle(claim.status);

                        return (
                            <div key={claim.claim_id || index} className="claim-box" style={{ borderLeftColor: claimStyle.color }}>
                                <div className="claim-header">
                                    <div className="claim-badge" style={{ backgroundColor: claimStyle.color }}>
                                        {claimStyle.icon}
                                        <span>{claimStyle.label}</span>
                                    </div>
                                </div>

                                <div className="claim-text">{claim.claim_text}</div>

                                {claim.detailed_paragraph && (
                                    <div className="claim-analysis">
                                        <p>{claim.detailed_paragraph}</p>
                                    </div>
                                )}

                                {/* Evidence Section */}
                                {(claim.prosecutor_facts?.length > 0 || claim.defender_facts?.length > 0) && (
                                    <div className="evidence-section">
                                        {/* Prosecutor Evidence */}
                                        {claim.prosecutor_facts?.length > 0 && (
                                            <div className="evidence-group prosecutor">
                                                <div className="evidence-group-title">
                                                    <FaTimesCircle /> Contradicting Evidence
                                                </div>
                                                {claim.prosecutor_facts.map((fact, idx) => (
                                                    <div key={idx} className="evidence-item">
                                                        <div className="evidence-meta">
                                                            <span className={`trust-badge trust-${fact.trust_score?.toLowerCase()}`}>
                                                                {fact.trust_score || 'Unknown'}
                                                            </span>
                                                            <span className="verification-tag">
                                                                {fact.verification_method?.replace('Tier', 'T')}
                                                            </span>
                                                        </div>
                                                        <div className="evidence-fact">{fact.key_fact}</div>
                                                        {fact.source_url && (
                                                            <a
                                                                href={fact.source_url}
                                                                target="_blank"
                                                                rel="noopener noreferrer"
                                                                className="evidence-source"
                                                            >
                                                                View Source →
                                                            </a>
                                                        )}
                                                        {fact.verification_details && (
                                                            <div className="verification-info">
                                                                {fact.verification_details}
                                                            </div>
                                                        )}
                                                    </div>
                                                ))}
                                            </div>
                                        )}

                                        {/* Defender Evidence */}
                                        {claim.defender_facts?.length > 0 && (
                                            <div className="evidence-group defender">
                                                <div className="evidence-group-title">
                                                    <FaCheckCircle /> Supporting Evidence
                                                </div>
                                                {claim.defender_facts.map((fact, idx) => (
                                                    <div key={idx} className="evidence-item">
                                                        <div className="evidence-meta">
                                                            <span className={`trust-badge trust-${fact.trust_score?.toLowerCase()}`}>
                                                                {fact.trust_score || 'Unknown'}
                                                            </span>
                                                            <span className="verification-tag">
                                                                {fact.verification_method?.replace('Tier', 'T')}
                                                            </span>
                                                        </div>
                                                        <div className="evidence-fact">{fact.key_fact}</div>
                                                        {fact.source_url && (
                                                            <a
                                                                href={fact.source_url}
                                                                target="_blank"
                                                                rel="noopener noreferrer"
                                                                className="evidence-source"
                                                            >
                                                                View Source →
                                                            </a>
                                                        )}
                                                        {fact.verification_details && (
                                                            <div className="verification-info">
                                                                {fact.verification_details}
                                                            </div>
                                                        )}
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

export default ResultsDisplay;
