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

function ResultsDisplay({ verdict, visualAnalysis }) {
    const [showClaimAnalysis, setShowClaimAnalysis] = useState(false);
    const [showVisualAnalysis, setShowVisualAnalysis] = useState(false);

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

                {/* Toggle Buttons Row - Side by Side */}
                <div style={{ display: 'flex', gap: '10px', justifyContent: 'space-between', marginTop: '1rem' }}>
                    {/* Claim-wise Verification Button */}
                    <button
                        className="toggle-button"
                        onClick={() => setShowClaimAnalysis(!showClaimAnalysis)}
                        style={{ minWidth: '200px', justifyContent: 'center' }}
                    >
                        <span>Claim wise verification</span>
                        {showClaimAnalysis ? <FaChevronUp /> : <FaChevronDown />}
                    </button>

                    {/* Visual Analysis Button - Only shown for video analyses */}
                    {visualAnalysis && (
                        <button
                            className="toggle-button"
                            onClick={() => setShowVisualAnalysis(!showVisualAnalysis)}
                            style={{ minWidth: '200px', justifyContent: 'center' }}
                        >
                            <span>Visual Analysis</span>
                            {showVisualAnalysis ? <FaChevronUp /> : <FaChevronDown />}
                        </button>
                    )}
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

            {/* Visual Analysis (Expandable) */}
            {showVisualAnalysis && visualAnalysis && (
                <div style={{
                    background: 'rgba(30,30,40,0.9)',
                    padding: '1rem',
                    borderRadius: '8px',
                    marginTop: '1rem'
                }}>
                    <p style={{ color: '#a0a0a0', marginBottom: '1rem' }}>
                        {visualAnalysis.summary}
                    </p>

                    {visualAnalysis.visual_elements?.map((visual, index) => (
                        <div key={index} style={{
                            padding: '0.75rem',
                            marginBottom: '0.5rem',
                            background: 'rgba(50,50,60,0.5)',
                            borderRadius: '6px',
                            borderLeft: `3px solid ${visual.status === 'matches' ? '#10b981' : visual.status === 'contradicts' ? '#ef4444' : '#f59e0b'}`
                        }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                                <span style={{ color: '#888', fontSize: '0.85rem' }}>{visual.timestamp}</span>
                                <span style={{
                                    padding: '2px 8px',
                                    borderRadius: '4px',
                                    fontSize: '0.75rem',
                                    fontWeight: 'bold',
                                    background: visual.status === 'matches' ? 'rgba(16,185,129,0.2)' : visual.status === 'contradicts' ? 'rgba(239,68,68,0.2)' : 'rgba(245,158,11,0.2)',
                                    color: visual.status === 'matches' ? '#10b981' : visual.status === 'contradicts' ? '#ef4444' : '#f59e0b'
                                }}>{visual.status?.toUpperCase()}</span>
                            </div>
                            <p style={{ color: '#e0e0e0', margin: 0 }}>{visual.description}</p>
                            {visual.concern && visual.concern !== 'null' && (
                                <p style={{ color: '#ef4444', fontSize: '0.85rem', marginTop: '0.5rem', fontStyle: 'italic' }}>⚠️ {visual.concern}</p>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

export default ResultsDisplay;
