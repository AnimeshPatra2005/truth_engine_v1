"""
Configuration constants and domain trust catalog for the Courtroom Engine.
Contains trusted domains for fact-checking and domain trust scoring functions.
"""
from typing import List, Literal
from urllib.parse import urlparse


# ==============================================================================
# TRUSTED DOMAINS CATALOG
# ==============================================================================

TRUSTED_DOMAINS = {
    "government": [
        # India Government
        "gov.in", "nic.in", "indiankanoon.org", "supremecourtofindia.nic.in",
        "mea.gov.in", "pib.gov.in", "asi.nic.in", "nationalarchives.gov.in",
        "vedicheritage.gov.in",
        # International Government
        "gov", "gov.uk", "europa.eu", "un.org", "who.int", "cdc.gov",
        "nih.gov", "nasa.gov", "noaa.gov", "epa.gov", "fda.gov"
    ],
    "academic": [
        "edu", "ac.uk", "ac.in", "arxiv.org", "jstor.org", "pubmed.ncbi.nlm.nih.gov",
        "scholar.google.com", "researchgate.net", "nature.com", "science.org",
        "springer.com", "sciencedirect.com", "ieee.org", "acm.org",
        "thelancet.com", "bmj.com", "jama.jamanetwork.com"
    ],
    "legal": [
        "indiankanoon.org", "supremecourtofindia.nic.in", "livelaw.in",
        "barandbench.com", "justia.com", "law.cornell.edu", "scotusblog.com"
    ],
    "news_trusted": [
        "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "thehindu.com",
        "theguardian.com", "nytimes.com", "wsj.com", "ft.com", "economist.com",
        "aljazeera.com", "npr.org", "pbs.org"
    ],
    "fact_checkers": [
        "snopes.com", "factcheck.org", "politifact.com", "fullfact.org",
        "altnews.in", "boomlive.in", "thequint.com/news/webqoof",
        "africacheck.org", "factcheckni.org"
    ],
    "religious_scholarly": [
        "sacred-texts.com", "britannica.com", "oxfordreference.com",
        "encyclopedia.com", "worldcat.org"
    ],
    "international_orgs": [
        "un.org", "who.int", "worldbank.org", "imf.org", "oecd.org",
        "wto.org", "icc-cpi.int", "icj-cij.org", "unhcr.org"
    ],
    "untrusted": [
        "quora.com", "reddit.com", "x.com", "facebook.com",
        "instagram.com", "medium.com", "linkedin.com"
    ]
}


# ==============================================================================
# DOMAIN TRUST FUNCTIONS
# ==============================================================================

def extract_domain(url: str) -> str:
    """Extract domain from URL for trust scoring."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Remove www. prefix
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    except:
        return url


def get_domain_trust_level(url: str) -> Literal["High", "Medium", "Low"]:
    """
    Determine trust level of a domain based on universal catalog.
    
    Returns:
        "High" - Government, academic, legal, major news, fact-checkers
        "Medium" - Other news sources, Wikipedia, established organizations
        "Low" - Social media, forums, blogs, unknown sources
    """
    domain = extract_domain(url)
    
    # Check untrusted first
    for untrusted in TRUSTED_DOMAINS["untrusted"]:
        if untrusted in domain or domain in untrusted:
            return "Low"
    
    # Check high-trust categories
    high_trust_categories = [
        "government", "academic", "legal", "fact_checkers", 
        "religious_scholarly", "international_orgs"
    ]
    
    for category in high_trust_categories:
        for trusted in TRUSTED_DOMAINS[category]:
            if trusted in domain or domain in trusted:
                return "High"
    
    # Check news sources (high trust)
    for trusted_news in TRUSTED_DOMAINS["news_trusted"]:
        if trusted_news in domain or domain in trusted_news:
            return "High"
    
    # Wikipedia gets medium trust (needs citation verification)
    if "wikipedia.org" in domain:
        return "Medium"
    
    # Default to Low for unknown sources
    return "Low"


def is_trusted_domain(url: str, suggested_domains: List[str] = None) -> bool:
    """
    Check if URL is from a trusted domain.
    
    Args:
        url: URL to check
        suggested_domains: Optional list of domain-specific trusted sources
    
    Returns:
        True if domain is trusted, False otherwise
    """
    domain = extract_domain(url)
    
    # Check against suggested domains if provided
    if suggested_domains:
        for suggested in suggested_domains:
            if suggested in domain or domain in suggested:
                return True
    
    # Check against universal trust catalog
    trust_level = get_domain_trust_level(url)
    return trust_level == "High"
