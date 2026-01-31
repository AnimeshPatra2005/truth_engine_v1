import React, { useState } from 'react';
import { FaCheckCircle, FaTimesCircle, FaExclamationCircle, FaInfoCircle, FaChevronDown, FaChevronUp, FaQuestionCircle, FaBook } from 'react-icons/fa';
import './ResultsDisplay.css';

// Helper to get domain from URL
const getDomain = (url) => {
    try {
        return new URL(url).hostname.replace('www.', '');
    } catch {
        return url;
    }
};

// Helper to get trust badge class
const getTrustClass = (trust) => {
    const t = trust?.toLowerCase() || '';
    if (t === 'high') return 'trust-high';
    if (t === 'medium') return 'trust-medium';
    if (t === 'low') return 'trust-low';
    return 'trust-unknown';
};

// Evidence Section Component with citations and sources toggle
function EvidenceSection({ prosecutorEvidence, defenderEvidence }) {
    const [showSources, setShowSources] = useState(false);

    // Build combined sources list with indices
    const allSources = [];

    const renderEvidence = (facts, isContradicting) => {
        if (!facts || facts.length === 0) return null;

        return (
            <div className={`evidence-group ${isContradicting ? 'contradicting' : 'supporting'}`}>
                <div className="evidence-group-title">
                    {isContradicting ? <FaTimesCircle /> : <FaCheckCircle />}
                    {isContradicting ? ' Contradicting Evidence' : ' Supporting Evidence'}
                </div>
                {facts.map((fact, idx) => {
                    // Add to sources list and get index
                    const sourceIndex = allSources.length + 1;
                    allSources.push({
                        index: sourceIndex,
                        url: fact.source_url,
                        domain: getDomain(fact.source_url),
                        trust: fact.trust_score
                    });

                    return (
                        <div key={idx} className="evidence-item">
                            <div className="evidence-fact">
                                {fact.key_fact}
                                <a
                                    href={fact.source_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="citation-link"
                                    title={`Source: ${getDomain(fact.source_url)}`}
                                >
                                    [{sourceIndex}]
                                </a>
                                <span className={`trust-badge ${getTrustClass(fact.trust_score)}`}>
                                    {fact.trust_score || 'Unknown'}
                                </span>
                            </div>
                        </div>
                    );
                })}
            </div>
        );
    };

    // Render both sides (this populates allSources)
    const contradictingContent = renderEvidence(prosecutorEvidence, true);
    const supportingContent = renderEvidence(defenderEvidence, false);

    return (
        <div className="evidence-section">
            {contradictingContent}
            {supportingContent}

            {/* Sources Toggle */}
            {allSources.length > 0 && (
                <div className="sources-toggle-container">
                    <button
                        className="sources-toggle-btn"
                        onClick={() => setShowSources(!showSources)}
                    >
                        <FaBook /> Sources
                        {showSources ? <FaChevronUp /> : <FaChevronDown />}
                    </button>

                    {showSources && (
                        <div className="sources-list">
                            {allSources.map((src) => (
                                <div key={src.index} className="source-item">
                                    <span className="source-index">[{src.index}]</span>
                                    <a
                                        href={src.url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="source-link"
                                    >
                                        {src.domain}
                                    </a>
                                    <span className={`trust-badge-small ${getTrustClass(src.trust)}`}>
                                        {src.trust}
                                    </span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

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
                                {(claim.prosecutor_evidence?.length > 0 || claim.defender_evidence?.length > 0) && (
                                    <EvidenceSection
                                        prosecutorEvidence={claim.prosecutor_evidence}
                                        defenderEvidence={claim.defender_evidence}
                                    />
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
