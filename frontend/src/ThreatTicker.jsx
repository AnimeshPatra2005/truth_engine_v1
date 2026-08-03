import { useEffect, useRef, useState } from 'react';
import './ThreatTicker.css';

// Scam intelligence data — generated from SEBI/RBI/NSE advisories
// Remove the two weak-source entries (scantotal.net, righttoinformation.wiki)
const THREAT_DATA = [
  {
    id: "sebi-boss-scam",
    title: "Boss Scam — CEO Impersonation",
    description: "Fraudsters impersonate CEOs on messaging platforms to trick employees into urgent fund transfers.",
    source_label: "SEBI",
    source_url: "https://www.sebi.gov.in/media-and-notifications/press-releases/jul-2026/caution-to-regulated-entities-and-listed-companies-boss-scam_102919.html",
    date: "2026-07",
    severity: "high",
    category: "impersonation",
  },
  {
    id: "bse-ceo-deepfake",
    title: "BSE CEO Deepfake Video",
    description: "AI-generated video of BSE CEO providing fake stock recommendations circulated on social media.",
    source_label: "BSE",
    source_url: "https://www.thehindu.com/business/bse-cautions-investors-against-deepfake-video-of-its-ceo-recommending-stocks/article70501075.ece",
    date: "2026-01",
    severity: "high",
    category: "deepfake",
  },
  {
    id: "nse-fake-stt-notice",
    title: "Forged SEBI Letterhead — STT Payment Demand",
    description: "Fraudsters use forged SEBI letterheads to demand Securities Transaction Tax payments to release funds.",
    source_label: "NSE",
    source_url: "https://www.angelone.in/news/personal-finance/nse-issues-public-warning-on-fake-sebi-stt-notices-urges-investors-to-stay-alert",
    date: "2026-02",
    severity: "high",
    category: "regulatory_fraud",
  },
  {
    id: "sebi-deepfake-guaranteed-returns",
    title: "AI Deepfakes Promoting Guaranteed Return Schemes",
    description: "AI-generated videos of market experts and public figures endorse fraudulent guaranteed-return investment schemes.",
    source_label: "SEBI",
    source_url: "https://www.nyvo.money/resources/newsletter/how-to-spot-investment-scam",
    date: "2025-05",
    severity: "high",
    category: "deepfake",
  },
  {
    id: "sbi-account-lock-phishing",
    title: "Fake Account Lock Phishing SMS",
    description: "Phishing messages claim bank accounts are locked, directing users to malicious links to harvest credentials.",
    source_label: "SBI",
    source_url: "https://sbi.bank.in/web/yono/phishing-attacks-how-to-spot-scams-and-protect-yourself",
    date: "2026",
    severity: "high",
    category: "phishing",
  },
  {
    id: "rbi-fictitious-lottery",
    title: "RBI Name Used in Fictitious Lottery Scams",
    description: "Fraudsters send fake offers using RBI logos and letterheads to solicit processing fees from victims.",
    source_label: "RBI",
    source_url: "https://www.rbi.org.in/commonman/English/Scripts/PressReleases.aspx?Id=2440",
    date: "2026",
    severity: "medium",
    category: "impersonation",
  },
  {
    id: "sebi-pump-dump-whatsapp",
    title: "WhatsApp Pump-and-Dump Stock Groups",
    description: "Scammers hype low-quality stocks in WhatsApp/Telegram groups before dumping shares on retail investors.",
    source_label: "SEBI",
    source_url: "https://www.indiratrade.com/blog/sebi-cracks-down-on-pumpanddump-scams-protecting-investors-in-2025/9564",
    date: "2025",
    severity: "medium",
    category: "pump_and_dump",
  },
  {
    id: "whatsapp-fake-fund-house",
    title: "Fake Fund House Groups on WhatsApp",
    description: "Scammers create WhatsApp groups impersonating well-known fund houses to sell fake stock tips and courses.",
    source_label: "Times of India",
    source_url: "https://timesofindia.indiatimes.com/business/financial-literacy/investing/how-whatsapp-investing-scams-operate-beware-of-these-red-flags-to-avoid-losing-money/articleshow/109168659.cms",
    date: "2026",
    severity: "medium",
    category: "social_engineering",
  },
  {
    id: "sebi-wealthmax-fake-advisor",
    title: "Unregistered Advisors Offering Guaranteed Returns",
    description: "Unregistered firms lure retail investors with promises of exclusive stock tips and guaranteed high returns.",
    source_label: "SEBI",
    source_url: "https://gocredit.money/news/sebi-bans-fake-advisor-are-you-safe-20260409",
    date: "2026-04",
    severity: "medium",
    category: "social_engineering",
  },
];

const SEVERITY_CONFIG = {
  high: { color: '#ff3b3b', label: '◆' },
  medium: { color: '#f5a623', label: '◆' },
  low: { color: '#4cd964', label: '◆' },
};

const CATEGORY_LABELS = {
  deepfake: 'DEEPFAKE',
  phishing: 'PHISHING',
  impersonation: 'IMPERSONATION',
  pump_and_dump: 'PUMP & DUMP',
  fake_platform: 'FAKE PLATFORM',
  voice_cloning: 'VOICE CLONE',
  social_engineering: 'SOCIAL ENG.',
  regulatory_fraud: 'REG. FRAUD',
};

export default function ThreatTicker() {
  const trackRef = useRef(null);
  const [isPaused, setIsPaused] = useState(false);

  // Duplicate items for seamless loop
  const items = [...THREAT_DATA, ...THREAT_DATA];

  return (
    <div className="threat-ticker">
      {/* Left anchor label — fixed, doesn't scroll */}
      <div className="ticker-label">
        <span className="ticker-pulse-dot" />
        <span className="ticker-label-text">LIVE THREATS</span>
      </div>

      {/* Divider */}
      <div className="ticker-divider" />

      {/* Scrolling track */}
      <div
        className="ticker-overflow"
        onMouseEnter={() => setIsPaused(true)}
        onMouseLeave={() => setIsPaused(false)}
      >
        <div
          ref={trackRef}
          className={`ticker-track ${isPaused ? 'paused' : ''}`}
        >
          {items.map((item, idx) => {
            const sev = SEVERITY_CONFIG[item.severity] || SEVERITY_CONFIG.medium;
            const cat = CATEGORY_LABELS[item.category] || item.category.toUpperCase();
            return (
              <a
                key={`${item.id}-${idx}`}
                href={item.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="ticker-item"
                title={item.description}
              >
                <span className="ticker-severity" style={{ color: sev.color }}>
                  {sev.label}
                </span>
                <span className="ticker-category">[{cat}]</span>
                <span className="ticker-title">{item.title}</span>
                <span className="ticker-source">— {item.source_label}</span>
                <span className="ticker-sep">·</span>
              </a>
            );
          })}
        </div>
      </div>
    </div>
  );
}
